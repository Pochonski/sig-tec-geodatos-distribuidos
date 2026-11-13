#!/usr/bin/env python3
"""Prueba permisos y restricciones con login TCP real; revierte los datos de prueba."""
import json
import subprocess
import uuid

from migrate import ROLE, apply, configuration, containers, sql


def denied(statement, state='42501'):
    escaped = statement.replace("'", "''")
    return f"""
DO $test$
BEGIN
    BEGIN
        EXECUTE '{escaped}';
        RAISE EXCEPTION 'La operación debía ser rechazada';
    EXCEPTION WHEN SQLSTATE '{state}' THEN
        NULL;
    END;
END
$test$;
"""


def inventory():
    ids = subprocess.check_output(['docker', 'ps', '-aq'], text=True).split()
    details = json.loads(subprocess.check_output(['docker', 'inspect', *ids], text=True))
    return {item['Id']: (item['State']['StartedAt'], item['State']['Status'],
                         item['Mounts']) for item in details}


def contents(nodes):
    tables = {'central': ['ops.requests', 'ops.decisions', 'ops.audit'],
              'cartago': ['cartago.edificios', 'ops.applied_operations']}
    return {(node, table): sql(nodes[node],
            f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]') FROM {table} t;")
            for node in tables for table in tables[node]}


def verify():
    nodes, values = containers(), configuration()
    before_containers, before_data = inventory(), contents(nodes)
    # Una segunda aplicación verifica que no se pierden ni cambian filas.
    apply(nodes, values)
    assert before_data == contents(nodes), 'La reejecución cambió datos'
    print('Reejecución: datos existentes conservados.')
    for node, container in nodes.items():
        flags = sql(container, f"SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls FROM pg_roles WHERE rolname = '{ROLE}';")
        assert flags == 'f', 'Atributos de rol excesivos'
        password = values[f'OPS_{node.upper()}_CLI_PASSWORD']
        assert sql(container, 'SELECT current_user;', password) == ROLE
        operation = str(uuid.uuid4())
        row = f"'{operation}', 1, 1, 'Nombre de prueba'"
        statement = 'BEGIN;\n'
        statement += denied('CREATE TABLE ops.no_permitida (id int)')
        statement += denied('CREATE ROLE ops_no_permitido')
        if node == 'central':
            statement += f'INSERT INTO ops.requests (operation_id, campus_id, building_id, new_name) VALUES ({row});\n'
            statement += f"SELECT operation_id FROM ops.requests WHERE operation_id = '{operation}';\n"
            statement += denied(f"INSERT INTO ops.requests (operation_id, campus_id, building_id, new_name) VALUES ('{operation}', 1, 2, 'Otro nombre')", '23505')
            statement += denied(f"INSERT INTO ops.audit (operation_id, campus_id, building_id, new_name) VALUES ('{operation}', 1, 2, 'Otro nombre')", '23503')
            statement += denied(f"INSERT INTO ops.decisions (operation_id, decision) VALUES ('{uuid.uuid4()}', 'COMMIT')", '23503')
            statement += denied(f"INSERT INTO ops.decisions (operation_id, decision) VALUES ('{operation}', 'PENDING')", '23514')
            statement += f"INSERT INTO ops.decisions (operation_id, decision) VALUES ('{operation}', 'COMMIT');\n"
            statement += f'INSERT INTO ops.audit (operation_id, campus_id, building_id, new_name) VALUES ({row});\n'
            statement += denied(f'INSERT INTO ops.audit (operation_id, campus_id, building_id, new_name) VALUES ({row})', '23505')
            statement += denied(f"INSERT INTO ops.decisions (operation_id, decision) VALUES ('{operation}', 'ABORT')", '23505')
            for table in ('requests', 'decisions', 'audit'):
                statement += f'SELECT * FROM ops.{table};\n'
                statement += denied(f'UPDATE ops.{table} SET operation_id = operation_id')
                statement += denied(f'DELETE FROM ops.{table}')
                statement += denied(f'TRUNCATE ops.{table}')
            statement += denied(f"INSERT INTO ops.audit (operation_id, campus_id, building_id, new_name, recorded_at) VALUES ('{uuid.uuid4()}', 1, 1, 'X', now())")
        else:
            statement += 'SELECT id, campus_id, nombre FROM cartago.edificios;\n'
            statement += "UPDATE cartago.edificios SET nombre = 'Cambio reversible de prueba' WHERE id = 1;\n"
            statement += "DO $$ BEGIN IF NOT EXISTS (SELECT FROM cartago.edificios WHERE id = 1 AND nombre = 'Cambio reversible de prueba') THEN RAISE EXCEPTION 'No se actualizó nombre'; END IF; END $$;\n"
            for query in (
                'UPDATE cartago.edificios SET id = id',
                'UPDATE cartago.edificios SET campus_id = campus_id',
                "INSERT INTO cartago.edificios VALUES (6, 1, 'No permitido')",
                'DELETE FROM cartago.edificios', 'TRUNCATE cartago.edificios',
                'ALTER TABLE cartago.edificios ADD COLUMN no_permitida int',
            ):
                statement += denied(query)
            statement += f'INSERT INTO ops.applied_operations (operation_id, campus_id, building_id, new_name) VALUES ({row});\n'
            statement += 'SELECT * FROM ops.applied_operations;\n'
            statement += denied(f'INSERT INTO ops.applied_operations (operation_id, campus_id, building_id, new_name) VALUES ({row})', '23505')
            statement += denied(f"INSERT INTO ops.applied_operations (operation_id, campus_id, building_id, new_name) VALUES ('{uuid.uuid4()}', 3, 1, 'X')", '23514')
            statement += denied('UPDATE ops.applied_operations SET new_name = new_name')
            statement += denied('DELETE FROM ops.applied_operations')
        statement += 'ROLLBACK;'
        sql(container, statement, password)
        print(f'{node}: login TCP, permisos permitidos/rechazados, UUID y restricciones correctos.')
    assert contents(nodes) == before_data, 'Las pruebas alteraron datos persistentes'
    assert inventory() == before_containers, 'Cambió el estado o montaje de un contenedor'
    print('Pruebas revertidas; contenedores, volúmenes y datos conservados.')


if __name__ == '__main__':
    try:
        verify()
    except (RuntimeError, OSError, AssertionError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
