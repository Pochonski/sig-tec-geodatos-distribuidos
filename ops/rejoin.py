#!/usr/bin/env python3
"""Inspección y simulación de reincorporación. No existe modo de ejecución de cambios."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

import backup
import rename
from verify import inventory

ROOT = Path(__file__).resolve().parent
REFERENCE = 'f3e1f91e1e61e2f293fac4ba50de209cc0af65ea'
REMOTE_REF = 'origin/joseph/cinco-campus-ocho-capas'
CAMPUSES = {1: 'cartago', 2: 'san_jose', 3: 'san_carlos', 4: 'alajuela', 5: 'limon'}
LAYERS = ('edificios', 'carreteras', 'aceras', 'parqueos', 'zonas_verdes',
          'puntos_interes', 'iluminacion', 'accesibilidad')
PUBLICATIONS = {'cartago': 'pub_cartago_edificios', 'san_jose': 'pub_san_jose_capas',
                'san_carlos': 'pub_san_carlos_edificios', 'alajuela': 'pub_alajuela_capas',
                'limon': 'pub_limon_capas'}
GEOMETRIES = {'edificios': 'Polygon', 'carreteras': 'LineString', 'aceras': 'LineString',
              'parqueos': 'Polygon', 'zonas_verdes': 'Polygon', 'puntos_interes': 'Point',
              'iluminacion': 'Point', 'accesibilidad': 'LineString'}
READ_OPTIONS = ('-c default_transaction_read_only=on -c statement_timeout=10000 '
                '-c lock_timeout=2000 -c search_path=pg_catalog')


class CheckError(Exception):
    pass


def command(args):
    result = subprocess.run(args, text=True, capture_output=True, encoding='utf-8')
    if result.returncode:
        raise CheckError('Herramienta no disponible o comando de consulta fallido; diagnóstico omitido.')
    return result.stdout.strip()


def reference_contract():
    commit = command(['git', 'rev-parse', '--verify', REMOTE_REF + '^{commit}'])
    if commit != REFERENCE:
        raise CheckError('La referencia de Joseph cambió; revisar el modelo antes de actualizar el contrato fijado.')
    paths = ('compose.yaml', 'db/schema.sql', 'db/seed.sql', 'db/publications.sql',
             'db/subscriptions.sql', 'db/bootstrap.sh', 'db/slot.sql')
    source = {path: subprocess.check_output(['git', 'show', f'{commit}:{path}']) for path in paths}
    return {'branch': REMOTE_REF, 'commit': commit,
            'source_sha256': {path: hashlib.sha256(content).hexdigest() for path, content in source.items()},
            'nodes': ['central', *CAMPUSES.values()],
            'host_ports': {node: 55430 + i for i, node in enumerate(['central', *CAMPUSES.values()])},
            'layers': list(LAYERS), 'publications': PUBLICATIONS,
            'central_subscriptions': 5, 'tables_per_central_subscription': 8,
            'campus_subscriptions': 1, 'tables_per_campus_subscription': 33,
            'id_sequence': '<campus>.sigtec_ids', 'id_increment': 5,
            'edificios_columns': ['id', 'campus_id', 'nombre', 'codigo', 'area', 'pisos', 'geom'],
            'edificios_geometry': 'geometry(Polygon,8908) NOT NULL',
            'ops_migrations_in_reference': False, 'archive_in_reference': False}


def next_candidate(campus_id, observed_max, sequence, issued_high_water):
    """Cálculo puro, no llama nextval/setval ni supone que MAX(id) es historia completa."""
    if issued_high_water is None:
        return {'candidate': None, 'blocker': 'Falta el máximo histórico aprobado de IDs emitidos, incluidos borrados.'}
    if not sequence or sequence['seqincrement'] != 5 or sequence['seqcycle']:
        return {'candidate': None, 'blocker': 'Secuencia ausente, incremento distinto de 5 o CYCLE habilitado.'}
    if sequence['seqstart'] % 5 != campus_id % 5:
        return {'candidate': None, 'blocker': 'La secuencia no corresponde a la clase del campus.'}
    if issued_high_water < 0 or issued_high_water < (observed_max or 0):
        return {'candidate': None, 'blocker': 'El máximo histórico declarado contradice IDs observados.'}
    # last_value puede reservar IDs en caché: saltar por encima es conservador.
    bound = max(issued_high_water, observed_max or 0, sequence['last_value'])
    candidate = bound + 1 + ((campus_id - (bound + 1)) % 5)
    if candidate > sequence['seqmax'] or candidate >= 2**63:
        return {'candidate': None, 'blocker': 'No hay espacio bigint sin reciclar IDs.'}
    return {'candidate': candidate, 'upper_bound': bound, 'written': False,
            'manual_semantics': 'Tras fencing y validación: fijar este valor con is_called=false; no retroceder la secuencia.'}


class TCPReader:
    def __init__(self, endpoint, values):
        if set(endpoint) != {'host','port','user','password_env'}:
            raise CheckError('El endpoint solo admite host, port, user y password_env; no contraseñas literales.')
        if endpoint['host'] not in ('127.0.0.1', 'localhost', '::1'):
            raise CheckError('Esta versión solo inspecciona endpoints loopback explícitos.')
        key = endpoint['password_env']
        if not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            raise CheckError('password_env debe ser un nombre de variable de configuración.')
        password = os.environ.get(key) or values.get(key)
        if not password:
            raise CheckError('Falta la variable local ' + key + '; no se intentó otra contraseña.')
        self.conn = psycopg.connect(host=endpoint['host'], port=endpoint['port'],
                                    user=endpoint['user'], password=password, dbname='sig_tec',
                                    connect_timeout=3, options=READ_OPTIONS, row_factory=dict_row)
        self.conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')

    def query(self, statement):
        return self.conn.execute(statement).fetchall()

    def close(self):
        try:
            if not self.conn.closed: self.conn.rollback()
        except psycopg.Error:
            pass
        finally:
            self.conn.close()


class RestoredReader:
    def __init__(self, container):
        details = json.loads(command(['docker', 'inspect', container]))[0]
        if (details['Config'].get('Labels', {}).get('sig-tec-ops-purpose') != 'pitr-test'
                or details['HostConfig']['NetworkMode'] != 'none' or details['HostConfig']['PortBindings']):
            raise CheckError('La copia debe llevar label sig-tec-ops-purpose=pitr-test, sin red ni puertos.')
        if not details['State']['Running']:
            raise CheckError('La copia aislada está detenida; el inspector nunca la arranca.')
        self.container = details['Id']

    def query(self, statement):
        wrapped = ("BEGIN READ ONLY; SET LOCAL search_path=pg_catalog; "
                   "SELECT COALESCE(json_agg(q),'[]'::json) FROM (" + statement + ') q; ROLLBACK;')
        return json.loads(command(['docker', 'exec', '-e', 'PGOPTIONS=' + READ_OPTIONS,
                                   self.container, 'psql', '-X', '-qAt', '-U', 'postgres', '-d', 'sig_tec',
                                   '-v', 'ON_ERROR_STOP=1', '-c', wrapped]))

    def close(self):
        pass


def collect(reader, node):
    q = reader.query
    result = {'reachable': True, 'settings': q("SELECT current_setting('transaction_read_only') AS read_only, "
              "current_setting('wal_level') AS wal_level, current_setting('max_prepared_transactions') AS max_prepared, "
              "current_setting('archive_mode') AS archive_mode, pg_is_in_recovery() AS in_recovery")[0]}
    if result['settings']['read_only'] != 'on':
        raise CheckError('La sesión no es READ ONLY; detener inspección.')
    result['prepared_count'] = q('SELECT count(*) AS n FROM pg_prepared_xacts')[0]['n']
    # Nunca seleccionar subconninfo: contiene la contraseña del replicador.
    result['subscriptions'] = q('SELECT subname, subenabled, subslotname, subpublications, suborigin, subtwophasestate '
                                'FROM pg_subscription WHERE subdbid=(SELECT oid FROM pg_database '
                                'WHERE datname=current_database()) ORDER BY subname')
    result['subscription_relations'] = q('SELECT s.subname, n.nspname AS schema, c.relname AS name, r.srsubstate AS state '
        'FROM pg_subscription_rel r JOIN pg_subscription s ON s.oid=r.srsubid '
        'JOIN pg_class c ON c.oid=r.srrelid JOIN pg_namespace n ON n.oid=c.relnamespace ORDER BY 1,2,3')
    result['subscription_workers'] = q('SELECT subname, pid, relid, received_lsn::text, latest_end_lsn::text '
                                        'FROM pg_stat_subscription ORDER BY subname,relid')
    result['slots'] = q('SELECT slot_name, plugin, slot_type, database, active, restart_lsn::text, '
                       'confirmed_flush_lsn::text, wal_status, invalidation_reason '
                       'FROM pg_replication_slots ORDER BY slot_name')
    result['publication_tables'] = q('SELECT pubname, schemaname, tablename FROM pg_publication_tables ORDER BY 1,2,3')
    result['origins'] = q('SELECT external_id, remote_lsn::text, local_lsn::text FROM pg_replication_origin_status')
    result['roles'] = q("SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                        "FROM pg_roles WHERE rolname IN ('sig_tec_ops_cli','sigtec_repl') ORDER BY rolname")
    # Solo tablas del contrato; no se publica ningún nombre de edificio ni geometría.
    catalog = backup.fingerprint(q)
    result['tables'] = {}
    for schema in CAMPUSES.values():
        for layer in LAYERS:
            table = schema + '.' + layer
            if table not in catalog['tables']:
                continue
            detail = catalog['tables'][table]
            detail.update(q(sql.SQL('SELECT max(id) AS max_id, count(*) FILTER '
                '(WHERE campus_id <> {} OR mod(id,5) <> {}) AS invalid_ids FROM {}').format(
                    sql.Literal(next(i for i, n in CAMPUSES.items() if n == schema)),
                    sql.Literal(next(i for i, n in CAMPUSES.items() if n == schema) % 5),
                    sql.Identifier(schema, layer)).as_string())[0])
            result['tables'][table] = detail
    # Una secuencia se comparte entre las ocho capas: duplicados entre tablas
    # de un mismo esquema también violan el contrato global de IDs.
    result['duplicate_ids'] = {}
    for schema in CAMPUSES.values():
        present = [layer for layer in LAYERS if schema + '.' + layer in result['tables']]
        if present:
            union = ' UNION ALL '.join(sql.SQL('SELECT id FROM {}').format(
                sql.Identifier(schema, layer)).as_string() for layer in present)
            result['duplicate_ids'][schema] = q('SELECT count(*) AS n FROM '
                '(SELECT id FROM (' + union + ') ids GROUP BY id HAVING count(*)>1) duplicates')[0]['n']
    result['sequence'] = None
    if node in CAMPUSES.values():
        sequence_name = sql.Literal(node + '.sigtec_ids').as_string()
        sequence = q('SELECT seqstart,seqincrement,seqmin,seqmax,seqcache,seqcycle '
                     'FROM pg_sequence WHERE seqrelid=to_regclass(' + sequence_name + ')')
        if sequence:
            sequence[0].update(q(sql.SQL('SELECT last_value,is_called FROM {}').format(
                sql.Identifier(node, 'sigtec_ids')).as_string())[0])
            result['sequence'] = sequence[0]
    result['cli_privileges'] = None
    if any(role['rolname'] == 'sig_tec_ops_cli' for role in result['roles']):
        result['cli_privileges'] = q("SELECT has_database_privilege('sig_tec_ops_cli',current_database(),'CONNECT') AS connect") [0]
        if node in CAMPUSES.values() and node + '.edificios' in result['tables']:
            table = sql.Literal(node + '.edificios').as_string()
            result['cli_privileges'].update(q("SELECT has_column_privilege('sig_tec_ops_cli'," + table + ", 'nombre','UPDATE') AS update_nombre, "
                "has_column_privilege('sig_tec_ops_cli'," + table + ", 'id','UPDATE') AS update_id, "
                "has_column_privilege('sig_tec_ops_cli'," + table + ", 'campus_id','UPDATE') AS update_campus, "
                "has_table_privilege('sig_tec_ops_cli'," + table + ", 'INSERT') AS insert_table, "
                "has_table_privilege('sig_tec_ops_cli'," + table + ", 'DELETE') AS delete_table")[0])
    result['ops_counts'] = {name: d['count'] for name, d in catalog['tables'].items() if name.startswith('ops.')}
    # Solo se usa en memoria para comparar UUID y carga; se elimina al serializar.
    result['_ops'] = {}
    for table in ('requests', 'decisions', 'audit', 'applied_operations'):
        if 'ops.' + table in catalog['tables']:
            columns = 'operation_id,decision' if table == 'decisions' else 'operation_id,campus_id,building_id,new_name'
            result['_ops'][table] = q(f'SELECT {columns} FROM ops.{table}')
    return result


def assess_node(node, state):
    blockers = []
    if not state.get('reachable'):
        return [node + ': ' + state['dependency']]
    if state['prepared_count']:
        blockers.append(node + ': transacciones preparadas requieren revisión manual')
    if state['settings']['wal_level'] != 'logical':
        blockers.append(node + ': wal_level no es logical')
    if int(state['settings']['max_prepared']) < 10:
        blockers.append(node + ': max_prepared_transactions insuficiente')
    if node != 'central' and state['sequence'] is None:
        blockers.append(node + ': falta la secuencia compartida ' + node + '.sigtec_ids')
    missing = [schema + '.' + layer for schema in CAMPUSES.values() for layer in LAYERS
               if schema + '.' + layer not in state['tables']]
    if missing:
        blockers.append(f'{node}: faltan {len(missing)} tablas del modelo geográfico de 40 tablas')
    for table, details in state['tables'].items():
        geometry = next((c for c in details['columns'] if c['attname'] == 'geom'), None)
        if not geometry or not geometry['attnotnull']:
            blockers.append(node + ': ' + table + ' carece de geom NOT NULL')
        elif geometry['type'].replace(' ','').lower() != f"geometry({GEOMETRIES[table.split('.')[1]]},8908)".lower():
            blockers.append(node + ': tipo/SRID inesperado en ' + table)
        if details['invalid_ids']:
            blockers.append(node + ': hay IDs/campus fuera de la clase esperada en ' + table)
    if any(state.get('duplicate_ids', {}).values()):
        blockers.append(node + ': IDs duplicados entre capas de un campus')
    expected_pubs = {pub: schema for schema,pub in PUBLICATIONS.items() if node == 'central' or node == schema}
    expected_pub_tables = {(pub,schema,layer) for pub,schema in expected_pubs.items() for layer in LAYERS}
    if node == 'central': expected_pub_tables.add(('pub_layer_styles','public','layer_styles'))
    if {(row['pubname'],row['schemaname'],row['tablename']) for row in state['publication_tables']} != expected_pub_tables:
        blockers.append(node + ': publicaciones/tablas distintas al contrato')
    expected_subs = ({f'sub_central_{campus}': (f'slot_central_{campus}', [PUBLICATIONS[campus]], 8)
                      for campus in CAMPUSES.values()} if node == 'central' else {
                          f'sub_{node}_central': (f'slot_{node}_central',
                          [pub for campus, pub in PUBLICATIONS.items() if campus != node] + ['pub_layer_styles'], 33)})
    actual = {sub['subname']: sub for sub in state['subscriptions']}
    if set(actual) != set(expected_subs):
        blockers.append(node + ': inventario de suscripciones distinto al contrato')
    for name, (slot, pubs, total) in expected_subs.items():
        sub = actual.get(name)
        if sub and (not sub['subenabled'] or sub['subslotname'] != slot
                    or sorted(sub['subpublications']) != sorted(pubs) or sub['suborigin'] != 'any'):
            blockers.append(node + ': configuración inesperada en ' + name)
        relations = [r for r in state['subscription_relations'] if r['subname'] == name]
        if len(relations) != total or any(r['state'] != 'r' for r in relations):
            blockers.append(node + ': sincronización inicial no lista en ' + name)
        expected_relations = {(schema,layer) for schema,pub in PUBLICATIONS.items() if pub in pubs for layer in LAYERS}
        if 'pub_layer_styles' in pubs: expected_relations.add(('public','layer_styles'))
        if {(r['schema'],r['name']) for r in relations} != expected_relations:
            blockers.append(node + ': lista de tablas incorrecta en ' + name)
    expected_slots = {f'slot_{campus}_central' for campus in CAMPUSES.values()} if node == 'central' else {f'slot_central_{node}'}
    actual_slots = {slot['slot_name']: slot for slot in state['slots']}
    if set(actual_slots) != expected_slots:
        blockers.append(node + ': inventario de slots distinto al contrato')
    if any(slot['plugin'] != 'pgoutput' or slot['invalidation_reason'] or slot['wal_status'] == 'lost'
           for slot in state['slots']):
        blockers.append(node + ': hay slots inválidos o con plugin inesperado')
    expected_ops = ('ops.requests', 'ops.decisions', 'ops.audit') if node == 'central' else ('ops.applied_operations',)
    if any(table not in state['ops_counts'] for table in expected_ops):
        blockers.append(node + ': faltan migraciones ops de integración')
    if state['cli_privileges'] is None:
        blockers.append(node + ': falta rol sig_tec_ops_cli')
    elif not state['cli_privileges'].get('connect'):
        blockers.append(node + ': el rol CLI no puede conectar a sig_tec')
    elif node != 'central' and (not state['cli_privileges'].get('update_nombre')
          or any(state['cli_privileges'].get(key) for key in ('update_id','update_campus','insert_table','delete_table'))):
        blockers.append(node + ': revisar permisos mínimos de CLI')
    if any(role['rolname']=='sig_tec_ops_cli' and any(role[key] for key in
           ('rolsuper','rolcreatedb','rolcreaterole','rolreplication','rolbypassrls')) for role in state['roles']):
        blockers.append(node + ': rol CLI con privilegios administrativos inesperados')
    return blockers


def operation_consistency(states):
    central = states.get('central', {}).get('_ops', {})
    if any(table not in central for table in ('requests', 'decisions', 'audit')):
        return {'checked': False, 'blocker': 'No se dispone de solicitudes, decisiones y auditoría centrales.'}
    requests = {str(row['operation_id']): row for row in central['requests']}
    decisions = {str(row['operation_id']): row['decision'] for row in central['decisions']}
    audits = {str(row['operation_id']): row for row in central['audit']}
    markers = {}
    missing_campuses = []
    needed = {row['campus_id'] for row in requests.values()}
    duplicated_markers = 0
    for campus,name in CAMPUSES.items():
        rows = states.get(name, {}).get('_ops', {}).get('applied_operations')
        if rows is None and campus in needed:
            missing_campuses.append(campus)
        for row in rows or []:
            key = str(row['operation_id'])
            duplicated_markers += key in markers or row['campus_id'] != campus
            markers[key] = row
    def payload(row):
        return tuple(row[key] for key in ('campus_id','building_id','new_name')) if row else None
    pending = 0
    for key, request in requests.items():
        choice = decisions.get(key)
        if choice == 'COMMIT':
            pending += payload(audits.get(key)) != payload(request) or payload(markers.get(key)) != payload(request)
        elif choice == 'ABORT':
            pending += key in audits or key in markers
        else:
            pending += 1
    orphans = (set(decisions) | set(audits) | set(markers)) - set(requests)
    return {'checked': not missing_campuses, 'requests': len(requests), 'pending_or_inconsistent': pending,
            'orphan_uuids': len(orphans), 'duplicate_or_wrong_campus_markers': duplicated_markers,
            'missing_campus_evidence': missing_campuses,
            'note': 'Evidencia actual; no prueba por sí sola el estado anterior/posterior a PITR.'}


def dry_run(states, campus_id=1, issued_high_water=None, restored=None):
    campus = CAMPUSES[campus_id]
    blockers = []
    for node in ('central', *CAMPUSES.values()):
        blockers.extend(assess_node(node, states.get(node, {'dependency': 'nodo no configurado'})))
    consistency = operation_consistency(states)
    if (not consistency['checked'] or consistency['pending_or_inconsistent'] or consistency['orphan_uuids']
            or consistency['duplicate_or_wrong_campus_markers']):
        blockers.append('Reconciliar evidencia 2PC antes de cualquier cambio')
    sequence = (restored or states.get(campus, {})).get('sequence')
    max_id = max((d['max_id'] or 0 for state in states.values()
                  for table, d in state.get('tables', {}).items() if table.startswith(campus + '.')), default=0)
    sequence_plan = next_candidate(campus_id, max_id, sequence, issued_high_water)
    if sequence_plan.get('blocker'):
        blockers.append(sequence_plan['blocker'])
    restored_consistency = None
    if restored is None:
        blockers.append('Falta inspección de la copia restaurada, aislada y activa solo para revisión')
    else:
        restored_consistency = operation_consistency({**states, campus: restored})
        if (not restored_consistency['checked'] or restored_consistency['pending_or_inconsistent']
                or restored_consistency['orphan_uuids'] or restored_consistency['duplicate_or_wrong_campus_markers']):
            blockers.append('La copia restaurada no concuerda con las decisiones/marcadores actuales del central')
        if any(sub['subenabled'] for sub in restored['subscriptions']):
            blockers.append('La copia conserva suscripciones habilitadas: no conectarla a la red')
        if restored['prepared_count']:
            blockers.append('La copia contiene GID preparados que requieren decisiones del central actual')
    differences = []
    for schema in CAMPUSES.values():
        owner = states.get(schema, {}).get('tables', {})
        for layer in LAYERS:
            table = schema + '.' + layer
            if table not in owner:
                continue
            for node, state in states.items():
                remote = state.get('tables', {}).get(table)
                if remote and remote['sha256'] != owner[table]['sha256']:
                    differences.append({'table': table, 'owner': schema, 'replica': node})
    if differences:
        blockers.append('Hay copias divergentes; los hashes no determinan cuál conserva cambios autorizados')
    return {'mode': 'dry-run', 'database_writes': False, 'execution_supported': False,
            'ready_for_real_rejoin': False, 'campus': campus, 'blockers': blockers,
            'mandatory_manual_gates': ['Fencing verificado del propietario anterior; inaccesibilidad TCP no basta',
                'Reconciliación aprobada de cambios desde PITR en las ocho capas, incluidos borrados',
                'Decisiones/marcadores 2PC reconciliados sin inventar efectos',
                'Máximo histórico de IDs y ajuste monotónico validados con escritores detenidos',
                'Plan explícito de tablas, slots y suscripciones afectadas; aprobación antes de vaciar/copiar'],
            'two_phase': consistency, 'restored_two_phase': restored_consistency,
            'sequence_proposal': sequence_plan, 'table_mismatches': differences,
            'topology': {'upstream': {'subscriber': 'central', 'subscription': f'sub_central_{campus}',
                                     'publisher': campus, 'slot': f'slot_central_{campus}', 'tables': 8},
                         'incoming_remote_copies': {'subscriber': campus, 'subscription': f'sub_{campus}_central',
                                                    'publisher': 'central', 'slot': f'slot_{campus}_central', 'tables': 33},
                         'other_campuses': [name for name in CAMPUSES.values() if name != campus]}}


def inspect(profile, config_path, env_file, campus_id, high_water, restored_container):
    before = inventory()
    if env_file:
        values = {}
        for line in env_file.read_text(encoding='utf-8').splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                key, value = line.split('=',1)
                values[key.strip()] = value.strip().strip('\"\'')
    else:
        values = rename.configuration()
    if config_path:
        endpoints = json.loads(config_path.read_text(encoding='utf-8'))['nodes']
    elif profile == 'ops':
        endpoints = {name: {'host': '127.0.0.1', 'port': port, 'user': 'postgres',
                           'password_env': f'OPS_{name.upper()}_PASSWORD'}
                     for name, port in (('central',57430),('cartago',57431))}
    else:
        endpoints = {name: {'host':'127.0.0.1','port':55430+i,'user':'postgres','password_env':'SIGTEC_ADMIN_PASSWORD'}
                     for i,name in enumerate(('central',*CAMPUSES.values()))}
    if set(endpoints) - {'central', *CAMPUSES.values()}:
        raise CheckError('Inventario contiene nodos ajenos al contrato.')
    states = {}
    for node, endpoint in endpoints.items():
        reader = None
        try:
            reader = TCPReader(endpoint, values)
            states[node] = collect(reader, node)
        except CheckError as error:
            states[node] = {'reachable': False, 'dependency': str(error)}
        except psycopg.Error as error:
            states[node] = {'reachable': False, 'dependency': 'Acceso SQL requerido (' + (error.sqlstate or 'conexión') + '); sin mostrar DSN.'}
        finally:
            if reader: reader.close()
    restored = None
    if restored_container:
        reader = RestoredReader(restored_container)
        try:
            restored = collect(reader, CAMPUSES[campus_id])
        finally:
            reader.close()
    report = {'executed_at_utc': datetime.now(timezone.utc).isoformat(), 'reference': reference_contract(),
              'read_only': True, 'profile': profile if not config_path else 'explicit-inventory',
              'plan': dry_run(states, campus_id, high_water, restored)}
    for state in states.values(): state.pop('_ops',None)
    if restored: restored.pop('_ops',None)
    report['nodes'] = states
    report['restored_node'] = restored
    if inventory() != before:
        raise CheckError('Cambió el inventario Docker durante la inspección; no asumir exclusividad.')
    report['existing_containers_unchanged'] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('compare','dry-run'))
    parser.add_argument('--profile', choices=('ops','integration'), default='ops')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--campus-id', type=int, choices=CAMPUSES, default=1)
    parser.add_argument('--issued-high-water', type=int)
    parser.add_argument('--restored-container')
    parser.add_argument('--output', type=Path, default=ROOT/'rejoin-results.json')
    args = parser.parse_args()
    try:
        if (not args.output.resolve().is_relative_to(ROOT) or args.output.suffix != '.json'
                or args.output.is_symlink()):
            raise CheckError('Guardar evidencia solo como archivo JSON normal dentro de ops/.')
        report = reference_contract() if args.action == 'compare' else inspect(
            args.profile,args.config,args.env_file,args.campus_id,args.issued_high_water,args.restored_container)
        backup.save(args.output, report)
        print('Informe de solo lectura: ' + str(args.output))
        if args.action == 'dry-run':
            print('Plan bloqueado para ejecución real; no se ejecutó ninguna acción de reincorporación.')
            for blocker in report['plan']['blockers']: print('- ' + blocker)
    except (CheckError, OSError, ValueError, KeyError, psycopg.Error) as error:
        print('Inspección incompleta; revisar dependencias e inventario. No se aplicaron cambios.')
        if isinstance(error, CheckError): print(str(error))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
