#!/usr/bin/env python3
"""Aplicación vigilada y verificación del archivado WAL, sin PITR."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import runtime
import psycopg
from psycopg import sql
from psycopg.rows import tuple_row

from backup import admin, origin_state
from migrate import containers
from rename import configuration
from verify import inventory

ROOT = Path(__file__).resolve().parent
PROJECT = runtime.config()['project']
STATE = ROOT / '.wal-state.json' if PROJECT == 'sig-tec-ops' else ROOT / '.runtime-state' / PROJECT / 'wal.json'
REPORT = ROOT / 'wal-results.json' if PROJECT == 'sig-tec-ops' else ROOT / f'wal-{PROJECT}-results.json'
COMPOSE = ['docker', 'compose', '-p', 'sig-tec-ops', '--env-file', str(ROOT / '.env'),
           '-f', str(ROOT / 'compose.yaml')]
ARCHIVE_COMMAND = runtime.config().get('archive_command', '/bin/sh /opt/sig-tec-ops/archive-wal.sh "%p" "%f" /wal-archive')


class SafetyError(Exception):
    pass


def run(args):
    proc = subprocess.run(args, capture_output=True, text=True, encoding='utf-8')
    if proc.returncode:
        raise SafetyError('Falló una herramienta; no continuar sin revisar el estado. Diagnóstico omitido.')
    return proc.stdout.strip()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    path.chmod(0o600)


def operation_rows(values):
    result = {}
    for node in runtime.config()['nodes']:
        tables = ('ops.requests','ops.decisions','ops.audit') if node == 'central' else ('ops.applied_operations',node+'.edificios')
        with admin(node, values) as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            with conn.cursor(row_factory=tuple_row) as cursor:
                for table in tables:
                    cursor.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier(*table.split('.'))))
                    key = node+'.'+table if node not in ('central','cartago') and table.startswith('ops.') else table
                    result[key] = {row[0]: row for row in cursor.fetchall()}
    return result


def row_hashes(values):
    return {table: {str(key): hashlib.sha256(json.dumps(row, default=str, ensure_ascii=False).encode()).hexdigest()
                    for key, row in rows.items()} for table, rows in operation_rows(values).items()}


def settings(conn):
    return {name: conn.execute('SELECT current_setting(%s) AS value', (name,)).fetchone()['value']
            for name in ('archive_mode', 'archive_command', 'max_prepared_transactions', 'wal_level')}


def archiver(conn):
    row = conn.execute('SELECT archived_count, last_archived_wal, last_archived_time, '
                       'failed_count, last_failed_wal, last_failed_time, stats_reset FROM pg_stat_archiver').fetchone()
    return {key: value.isoformat() if hasattr(value, 'isoformat') else value for key, value in row.items()}


def mounts(container):
    info = json.loads(run(['docker', 'inspect', container]))[0]
    return {m['Destination']: m.get('Name', m['Source']) for m in info['Mounts']}


def other_inventory(nodes):
    # docker ps -q entrega IDs cortos; inventory() usa los completos.
    target_ids = {json.loads(run(['docker', 'inspect', cid]))[0]['Id'] for cid in nodes.values()}
    return {key: value for key, value in inventory().items() if key not in target_ids}


def preflight():
    if run(['git', 'branch', '--show-current']) != 'armando/operaciones':
        raise SafetyError('Rama incorrecta; detenerse.')
    free = shutil.disk_usage(ROOT)
    if free.free < max(5 * 2**30, free.total // 10):
        raise SafetyError('Espacio insuficiente en ops/: mínimo 5 GiB y 10% libre.')
    nodes, values = containers(), configuration()
    result = {'host_free_bytes': free.free, 'git_status': run(['git', 'status', '--short']), 'nodes': {}}
    for node, container in nodes.items():
        info = json.loads(run(['docker', 'inspect', container]))[0]
        expected_data = runtime.config().get('data_mounts',{}).get(node,f'{PROJECT}_{node}_data')
        if mounts(container).get('/var/lib/postgresql/data') != expected_data:
            raise SafetyError(f'{node}: volumen PGDATA inesperado.')
        local_image = json.loads(run(['docker', 'image', 'inspect', 'postgis/postgis:17-3.6']))[0]['Id']
        if info['Image'] != local_image:
            raise SafetyError('La imagen local difiere de la que ejecuta los nodos; no actualizarla automáticamente.')
        disk = run(['docker', 'exec', container, 'df', '-Pk', '/var/lib/postgresql/data']).splitlines()[-1].split()
        if int(disk[3]) * 1024 < max(5 * 2**30, int(disk[1]) * 1024 // 10):
            raise SafetyError(f'{node}: espacio insuficiente en el almacenamiento Docker.')
        with admin(node, values) as conn:
            if conn.execute('SELECT gid FROM pg_prepared_xacts').fetchall():
                raise SafetyError(f'{node}: hay transacciones preparadas; no se resolverán automáticamente.')
            if conn.execute("SELECT pid FROM pg_stat_activity WHERE application_name='sig-tec-ops-rename'").fetchall():
                raise SafetyError(f'{node}: hay sesiones de coordinación activas.')
            if conn.execute("SELECT current_setting('server_version_num')::int AS n").fetchone()['n'] // 10000 != 17:
                raise SafetyError('Se requiere PostgreSQL 17.')
            result['nodes'][node] = {'data_volume': expected_data, 'settings': settings(conn),
                                     'archiver': archiver(conn), 'free_bytes': int(disk[3]) * 1024}

    # No basta contar GID: una decisión COMMIT puede tener una rama perdida.
    data = operation_rows(values)
    requests, decisions = data['ops.requests'], data['ops.decisions']
    audits, markers = data['ops.audit'], {}
    for table, rows in data.items():
        if table.endswith('ops.applied_operations'): markers.update(rows)
    if set(requests) != set(decisions) or set(audits) - set(requests) or set(markers) - set(requests):
        raise SafetyError('Hay solicitudes sin decisión o marcadores huérfanos; detenerse para reconciliación.')
    for key, request in requests.items():
        if runtime.CAMPUSES.get(request[1]) not in nodes:
            raise SafetyError('Campus no soportado en esta comprobación.')
        decision = decisions[key][1]
        if decision == 'COMMIT':
            if key not in audits or key not in markers or audits[key][1:4] != request[1:4] or markers[key][1:4] != request[1:4]:
                raise SafetyError('Hay una decisión COMMIT sin sus dos efectos; detenerse.')
        elif decision != 'ABORT' or key in audits or key in markers:
            raise SafetyError('Hay una operación ABORT inconsistente; detenerse.')
    return nodes, values, result


def apply():
    if runtime.config().get('integrated'):
        raise SafetyError('Aplicar el overlay integrado revisado; este comando no recrea nodos integrados.')
    nodes, values, checks = preflight()
    run(COMPOSE + ['config', '--quiet'])
    baseline = {'checks': checks, 'data': origin_state(list(nodes), values), 'rows': row_hashes(values),
                'other_containers': other_inventory(nodes)}
    write(STATE, baseline)
    # Última comprobación antes de recrear solo los contenedores, no sus volúmenes.
    preflight()
    run(COMPOSE + ['up', '-d', '--no-deps', '--pull', 'never', '--wait', '--wait-timeout', '120', 'central', 'cartago'])
    current = containers()
    if origin_state(list(current), values) != baseline['data']:
        raise SafetyError('Los datos o GID cambiaron durante la aplicación; detenerse.')
    for node, container in current.items():
        mounted = mounts(container)
        if mounted.get('/var/lib/postgresql/data') != checks['nodes'][node]['data_volume']:
            raise SafetyError('Cambió un volumen PGDATA; detenerse.')
        if mounted.get('/wal-archive') != runtime.config().get('archive_volumes',{}).get(node,f'{PROJECT}_{node}_wal'):
            raise SafetyError('Montaje WAL incorrecto; detenerse.')
    others = other_inventory(current)
    if json.dumps(others, sort_keys=True) != json.dumps(baseline['other_containers'], sort_keys=True):
        raise SafetyError('Cambió otro contenedor; revisar antes de continuar.')
    print('Configuración aplicada solo a Central y Cartago; datos y volúmenes conservados.')


def preserved():
    if not STATE.exists():
        raise SafetyError('Falta el estado previo privado de apply; no afirmar conservación sin evidencia.')
    baseline = json.loads(STATE.read_text(encoding='utf-8'))
    nodes, values, _ = preflight()
    now = row_hashes(values)
    for table, rows in baseline['rows'].items():
        if any(now.get(table, {}).get(key) != value for key, value in rows.items()):
            raise SafetyError('Un registro anterior cambió o desapareció; detenerse.')
    others = other_inventory(nodes)
    if json.loads(json.dumps(others)) != baseline['other_containers']:
        raise SafetyError('Cambió el estado o montaje de otro contenedor.')
    for node, container in nodes.items():
        if mounts(container).get('/var/lib/postgresql/data') != baseline['checks']['nodes'][node]['data_volume']:
            raise SafetyError('Cambió el volumen de datos.')
    return baseline, nodes, values


def verify():
    baseline, nodes, values = preserved()
    result = {}
    for node, container in nodes.items():
        with admin(node, values) as conn:
            conn.autocommit = True
            current = settings(conn)
            if current['archive_mode'] != 'on' or current['archive_command'] != ARCHIVE_COMMAND or current['max_prepared_transactions'] != '10':
                raise SafetyError(f'{node}: parámetros inesperados.')
            before = archiver(conn)
            initial = baseline['checks']['nodes'][node]['archiver']
            if before['failed_count'] != initial['failed_count'] or before['stats_reset'] != initial['stats_reset']:
                raise SafetyError(f'{node}: aumentaron fallos o se reiniciaron estadísticas; detenerse.')
            # Generar WAL sin cambiar tablas; pg_switch_wal no avanza un segmento vacío.
            conn.execute("SELECT pg_logical_emit_message(false, 'sig-tec-ops', 'validacion archivado WAL')")
            segment = conn.execute('SELECT pg_walfile_name(pg_switch_wal()) AS segment').fetchone()['segment']
            size = conn.execute("SELECT pg_size_bytes(current_setting('wal_segment_size')) AS bytes").fetchone()['bytes']
            deadline = time.monotonic() + 90
            while True:
                stats = archiver(conn)
                if stats['failed_count'] != before['failed_count']:
                    raise SafetyError(f'{node}: el archivador registró un fallo; detenerse.')
                exists = subprocess.run(['docker', 'exec', '-u', 'postgres', container, 'test', '-r',
                                         '/wal-archive/' + segment], capture_output=True).returncode == 0
                if exists and stats['archived_count'] > before['archived_count']:
                    break
                if time.monotonic() > deadline:
                    raise SafetyError(f'{node}: expiró la espera de archivado; detenerse.')
                time.sleep(0.5)
            archived = '/wal-archive/' + segment
            if int(run(['docker', 'exec', '-u', 'postgres', container, 'stat', '-c', '%s', archived])) != size:
                raise SafetyError('Tamaño de segmento incorrecto.')
            digest = run(['docker', 'exec', '-u', 'postgres', container, 'sha256sum', archived]).split()[0]
            run(['docker', 'exec', '-u', 'postgres', container, '/usr/lib/postgresql/17/bin/pg_waldump',
                 '-p', '/wal-archive', '-n', '1', segment])
            result[node] = {'settings': current, 'volume': mounts(container)['/wal-archive'],
                            'segment': segment, 'size_bytes': size, 'sha256': digest,
                            'readable_by_postgres': True, 'pg_waldump': 'ok',
                            'before': before, 'after': stats, 'failed_count_delta': 0}
            print(f'{node}: {segment}, {size} bytes, WAL legible, failed_count sin aumento.')
    preserved()
    report = json.loads(REPORT.read_text(encoding='utf-8')) if REPORT.exists() else {'verifications': []}
    report['verifications'].append({'executed_at_utc': datetime.now(timezone.utc).isoformat(), 'nodes': result})
    report.update(base_commit=run(['git', 'rev-parse', 'HEAD']), preflight=baseline['checks'],
                  protected_rows={table: len(rows) for table, rows in baseline['rows'].items()},
                  previous_rows_unchanged=True, data_volumes_unchanged=True,
                  other_containers_unchanged=True, prepared_transactions=0)
    write(REPORT, report)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('preflight', 'apply', 'capture', 'verify', 'check-preserved'))
    args = parser.parse_args()
    try:
        if args.action == 'preflight':
            print(json.dumps(preflight()[2], ensure_ascii=False, indent=2))
        elif args.action == 'capture':
            nodes,values,checks=preflight()
            write(STATE,{'checks':checks,'data':origin_state(list(nodes),values),'rows':row_hashes(values),'other_containers':other_inventory(nodes)})
            print('Estado de verificación capturado sin cambios de configuración.')
        elif args.action == 'apply':
            apply()
        elif args.action == 'verify':
            verify()
        else:
            preserved()
            print('Registros previos, volúmenes y otros contenedores intactos; sin 2PC pendiente.')
    except SafetyError as error:
        print('DETENER: ' + str(error), file=sys.stderr)
        return 1
    except (psycopg.Error, OSError, ValueError, KeyError):
        print('DETENER: no se pudo verificar el estado; diagnóstico omitido para proteger credenciales.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
