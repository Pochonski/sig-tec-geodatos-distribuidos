#!/usr/bin/env python3
"""Respaldos de sig-tec-ops y restauración lógica en un contenedor aislado."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

import rename
from migrate import containers
from verify import inventory

ROOT = Path(__file__).resolve().parent
BACKUPS = ROOT / 'backups'
NODES = {'central': rename.CENTRAL, 'cartago': rename.CAMPUSES[1]}


class BackupError(Exception):
    pass


def command(args, *, data=None, output=None, source=None):
    proc = subprocess.run(args, input=data, stdin=source, stdout=output or subprocess.PIPE,
                          stderr=subprocess.PIPE)
    if proc.returncode:
        # Herramientas y Docker pueden imprimir datos sensibles en diagnósticos.
        raise BackupError(f'Falló {args[0]} (código {proc.returncode}); diagnóstico omitido.')
    if proc.stderr:
        print(f'{args[0]}: diagnóstico no fatal recibido (sin mostrar su contenido).', flush=True)
    return proc.stdout or b''


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    path.chmod(0o600)


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def admin(node, values):
    password = values.get(f'OPS_{node.upper()}_PASSWORD')
    if not password:
        raise BackupError(f'Falta la contraseña administrativa local de {node}.')
    return psycopg.connect(host='127.0.0.1', port=NODES[node].port, dbname='sig_tec',
                           user='postgres', password=password, row_factory=dict_row,
                           connect_timeout=5, options='-c search_path=pg_catalog')


def source_tool(container, password, tool_args, destination):
    # La contraseña viaja únicamente por stdin; no se escribe en logs ni argv.
    args = ['docker', 'exec', '-i', container, 'sh', '-c',
            'IFS= read -r PGPASSWORD; export PGPASSWORD; exec "$@"', 'sh', *tool_args]
    with destination.open('xb') as output:
        command(args, data=(password + '\n').encode(), output=output)
    destination.chmod(0o600)


def fingerprint(execute):
    """Inventario y hash de todas las filas, incluyendo tablas de extensiones."""
    tables = execute("SELECT n.nspname AS schema, c.relname AS name FROM pg_class c "
                     "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p') "
                     "AND n.nspname NOT IN ('pg_catalog','information_schema') "
                     "AND n.nspname NOT LIKE 'pg_toast%' ORDER BY n.nspname,c.relname")
    result = {'extensions': execute('SELECT extname, extversion FROM pg_extension ORDER BY extname'),
              'tables': {}}
    for table in tables:
        schema, name = table['schema'], table['name']
        identifier = sql.Identifier(schema, name).as_string()
        regclass = sql.Literal(identifier).as_string() + '::regclass'
        data = execute(
            "SELECT count(*) AS count, encode(sha256(convert_to(COALESCE("
            "string_agg(to_jsonb(t)::text, E'\\n' ORDER BY to_jsonb(t)::text COLLATE \"C\"), ''),"
            f"'UTF8')), 'hex') AS sha256 FROM ONLY {identifier} t"
        )[0]
        columns = execute('SELECT attname, format_type(atttypid,atttypmod) AS type, attnotnull '
                          f'FROM pg_attribute WHERE attrelid={regclass} AND attnum>0 '
                          'AND NOT attisdropped ORDER BY attnum')
        constraints = execute('SELECT conname, pg_get_constraintdef(oid) AS definition '
                              f'FROM pg_constraint WHERE conrelid={regclass} ORDER BY conname')
        result['tables'][f'{schema}.{name}'] = {**data, 'columns': columns, 'constraints': constraints}
    return result


def origin_state(nodes, values):
    result = {}
    for node in nodes:
        with admin(node, values) as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            result[node] = {
                'data': fingerprint(lambda query: conn.execute(query).fetchall()),
                'prepared': conn.execute('SELECT gid, owner, database FROM pg_prepared_xacts ORDER BY gid').fetchall(),
            }
    return result


def sources(node_names):
    current = containers()
    result = {}
    for node in node_names:
        details = json.loads(command(['docker', 'inspect', current[node]]))[0]
        result[node] = {'container': current[node], 'image': details['Image']}
    return result


def verify_logical(folder, image):
    with (folder / 'logical.dump').open('rb') as stream:
        listing = command(['docker', 'run', '--rm', '-i', '--pull', 'never', '--network', 'none',
                           '--read-only', '--entrypoint', 'pg_restore', image, '--list'], source=stream)
    (folder / 'logical.list').write_bytes(listing)
    (folder / 'logical.list').chmod(0o600)


def verify_physical(folder, image):
    command(['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--read-only',
             '--mount', f'type=bind,source={folder / "physical/data"},target=/backup,readonly',
             '--entrypoint', '/usr/lib/postgresql/17/bin/pg_verifybackup', image, '/backup'])


def create(node_names, kind):
    values = rename.configuration()
    source = sources(node_names)
    before, before_containers = origin_state(node_names, values), inventory()
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
    directory = BACKUPS / run_id
    directory.mkdir(parents=True, mode=0o700)
    report = {'run_id': run_id, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'status': 'incomplete', 'nodes': {}}
    save(directory / 'manifest.json', report)
    for node in node_names:
        folder = directory / node
        folder.mkdir(mode=0o700)
        info = source[node]
        item = {'image': info['image'], 'database': 'sig_tec'}
        password = values[f'OPS_{node.upper()}_PASSWORD']
        with admin(node, values) as conn:
            if conn.execute("SELECT current_setting('server_version_num')::int AS version").fetchone()['version'] // 10000 != 17:
                raise BackupError('Este procedimiento requiere PostgreSQL 17.')
            item['server_version'] = conn.execute('SHOW server_version').fetchone()['server_version']
            if kind in ('all', 'physical') and conn.execute(
                "SELECT spcname FROM pg_tablespace WHERE spcname NOT IN ('pg_default','pg_global')"
            ).fetchall():
                raise BackupError('Este formato físico no admite tablespaces externos.')
        if kind in ('all', 'logical'):
            print(f'{node}: pg_dump custom con snapshot consistente...', flush=True)
            with admin(node, values) as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                snapshot = conn.execute('SELECT pg_export_snapshot() AS snapshot').fetchone()['snapshot']
                expected = fingerprint(lambda query: conn.execute(query).fetchall())
                source_tool(info['container'], password,
                            ['pg_dump', '-h', '127.0.0.1', '-U', 'postgres', '-d', 'sig_tec',
                             '--no-password', '--format=custom', '--snapshot=' + snapshot], folder / 'logical.dump')
            save(folder / 'expected.json', expected)
            verify_logical(folder, info['image'])
            item['logical'] = {'sha256': checksum(folder / 'logical.dump'), 'verified': True,
                               'expected_sha256': checksum(folder / 'expected.json'),
                               'counts': {name: table['count'] for name, table in expected['tables'].items()}}
            print(f'{node}: pg_restore --list correcto.', flush=True)
        if kind in ('all', 'physical'):
            print(f'{node}: pg_basebackup completo...', flush=True)
            physical = folder / 'physical'
            physical.mkdir(mode=0o700)
            source_tool(info['container'], password,
                        ['pg_basebackup', '-h', '127.0.0.1', '-U', 'postgres', '--pgdata=-',
                         '--format=tar', '--wal-method=fetch', '--checkpoint=fast',
                         '--manifest-checksums=SHA256', '--no-password'], physical / 'base.tar')
            data = physical / 'data'
            data.mkdir(mode=0o700)
            with tarfile.open(physical / 'base.tar') as archive:
                archive.extractall(data, filter='data')
            verify_physical(folder, info['image'])
            item['physical'] = {'tar_sha256': checksum(physical / 'base.tar'), 'verified': True,
                                'manifest_sha256': checksum(data / 'backup_manifest')}
            print(f'{node}: pg_verifybackup correcto, incluidos los segmentos requeridos.', flush=True)
        report['nodes'][node] = item
        save(directory / 'manifest.json', report)
    if origin_state(node_names, values) != before:
        raise BackupError('Los datos de origen cambiaron durante la ejecución; revisar actividad concurrente.')
    if inventory() != before_containers:
        raise BackupError('Cambió el estado o montaje de un contenedor existente.')
    report.update(status='complete', source_data_unchanged=True, source_prepared_unchanged=True,
                  existing_containers_unchanged=True)
    save(directory / 'manifest.json', report)
    save(ROOT / 'backup-results.json', {'directory': str(directory.relative_to(ROOT.parent)), **report})
    print(f'Respaldos completos: {directory.relative_to(ROOT.parent)}', flush=True)


def load(directory):
    directory = directory.resolve()
    if not directory.is_relative_to(BACKUPS.resolve()):
        raise BackupError('La ejecución debe estar dentro de ops/backups/.')
    report = json.loads((directory / 'manifest.json').read_text())
    if report['status'] != 'complete':
        raise BackupError('La ejecución no tiene un manifiesto completo.')
    return directory, report


def verify(directory, node_names=None):
    directory, report = load(directory)
    selected = list(report['nodes']) if node_names is None else node_names
    for node in selected:
        item, folder = report['nodes'][node], directory / node
        if 'logical' in item:
            if (checksum(folder / 'logical.dump') != item['logical']['sha256']
                    or checksum(folder / 'expected.json') != item['logical']['expected_sha256']):
                raise BackupError(f'{node}: checksum lógico incorrecto.')
            verify_logical(folder, item['image'])
        if 'physical' in item:
            if (checksum(folder / 'physical/base.tar') != item['physical']['tar_sha256']
                    or checksum(folder / 'physical/data/backup_manifest') != item['physical']['manifest_sha256']):
                raise BackupError(f'{node}: checksum físico incorrecto.')
            verify_physical(folder, item['image'])
        print(f'{node}: verificaciones correctas.', flush=True)
    return directory, report


def isolated_restore(folder, image):
    """El único destino admitido es un contenedor nuevo, sin red y con PGDATA tmpfs."""
    name = 'sig-tec-ops-restore-' + uuid4().hex[:12]
    container = command([
        'docker', 'run', '-d', '--pull', 'never', '--name', name, '--network', 'none',
        '--label', 'sig-tec-ops-purpose=logical-restore-test',
        '--tmpfs', '/var/lib/postgresql/data:rw,size=512m',
        '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', '-e', 'POSTGRES_DB=restore_seed', image,
    ]).decode().strip()
    try:
        deadline = time.monotonic() + 180
        while True:
            proc = subprocess.run(['docker', 'exec', container, 'pg_isready', '-h', '127.0.0.1',
                                   '-U', 'postgres', '-d', 'restore_seed'], capture_output=True)
            if proc.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise BackupError('La instancia aislada no estuvo lista a tiempo.')
            time.sleep(0.5)
        command(['docker', 'exec', container, 'createdb', '-U', 'postgres', '-T', 'template0', 'sig_tec'])
        with (folder / 'logical.dump').open('rb') as stream:
            command(['docker', 'exec', '-i', container, 'pg_restore', '-U', 'postgres', '-d', 'sig_tec',
                     '--no-owner', '--no-privileges', '--single-transaction', '--exit-on-error'], source=stream)

        def execute(statement):
            query = "SET search_path=pg_catalog; SELECT COALESCE(json_agg(q), '[]'::json) FROM (" + statement + ') q'
            value = command(['docker', 'exec', container, 'psql', '-X', '-qAt', '-U', 'postgres',
                             '-d', 'sig_tec', '-v', 'ON_ERROR_STOP=1', '-c', query])
            return json.loads(value)

        expected = json.loads((folder / 'expected.json').read_text())
        restored = fingerprint(execute)
        if restored != expected:
            raise BackupError('La restauración no coincide con tablas, columnas, restricciones o registros de origen.')
        return {'verified': True, 'network': 'none', 'data': 'tmpfs', 'ports_published': False,
                'counts': {name: table['count'] for name, table in restored['tables'].items()},
                'row_hashes_match': True, 'columns_constraints_extensions_match': True}
    finally:
        # Solo el ID recién creado; no se usa prune ni se elimina ningún volumen.
        command(['docker', 'rm', '-f', container])


def restore_test(directory):
    directory, report = verify(directory)
    node_names = list(report['nodes'])
    values = rename.configuration()
    before, before_containers = origin_state(node_names, values), inventory()
    results = {}
    for node, item in report['nodes'].items():
        if 'logical' not in item:
            raise BackupError(f'{node}: no hay respaldo lógico para restaurar.')
        print(f'{node}: restaurando en instancia nueva sin red...', flush=True)
        results[node] = isolated_restore(directory / node, item['image'])
        print(f'{node}: tablas, conteos y hashes de registros coinciden.', flush=True)
    if origin_state(node_names, values) != before or inventory() != before_containers:
        raise BackupError('Cambió el origen durante la prueba; revisar actividad concurrente.')
    report['logical_restore_test'] = {'executed_at_utc': datetime.now(timezone.utc).isoformat(),
                                      'nodes': results, 'source_data_prepared_containers_unchanged': True}
    save(directory / 'manifest.json', report)
    save(ROOT / 'backup-results.json', {'directory': str(directory.relative_to(ROOT.parent)), **report})
    print('Restauraciones verificadas; instancias temporales eliminadas y orígenes intactos.', flush=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    new = sub.add_parser('create')
    new.add_argument('--node', choices=('all', 'central', 'cartago'), default='all')
    new.add_argument('--kind', choices=('all', 'logical', 'physical'), default='all')
    for action in ('verify', 'restore-test'):
        sub.add_parser(action).add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'create':
            create(list(NODES) if args.node == 'all' else [args.node], args.kind)
        elif args.action == 'verify':
            verify(args.directory)
        else:
            restore_test(args.directory)
    except (BackupError, rename.OperationError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (psycopg.Error, OSError, ValueError, KeyError, tarfile.TarError):
        print('Operación incompleta; se conservaron los respaldos y no se modificaron destinos existentes. '
              'Revisar configuración local, espacio, herramientas y manifiesto de la ejecución.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
