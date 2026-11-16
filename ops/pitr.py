#!/usr/bin/env python3
"""Prueba PITR real en una copia aislada de Cartago; nunca restaura sobre un origen."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from uuid import uuid4

import psycopg

import runtime
import backup
import wal
from verify import inventory

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / 'pitr-runs'
REPORT = ROOT / 'pitr-results.json'


class PITRError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise PITRError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def lsn_value(lsn):
    require(bool(re.fullmatch(r'[0-9A-F]+/[0-9A-F]+', lsn)), 'LSN inválido.')
    high, low = lsn.split('/')
    return (int(high, 16) << 32) + int(low, 16)


def required_segments(start, end, timeline, size):
    first, last = lsn_value(start), lsn_value(end)
    require(last > first and size > 0 and 2**32 % size == 0, 'Rango WAL inválido.')
    require(0 < timeline < 2**32, 'Timeline inválido.')
    per_log = 2**32 // size
    return [f'{timeline:08X}{number // per_log:08X}{number % per_log:08X}'
            for number in range(first // size, (last - 1) // size + 1)]


def archive_hashes(container):
    output = wal.run(['docker', 'exec', '-u', 'postgres', container, 'find', '/wal-archive',
                      '-maxdepth', '1', '-type', 'f', '-name', '[0-9A-F]*',
                      '-exec', 'sha256sum', '--', '{}', '+'])
    return {Path(line.split(maxsplit=1)[1]).name: line.split()[0]
            for line in output.splitlines() if line}


def verify_old_backups():
    """Solo lectura: no regenerar logical.list de respaldos anteriores."""
    checked = []
    for manifest in sorted(backup.BACKUPS.glob('*/manifest.json')):
        directory, report = backup.load(manifest.parent)
        for node, item in report['nodes'].items():
            folder = directory / node
            if 'logical' in item:
                require(backup.checksum(folder / 'logical.dump') == item['logical']['sha256'],
                        'Un respaldo lógico previo no coincide con su checksum.')
                with (folder / 'logical.dump').open('rb') as stream:
                    backup.command(['docker', 'run', '--rm', '-i', '--pull', 'never', '--network', 'none',
                                    '--read-only', '--entrypoint', 'pg_restore', item['image'], '--list'], source=stream)
            if 'physical' in item:
                require(backup.checksum(folder / 'physical/base.tar') == item['physical']['tar_sha256'],
                        'Un respaldo físico previo no coincide con su checksum.')
                backup.verify_physical(folder, item['image'])
        checked.append(str(directory.relative_to(ROOT.parent)))
    require(bool(checked), 'No hay respaldos previos verificados; revisar antes de escribir.')
    return checked


def prepare_copy(source, destination, target, server_settings=None):
    require(bool(re.fullmatch(r'sig_tec_pitr_[0-9a-f]{32}', target)), 'Nombre de punto inválido.')
    source, destination = Path(source).resolve(), Path(destination)
    require(source.is_relative_to(backup.BACKUPS.resolve()) and source.is_dir(), 'Origen de respaldo no permitido.')
    require(destination.resolve().is_relative_to(RUNS.resolve()), 'Destino fuera del aislamiento PITR.')
    require(not destination.exists() and not destination.is_symlink(), 'El destino debe ser nuevo.')
    require(not destination.resolve().is_relative_to(source), 'No escribir dentro del respaldo verificado.')
    require((source / 'PG_VERSION').read_text(encoding='utf-8').strip() == '17', 'El respaldo debe ser PostgreSQL 17.')
    require(not (source / 'standby.signal').exists() and not (source / 'recovery.signal').exists(),
            'Se requiere un respaldo primario, sin señales de recuperación anteriores.')
    shutil.copytree(source, destination, symlinks=True)
    # Solo se edita la copia nueva. Sin conexión primaria ni archivado desde el clon.
    with (destination / 'postgresql.auto.conf').open('a', encoding='utf-8') as config:
        config.write("\n# Configuración exclusiva de la copia de prueba PITR\n"
                     "archive_mode = off\narchive_command = ''\nlisten_addresses = ''\n"
                     "hot_standby = on\nmax_prepared_transactions = 10\n"
                     "primary_conninfo = ''\nprimary_slot_name = ''\nmax_logical_replication_workers = 0\n"
                     'restore_command = \'/bin/cp -- "/wal-archive/%f" "%p"\'\n'
                     f"recovery_target_name = '{target}'\nrecovery_target_timeline = 'current'\n"
                     "recovery_target_action = 'pause'\n")
    if server_settings:
        allowed={'max_connections','max_worker_processes','max_wal_senders','max_prepared_transactions','max_locks_per_transaction','max_replication_slots'}
        with (destination/'postgresql.auto.conf').open('a',encoding='utf-8') as config:
            for name,value in server_settings.items():
                require(name in allowed and str(value).isdigit(), 'Parámetro de recuperación no permitido.')
                config.write(name+' = '+str(value)+'\n')
            config.write("wal_level = logical\n" if runtime.config().get('integrated') else '')
    (destination / 'recovery.signal').touch(mode=0o600)
    destination.chmod(0o700)
    return destination


def clone_query(container, statement):
    query = "SET search_path=pg_catalog; SELECT COALESCE(json_agg(q), '[]'::json) FROM (" + statement + ') q'
    result = subprocess.run(['docker', 'exec', container, 'psql', '-X', '-qAt', '-U', 'postgres',
                             '-d', 'sig_tec', '-v', 'ON_ERROR_STOP=1', '-c', query],
                            capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise PITRError('La copia aún no acepta la consulta; revisar logs privados si persiste.')
    return json.loads(result.stdout)


def logs(container):
    result = subprocess.run(['docker', 'logs', container], capture_output=True, text=True, encoding='utf-8')
    return result.stdout + result.stderr


def wait_recovery(container, *, paused):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        running = json.loads(wal.run(['docker', 'inspect', container]))[0]['State']['Running']
        require(running, 'La copia PostgreSQL terminó antes de completar la recuperación.')
        try:
            state = clone_query(container,
                "SELECT pg_is_in_recovery() AS in_recovery, "
                "CASE WHEN pg_is_in_recovery() THEN pg_get_wal_replay_pause_state() ELSE 'finished' END AS state, "
                "pg_last_wal_replay_lsn()::text AS replay_lsn, current_setting('recovery_target_name') AS target")
        except PITRError:
            time.sleep(0.5)
            continue
        state = state[0]
        if paused:
            require(state['in_recovery'], 'La copia salió de recovery sin comprobar el punto nombrado.')
            if state['state'] == 'paused':
                return state
        elif not state['in_recovery']:
            return state
        time.sleep(0.5)
    raise PITRError('Tiempo agotado esperando el estado de recuperación esperado.')


def wait_wal(container, values, segments, initial_failed, size):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        with backup.admin('cartago', values) as conn:
            stats = wal.archiver(conn)
        require(stats['failed_count'] == initial_failed, 'El archivador de Cartago registró fallos.')
        digests = archive_hashes(container)
        if all(segment in digests for segment in segments):
            for segment in segments:
                actual_size = int(wal.run(['docker', 'exec', '-u', 'postgres', container, 'stat', '-c', '%s',
                                           '/wal-archive/' + segment]))
                require(actual_size == size, 'Un segmento requerido no tiene el tamaño esperado.')
            return {segment: digests[segment] for segment in segments}, stats
        time.sleep(0.5)
    raise PITRError('No se archivó toda la secuencia WAL requerida.')


def wait_originals(nodes,values,expected):
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        if backup.origin_state(nodes,values)==expected: return
        time.sleep(0.5)
    raise PITRError('Los datos originales no convergieron al estado esperado; no reparar automáticamente.')


def exercise(*, keep_copy=False):
    os.umask(0o077)
    nodes, values, checks = wal.preflight()
    for node in nodes:
        require(checks['nodes'][node]['settings']['archive_mode'] == 'on', 'El archivado debe estar habilitado.')
        require(checks['nodes'][node]['settings']['archive_command'] == wal.ARCHIVE_COMMAND, 'archive_command inesperado.')
        require(checks['nodes'][node]['archiver']['failed_count'] == 0, 'Revisar fallos de archivado anteriores.')
        with backup.admin(node, values) as conn:
            require(all(conn.execute('SELECT current_setting(%s) AS v', (name,)).fetchone()['v'] == 'on'
                        for name in ('fsync', 'full_page_writes', 'synchronous_commit')), 'Durabilidad no habilitada.')
    old_backups = verify_old_backups()
    source = backup.sources(['cartago'])['cartago']
    archive_volume = wal.mounts(nodes['cartago']).get('/wal-archive')
    require(archive_volume == runtime.config().get('archive_volumes',{}).get('cartago',runtime.config()['project'] + '_cartago_wal'), 'Volumen WAL de Cartago inesperado.')
    before = backup.origin_state(list(nodes), values)
    before_containers = inventory()
    old_archives = {node: archive_hashes(cid) for node, cid in nodes.items()}
    token = uuid4().hex
    directory = RUNS / token
    directory.mkdir(parents=True, mode=0o700)
    report = {'run_id': token, 'started_at_utc': utc(), 'status': 'incomplete', 'stage': 'preflight',
              'base_commit': wal.run(['git', 'rev-parse', 'HEAD']), 'preflight': checks,
              'previous_backups_verified': old_backups,
              'artifacts': str(directory.relative_to(ROOT.parent))}
    container = None
    success = False

    def checkpoint(stage):
        report['stage'] = stage
        backup.save(directory / 'report.json', report)
        backup.save(REPORT, report)
        print('PITR: ' + stage, flush=True)

    try:
        checkpoint('insert_fixture')
        integrated = runtime.config().get('integrated',False)
        projection = "id,campus_id,nombre,codigo,area,pisos,encode(public.ST_AsEWKB(geom),'hex') AS geom_hex" if integrated else 'id,campus_id,nombre'
        with backup.admin('cartago', values) as conn:
            if integrated:
                fixture = conn.execute('INSERT INTO sig.edificios (nombre,codigo,area,pisos,geom) VALUES (%s,%s,4,1,public.ST_MakeEnvelope(500000,1100000,500002,1100002,8908)) RETURNING '+projection, ('Fixture PITR '+token,'PITR-'+token)).fetchone()
            for _ in range(0 if integrated else 10):
                identifier = (uuid4().int % 10**14) * 5 + 1
                fixture = conn.execute('INSERT INTO cartago.edificios (id, campus_id, nombre) VALUES (%s, 1, %s) '
                                       'ON CONFLICT (id) DO NOTHING RETURNING id, campus_id, nombre',
                                       (identifier, 'Fixture PITR ' + token)).fetchone()
                if fixture:
                    break
            require(fixture is not None, 'No se encontró identificador libre; no se sobrescribió ninguna fila.')
        report['fixture'] = fixture
        expected_copy = backup.origin_state(['cartago'], values)['cartago']['data']
        checkpoint('new_physical_backup')
        new_backup = backup.create(['cartago'], 'physical', publish_summary=False)
        _, manifest = backup.load(new_backup)
        item = manifest['nodes']['cartago']
        report['backup'] = {'directory': str(new_backup.relative_to(ROOT.parent)), 'physical_verified': True,
                             'sha256': item['physical']['tar_sha256'], 'verified_at_utc': utc()}
        data = new_backup / 'cartago/physical/data'
        backup_manifest = json.loads((data / 'backup_manifest').read_text(encoding='utf-8'))
        ranges = backup_manifest['WAL-Ranges']
        require(len(ranges) == 1, 'El respaldo cruza timelines; requiere una prueba distinta.')
        wal_range = ranges[0]
        checkpoint('named_restore_point')
        wal.preflight()
        point = 'sig_tec_pitr_' + token
        with backup.admin('cartago', values) as conn:
            conn.autocommit = True
            target_lsn = conn.execute('SELECT pg_create_restore_point(%s)::text AS lsn', (point,)).fetchone()['lsn']
            require(lsn_value(target_lsn) > lsn_value(wal_range['End-LSN']), 'El punto no es posterior al respaldo.')
        report['restore_point'] = {'name': point, 'lsn': target_lsn, 'created_at_utc': utc(),
                                   'backup_end_lsn': wal_range['End-LSN']}
        checkpoint('delete_only_fixture')
        with backup.admin('cartago', values) as conn:
            deleted = conn.execute('DELETE FROM cartago.edificios WHERE id=%s AND campus_id=1 AND nombre=%s '
                                   'RETURNING '+projection, (fixture['id'], fixture['nombre'])).fetchone()
            require(deleted == fixture, 'La eliminación no coincidió exactamente con el fixture propio.')
        with backup.admin('cartago', values) as conn:
            conn.autocommit = True
            delete_lsn = conn.execute('SELECT pg_current_wal_flush_lsn()::text AS lsn').fetchone()['lsn']
            end_lsn = conn.execute('SELECT pg_switch_wal()::text AS lsn').fetchone()['lsn']
            size = conn.execute("SELECT pg_size_bytes(current_setting('wal_segment_size')) AS size").fetchone()['size']
        report['delete_flush_lsn'] = delete_lsn
        required = required_segments(wal_range['Start-LSN'], end_lsn, wal_range['Timeline'], size)
        checkpoint('wait_archived_wal')
        digests, stats = wait_wal(nodes['cartago'], values, required,
                                 checks['nodes']['cartago']['archiver']['failed_count'], size)
        report['wal'] = {'volume': archive_volume, 'required_segments': digests,
                         'start_lsn': wal_range['Start-LSN'], 'switched_lsn': end_lsn,
                         'segment_size': size, 'archiver': stats}
        wal.run(['docker', 'exec', '-u', 'postgres', nodes['cartago'],
                 '/usr/lib/postgresql/17/bin/pg_waldump', '-p', '/wal-archive',
                 '-t', str(wal_range['Timeline']), '-s', wal_range['Start-LSN'], '-e', target_lsn])
        wait_originals(list(nodes),values,before)
        checkpoint('prepare_isolated_copy')
        with backup.admin('cartago',values) as conn:
            server_settings={name:conn.execute('SELECT current_setting(%s) AS v',(name,)).fetchone()['v']
                for name in ('max_connections','max_worker_processes','max_wal_senders','max_prepared_transactions','max_locks_per_transaction','max_replication_slots')}
        report['recovery_server_settings']=server_settings
        clone = prepare_copy(data, directory / 'pgdata', point, server_settings)
        container = wal.run(['docker', 'run', '-d', '--pull', 'never', '--network', 'none',
                             '--name', runtime.config()['project']+'-pitr-' + token[:12],
                             '--label', 'sig-tec-ops-purpose=pitr-test',
                             '--mount', f'type=bind,source={clone},target=/var/lib/postgresql/data',
                             '--mount', f'type=volume,source={archive_volume},target=/wal-archive,readonly',
                             source['image'], 'postgres'])
        info = json.loads(wal.run(['docker', 'inspect', container]))[0]
        require(info['HostConfig']['NetworkMode'] == 'none' and not info['HostConfig']['PortBindings'],
                'El contenedor no está aislado.')
        require(any(m['Destination'] == '/wal-archive' and not m['RW'] and m['Name'] == archive_volume
                    for m in info['Mounts']), 'El archivo WAL no se montó en solo lectura.')
        report['isolation'] = {'network': 'none', 'published_ports': False, 'archive_read_only': True,
                               'pgdata_copy': str(clone.relative_to(ROOT.parent)), 'image': source['image']}
        checkpoint('wait_named_target_pause')
        paused = wait_recovery(container, paused=True)
        target_lines = [line for line in logs(container).splitlines()
                        if 'recovery stopping at restore point' in line and point in line]
        require(bool(target_lines) and paused['target'] == point, 'Los logs no confirman el punto nombrado.')
        require(lsn_value(target_lsn) <= lsn_value(paused['replay_lsn']) < lsn_value(delete_lsn),
                'La posición reproducida no es anterior a la eliminación.')
        restored = clone_query(container, f"SELECT {projection} FROM cartago.edificios WHERE id={fixture['id']}")
        require(restored == [fixture], 'El edificio no se recuperó con los atributos originales.')
        report['target_reached'] = {'paused': paused, 'log_evidence': target_lines}
        archive_lines = [line for line in logs(container).splitlines()
                         if 'restored log file' in line and 'from archive' in line]
        target_segment = required_segments(target_lsn, end_lsn, wal_range['Timeline'], size)[0]
        require(any(f'"{target_segment}"' in line for line in archive_lines),
                'No se confirmó la lectura desde el archivo WAL del segmento con el punto nombrado.')
        report['target_reached']['archive_log_evidence'] = archive_lines
        checkpoint('finish_recovery')
        clone_query(container, 'SELECT pg_wal_replay_resume()')
        finished = wait_recovery(container, paused=False)
        restored_data = backup.fingerprint(lambda query: clone_query(container, query))
        require(restored_data == expected_copy, 'La copia no coincide con los datos existentes al punto de restauración.')
        timeline = clone_query(container, 'SELECT timeline_id FROM pg_control_checkpoint()')[0]['timeline_id']
        require(timeline > wal_range['Timeline'], 'No se creó el nuevo timeline de la copia.')
        wal.run(['docker', 'exec', container, 'test', '!', '-e', '/var/lib/postgresql/data/recovery.signal'])
        report['recovery_finished'] = {'state': finished, 'timeline': timeline, 'recovery_signal_removed': True,
                                       'restored_fixture': restored[0], 'all_table_hashes_match': True}
        checkpoint('verify_originals_unchanged')
        wal.preflight()
        wait_originals(list(nodes),values,before)
        for node, original in old_archives.items():
            current = archive_hashes(nodes[node])
            require(all(current.get(name) == digest for name, digest in original.items()), 'Cambió un WAL archivado anteriormente.')
        require(backup.checksum(new_backup / 'cartago/physical/base.tar') == item['physical']['tar_sha256'],
                'Cambió el respaldo físico nuevo.')
        backup.verify_physical(new_backup / 'cartago', item['image'])
        for cid, original in before_containers.items():
            require(inventory().get(cid) == original, 'Cambió el estado o montaje de un contenedor original.')
        report['checks'] = {'original_fixture_deleted': True, 'restored_fixture_matches': True,
                            'originals_all_table_hashes_match': True, 'central_unchanged': True,
                            'original_containers_unchanged': True, 'old_archives_unchanged': True,
                            'physical_backup_still_verified': True, 'prepared_transactions': 0}
        report['status'] = 'passed'
        report['finished_at_utc'] = utc()
        success = True
    except Exception:
        report['status'] = 'failed'
        report['failure_policy'] = 'Respaldos, copia y logs conservados. No se reparó ni reinsertó nada en los originales.'
        raise
    finally:
        if container:
            private_logs = logs(container)
            (directory / 'postgres.log').write_text(private_logs, encoding='utf-8')
            (directory / 'postgres.log').chmod(0o600)
            state = json.loads(wal.run(['docker', 'inspect', container]))[0]['State']
            if state['Running'] and not (success and keep_copy):
                wal.run(['docker', 'stop', '--time', '30', container])
            if success and not keep_copy:
                wal.run(['docker', 'rm', container])
                report['temporary_container_removed'] = True
            else:
                report['restored_container' if success else 'diagnostic_container'] = container
        backup.save(directory / 'report.json', report)
        backup.save(REPORT, report)
    print(f'PITR completado: {point}; evidencia: ops/pitr-results.json', flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run',))
    parser.add_argument('--keep-copy',action='store_true')
    args=parser.parse_args()
    try:
        exercise(keep_copy=args.keep_copy)
    except (PITRError, wal.SafetyError, backup.BackupError) as error:
        print('DETENER: ' + str(error), file=sys.stderr)
        return 1
    except (psycopg.Error, OSError, ValueError, KeyError):
        print('DETENER: prueba incompleta; conservar artefactos y revisar logs privados. Diagnóstico omitido.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
