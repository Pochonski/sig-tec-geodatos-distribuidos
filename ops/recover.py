#!/usr/bin/env python3
"""Reconcilia una operación 2PC por UUID usando su decisión central duradera."""
import argparse
from contextlib import ExitStack
import json
import sys
from uuid import UUID

import psycopg
from psycopg import sql

import rename as protocol


def decision(control, operation):
    row = control.execute('SELECT decision FROM ops.decisions WHERE operation_id = %s',
                          (operation,)).fetchone()
    return row[0] if row else None


def evidence(participants, operation, payload):
    result = {}
    for conn, node, table in participants:
        marker = protocol.marker(conn, table, operation)
        result[node.name] = {
            'marker': marker is not None,
            'matches_request': marker == payload,
            'prepared': protocol.prepared(conn, operation, node),
        }
    return result


def recover(operation, values=None):
    operation = UUID(str(operation))
    values = protocol.configuration() if values is None else values
    try:
        with ExitStack() as resources:
            def open_node(node):
                conn = protocol.connect(node, values)
                resources.callback(conn.close)
                return conn

            # Si el central no responde, no se consulta ni modifica Cartago.
            control = open_node(protocol.CENTRAL)
            control.execute('SELECT pg_catalog.pg_advisory_lock(%s)',
                            (protocol.lock_key(operation),))
            payload = control.execute(
                'SELECT campus_id, building_id, new_name FROM ops.requests WHERE operation_id = %s',
                (operation,),
            ).fetchone()
            if payload is None:
                raise protocol.Pending('Solicitud no encontrada; requiere reconciliación sin inventar datos.')
            node = protocol.CAMPUSES.get(payload[0])
            if node is None:
                raise protocol.Pending('Campus aún no integrado para recuperación.')
            durable = decision(control, operation)
            campus = open_node(node)
            participants = ((campus, node, 'applied_operations'),
                            (control, protocol.CENTRAL, 'audit'))
            before = evidence(participants, operation, payload)

            # Verificar ambos participantes antes de resolver cualquiera.
            for state in before.values():
                if state['marker'] and (not state['matches_request'] or state['prepared']):
                    raise protocol.Pending('Marcador incompatible o rama duplicada; reconciliación pendiente.')
            if durable is None:
                if any(state['marker'] for state in before.values()):
                    raise protocol.Pending('Hay cambios aplicados sin decisión; reconciliación pendiente.')
                # El mismo bloqueo que rename.py impide una decisión concurrente.
                # La inserción autocommit debe ser reconocida antes de revertir.
                control.execute(
                    "INSERT INTO ops.decisions (operation_id, decision) VALUES (%s, 'ABORT') "
                    'ON CONFLICT (operation_id) DO NOTHING', (operation,),
                )
                durable = decision(control, operation)

            if durable == 'COMMIT':
                if any(not state['marker'] and not state['prepared'] for state in before.values()):
                    raise protocol.Pending('COMMIT duradero, pero falta una rama y su marcador; '
                                           'reconciliación pendiente. No se reconstruyen cambios.')
                command = 'COMMIT PREPARED {}'
            elif durable == 'ABORT':
                if any(state['marker'] for state in before.values()):
                    raise protocol.Pending('ABORT con cambios aplicados; reconciliación pendiente.')
                command = 'ROLLBACK PREPARED {}'
            else:
                raise protocol.Pending('Decisión incierta; ninguna rama fue resuelta.')

            resolved = []
            for conn, target, _ in participants:
                if not before[target.name]['prepared']:
                    continue
                # Revalidar en la misma sesión que conserva el bloqueo. Una
                # pérdida de conexión o de confirmación deja las demás ramas intactas.
                if decision(control, operation) != durable:
                    raise protocol.Pending('No se pudo revalidar la decisión; operación pendiente.')
                conn.execute(sql.SQL(command).format(sql.Literal(protocol.gid(operation, target))))
                resolved.append(target.name)

            after = evidence(participants, operation, payload)
            if decision(control, operation) != durable:
                raise protocol.Pending('Decisión no verificable al finalizar; operación pendiente.')
            if any(state['prepared'] for state in after.values()):
                raise protocol.Pending('Aún existen ramas preparadas; recuperación pendiente.')
            if durable == 'COMMIT' and not all(state['matches_request'] for state in after.values()):
                raise protocol.Pending('Faltan marcadores confirmados; reconciliación pendiente.')
            if durable == 'ABORT' and any(state['marker'] for state in after.values()):
                raise protocol.Pending('Persisten marcadores tras ABORT; reconciliación pendiente.')
            return {'operation_id': str(operation),
                    'status': 'completed' if durable == 'COMMIT' else 'aborted',
                    'decision': durable, 'resolved': resolved, 'participants': after}
    except psycopg.Error as error:
        raise protocol.Pending(f'Recuperación pendiente por error de base de datos '
                               f'({error.sqlstate or "conexion"}); volver a consultar la decisión.') from None
    except KeyboardInterrupt:
        raise protocol.Pending('Recuperación interrumpida; repetir con el mismo UUID.') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation_id', type=UUID)
    args = parser.parse_args()
    try:
        result = recover(args.operation_id)
    except protocol.Pending as error:
        result = {'operation_id': str(args.operation_id), 'status': 'pending', 'message': str(error)}
        code = 2
    except protocol.OperationError as error:
        result = {'operation_id': str(args.operation_id), 'status': 'error', 'message': str(error)}
        code = 1
    else:
        code = 0
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
