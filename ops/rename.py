#!/usr/bin/env python3
"""Renombrado administrativo con 2PC; sin recuperación automática."""
import argparse
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent
ROLE = 'sig_tec_ops_cli'


class OperationError(Exception):
    """Solicitud inválida; el mensaje es seguro para la salida de la CLI."""


class Pending(OperationError):
    """Requiere reconciliación; no se debe inferir un aborto."""


@dataclass(frozen=True)
class Node:
    name: str
    port: int
    schema: str | None = None


CENTRAL = Node('central', 57430)
# Ampliar este registro al integrar otros campus. No aceptar esquemas del usuario.
CAMPUSES = {1: Node('cartago', 57431, 'cartago')}


def configuration():
    """Solo lectura: no genera ni modifica credenciales durante una operación."""
    try:
        values = {}
        for line in (ROOT / '.env').read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('\"\'')
        return values
    except (OSError, ValueError):
        raise OperationError('No se pudo leer ops/.env.') from None


def connect(node, values):
    password = values.get(f'OPS_{node.name.upper()}_CLI_PASSWORD')
    if not password:
        raise OperationError(f'Falta la contraseña local de CLI para {node.name}.')
    conn = psycopg.connect(
        host='127.0.0.1', port=node.port, dbname='sig_tec', user=ROLE,
        password=password, autocommit=True, connect_timeout=5,
        application_name='sig-tec-ops-rename',
        options='-c statement_timeout=15000 -c lock_timeout=10000 -c synchronous_commit=on',
    )
    return conn


def gid(operation, node):
    return f'sig-tec:ops:v1:{operation}:{node.name}'


def lock_key(operation):
    # Clave estable entre procesos; una colisión solo serializa UUID adicionales.
    digest = hashlib.sha256(b'sig-tec-ops:v1:' + operation.bytes).digest()
    return int.from_bytes(digest[:8], 'big', signed=True)


def prepared(conn, operation, node):
    return conn.execute(
        'SELECT EXISTS (SELECT FROM pg_catalog.pg_prepared_xacts '
        'WHERE gid = %s AND database = current_database())',
        (gid(operation, node),),
    ).fetchone()[0]


def marker(conn, table, operation):
    return conn.execute(sql.SQL(
        'SELECT campus_id, building_id, new_name FROM ops.{} WHERE operation_id = %s'
    ).format(sql.Identifier(table)), (operation,)).fetchone()


def completed(control, campus, operation, node, payload):
    # Los marcadores contienen el resultado original aunque otra operación
    # posterior haya renombrado el mismo edificio.
    return (
        marker(control, 'audit', operation) == payload
        and marker(campus, 'applied_operations', operation) == payload
        and not prepared(control, operation, CENTRAL)
        and not prepared(campus, operation, node)
    )


def aborted(control, campus, operation, node):
    return (
        marker(control, 'audit', operation) is None
        and marker(campus, 'applied_operations', operation) is None
        and not prepared(control, operation, CENTRAL)
        and not prepared(campus, operation, node)
    )


def rename(operation, campus_id, building_id, new_name, values=None, *, _checkpoint=None):
    operation = UUID(str(operation))
    if campus_id not in CAMPUSES:
        raise OperationError('Campus no soportado; actualmente solo Cartago (1).')
    if not -(2**63) <= building_id < 2**63:
        raise OperationError('El id debe ser un bigint.')
    if not new_name.strip() or '\x00' in new_name:
        raise OperationError('El nombre no puede estar vacío ni contener NUL.')
    values = configuration() if values is None else values
    node = CAMPUSES[campus_id]
    for target in (CENTRAL, node):
        if not values.get(f'OPS_{target.name.upper()}_CLI_PASSWORD'):
            raise OperationError(f'Falta la contraseña local de CLI para {target.name}.')
    payload = (campus_id, building_id, new_name)
    try:
        # close() descarta las transacciones abiertas, pero nunca resuelve una
        # transacción preparada. No usar contextos que hagan COMMIT implícito.
        with ExitStack() as resources:
            def open_node(target):
                conn = connect(target, values)
                resources.callback(conn.close)
                return conn

            control = open_node(CENTRAL)
            # La sesión se mantiene hasta verificar los marcadores. No bloquea
            # filas de requests que deben consultar las transacciones participantes.
            control.execute('SELECT pg_catalog.pg_advisory_lock(%s)', (lock_key(operation),))
            created = control.execute(
                'INSERT INTO ops.requests (operation_id, campus_id, building_id, new_name) '
                'VALUES (%s, %s, %s, %s) ON CONFLICT (operation_id) DO NOTHING '
                'RETURNING operation_id', (operation, *payload),
            ).fetchone() is not None
            saved = control.execute(
                'SELECT campus_id, building_id, new_name FROM ops.requests WHERE operation_id = %s',
                (operation,),
            ).fetchone()
            if saved != payload:
                raise OperationError('UUID reutilizado con datos diferentes.')

            decision = control.execute(
                'SELECT decision FROM ops.decisions WHERE operation_id = %s', (operation,),
            ).fetchone()
            campus = open_node(node)
            if not created:
                if decision == ('COMMIT',) and completed(control, campus, operation, node, payload):
                    return {'operation_id': str(operation), 'status': 'completed', 'repeated': True}
                if decision == ('ABORT',) and aborted(control, campus, operation, node):
                    return {'operation_id': str(operation), 'status': 'aborted', 'repeated': True}
                raise Pending('Solicitud existente incompleta; ejecutar ops/recover.py con su UUID.')
            if (decision or marker(control, 'audit', operation)
                    or marker(campus, 'applied_operations', operation)
                    or prepared(control, operation, CENTRAL)
                    or prepared(campus, operation, node)):
                raise Pending('Se encontraron evidencias previas; requiere reconciliación.')

            audit = open_node(CENTRAL)
            campus.execute('BEGIN')
            updated = campus.execute(sql.SQL(
                'UPDATE {}.edificios SET nombre = %s WHERE id = %s AND campus_id = %s RETURNING id'
            ).format(sql.Identifier(node.schema)), (new_name, building_id, campus_id)).fetchone()
            if updated is None:
                raise Pending('El edificio no existe en el campus; la solicitud quedó pendiente.')
            campus.execute(
                'INSERT INTO ops.applied_operations (operation_id, campus_id, building_id, new_name) '
                'VALUES (%s, %s, %s, %s)', (operation, *payload),
            )
            audit.execute('BEGIN')
            audit.execute(
                'INSERT INTO ops.audit (operation_id, campus_id, building_id, new_name) '
                'VALUES (%s, %s, %s, %s)', (operation, *payload),
            )
            for participant, target in ((campus, node), (audit, CENTRAL)):
                participant.execute(sql.SQL('PREPARE TRANSACTION {}').format(
                    sql.Literal(gid(operation, target))))
                if target == node and _checkpoint:
                    _checkpoint('after_first_prepare')
            if _checkpoint:
                _checkpoint('after_both_prepare')

            # La conexión control conserva el bloqueo y usa una transacción
            # independiente de ambas ramas. synchronous_commit=on fuerza WAL local.
            control.execute(
                "INSERT INTO ops.decisions (operation_id, decision) VALUES (%s, 'COMMIT')",
                (operation,),
            )
            if _checkpoint:
                _checkpoint('after_decision')
            # Solo llegar aquí si el servidor confirmó la escritura de la decisión.
            for participant, target in ((campus, node), (audit, CENTRAL)):
                participant.execute(sql.SQL('COMMIT PREPARED {}').format(
                    sql.Literal(gid(operation, target))))
                if target == node and _checkpoint:
                    _checkpoint('after_first_commit')
            if not completed(control, campus, operation, node, payload):
                raise Pending('COMMIT decidido, pero faltan evidencias de aplicación completa.')
            return {'operation_id': str(operation), 'status': 'completed', 'repeated': False}
    except psycopg.Error as error:
        # No imprimir mensajes del servidor, DSN, SQL ni secretos. Incluso si se
        # perdió la respuesta al guardar COMMIT, conservar las ramas preparadas.
        code = error.sqlstate or 'conexion'
        raise Pending(f'Estado pendiente por error de base de datos ({code}); '
                      'no se resolvieron automáticamente transacciones preparadas.') from None
    except KeyboardInterrupt:
        raise Pending('Operación interrumpida; comprobar la decisión y los marcadores '
                      'antes de resolver cualquier transacción preparada.') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation_id', type=UUID)
    parser.add_argument('campus_id', type=int)
    parser.add_argument('building_id', type=int)
    parser.add_argument('new_name')
    args = parser.parse_args()
    try:
        result = rename(args.operation_id, args.campus_id, args.building_id, args.new_name)
    except Pending as error:
        print(json.dumps({'operation_id': str(args.operation_id), 'status': 'pending',
                          'message': str(error)}, ensure_ascii=False))
        return 2
    except OperationError as error:
        print(json.dumps({'operation_id': str(args.operation_id), 'status': 'error',
                          'message': str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
