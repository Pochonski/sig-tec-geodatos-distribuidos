"""Ensayo de sustitución real limitado al laboratorio; conserva el nodo anterior y sus datos."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

import backup
import integration_checks as checks
import lab
from migrate import containers
import pitr
import recover
import rejoin
import rename
import runtime
from verify import inventory

LAYERS=rejoin.LAYERS


def clone_sql(container, statement):
    proc=subprocess.run(['docker','exec','-i',container,'env','PGCLIENTENCODING=UTF8',
                          'psql','-X','-q','-U','postgres','-d','sig_tec','-v','ON_ERROR_STOP=1'],
                         input=statement.encode('utf-8'),capture_output=True)
    if proc.returncode:
        (lab.LAB/'clone-last-error.log').write_bytes(proc.stderr)
        raise RuntimeError('Falló SQL en la copia; revisar diagnóstico privado sin publicar sentencias.')


def export_table(conn, table, path):
    with conn.cursor().copy(sql.SQL('COPY {} TO STDOUT (FORMAT BINARY)').format(sql.Identifier(*table.split('.')))) as stream:
        with path.open('xb') as output:
            for block in stream: output.write(block)


def reconcile(container, table, path, permitted_deletions):
    table_id=sql.Identifier(*table.split('.')).as_string()
    columns=pitr.clone_query(container,'SELECT attname FROM pg_attribute WHERE attrelid='+sql.Literal(table).as_string()+
                              '::regclass AND attnum>0 AND NOT attisdropped ORDER BY attnum')
    names=[column['attname'] for column in columns]
    key='operation_id' if table=='ops.applied_operations' else 'id'
    key_id=sql.Identifier(key).as_string()
    assignments=','.join(sql.SQL('{}=EXCLUDED.{}').format(sql.Identifier(name),sql.Identifier(name)).as_string()
                         for name in names if name!=key)
    remote='/tmp/rejoin-'+uuid4().hex+'.bin'
    lab.run(['docker','cp',str(path),container+':'+remote])
    lab.run(['docker','exec',container,'chown','postgres:postgres',remote])
    allowed=','.join(str(int(value)) for value in permitted_deletions) if key=='id' and permitted_deletions else 'NULL'
    # Validar todos los borrados antes de tocar la tabla destino. Solo se autoriza
    # la fila ficticia que esta misma ejecución eliminó para probar PITR.
    statement=f'''BEGIN;
CREATE TEMP TABLE rejoin_stage (LIKE {table_id}) ON COMMIT DROP;
COPY rejoin_stage FROM '{remote}' WITH (FORMAT BINARY);
DO $$ BEGIN
IF EXISTS (SELECT FROM {table_id} t WHERE NOT EXISTS (SELECT FROM rejoin_stage s WHERE s.{key_id}=t.{key_id})
           AND (t.{key_id} NOT IN ({allowed}) OR {allowed=='NULL'})) THEN
    RAISE EXCEPTION 'Borrado no autorizado en la copia';
END IF;
END $$;
INSERT INTO {table_id} SELECT * FROM rejoin_stage WHERE true ON CONFLICT ({key_id}) DO UPDATE SET {assignments};
'''
    if key=='id' and permitted_deletions:
        statement+=f'DELETE FROM {table_id} t WHERE t.{key_id} IN ({allowed}) AND NOT EXISTS (SELECT FROM rejoin_stage s WHERE s.{key_id}=t.{key_id});\n'
    statement+='COMMIT;'
    clone_sql(container,statement)


def create_subscription(conn, name, host, publications, slot, values):
    connection=make_conninfo(host=host,port=5432,dbname='sig_tec',user='sigtec_repl',password=values['SIGTEC_REPLICATION_PASSWORD'])
    conn.execute(sql.SQL('CREATE SUBSCRIPTION {} CONNECTION {} PUBLICATION {} '
                        "WITH (create_slot=false,slot_name={},copy_data=false,origin='any')").format(
        sql.Identifier(name),sql.Literal(connection),sql.SQL(',').join(map(sql.Identifier,publications)),sql.Literal(slot)))


def run():
    checks.require_lab()
    existing=containers()
    for node,cid in existing.items():
        details=json.loads(lab.run(['docker','inspect',cid]))[0]
        assert details['Config']['Labels']['com.docker.compose.project']==lab.PROJECT
        with backup.admin(node,rename.configuration()) as conn:
            assert not conn.execute('SELECT gid FROM pg_prepared_xacts').fetchall()
    assert not lab.run(['docker','ps','-aq','--filter','name=^sig-tec-rejoin-lab-cartago-recovered$']).strip()
    checks.wait_for(checks.all_geography_converged,'El laboratorio no converge antes del ensayo')
    outsider_ids={json.loads(lab.run(['docker','inspect',cid]))[0]['Id'] for cid in existing.values()}
    outsiders={key:value for key,value in inventory().items() if key not in outsider_ids}
    values=rename.configuration()
    report={'started_at_utc':datetime.now(timezone.utc).isoformat(),'project':lab.PROJECT,
            'status':'running','scope':'Solo laboratorio, sin reincorporación de producción'}
    out=runtime.ROOT/'rejoin-execution-results.json'
    token=uuid4().hex
    journal=lab.LAB/'rejoin-execution'/token
    journal.mkdir(parents=True,mode=0o700)
    def phase(name):
        report['phase']=name
        backup.save(out,report)
        print('Reincorporación: '+name,flush=True)
    try:
        phase('pitr_real_model')
        pit=pitr.exercise(keep_copy=True)
        clone=pit['restored_container']
        clone_data=Path(pit['isolation']['pgdata_copy']).resolve()
        report['pitr']={'point':pit['restore_point'],'fixture_id':pit['fixture']['id'],
                        'timeline':pit['recovery_finished']['timeline']}
        clone_sql(clone,'ALTER SUBSCRIPTION sub_cartago_central DISABLE;')
        assert all(not r['subenabled'] for r in pitr.clone_query(clone,'SELECT subenabled FROM pg_subscription'))
        phase('controlled_post_pitr_changes')
        own_id=checks.fixture('cartago','Cambio posterior a PITR')
        operation=uuid4()
        result=rename.rename(operation,1,own_id,'Reconciliación José Ñandú 🏢',values)
        assert result['status']=='completed'
        incoming_id=checks.fixture('san_jose','Cambio entrante posterior a PITR')
        checks.wait_for(checks.all_geography_converged,'No convergen cambios posteriores')
        # Operación realmente preparada, abortada antes de congelar al propietario.
        interrupted=uuid4()
        proc=subprocess.run([sys.executable,'-B',str(runtime.ROOT/'fault_worker.py'),'crash',str(interrupted),str(own_id),
                             'No debe aplicarse','after_both_prepare'],capture_output=True)
        assert proc.returncode==86
        aborted=recover.recover(interrupted,values)
        assert aborted['status']=='aborted'
        report['two_phase']={'post_pitr_commit':str(operation),'recovered_abort':str(interrupted),
                             'unknown_prepared_resolved':False}
        with backup.admin('central',values) as conn:
            expected=conn.execute('SELECT campus_id,building_id,new_name FROM ops.requests WHERE operation_id=%s',(operation,)).fetchone()
            audit=conn.execute('SELECT campus_id,building_id,new_name FROM ops.audit WHERE operation_id=%s',(operation,)).fetchone()
            assert expected==audit
        phase('freeze_export_and_plan')
        checks.wait_for(checks.all_geography_converged,'No convergen los datos antes del corte')
        cut=backup.origin_state(list(backup.NODES),values)
        tables=[('cartago',f'cartago.{layer}') for layer in LAYERS]+[('cartago','ops.applied_operations')]
        tables += [('central',f'{campus}.{layer}') for campus in runtime.CAMPUSES.values() if campus!='cartago' for layer in LAYERS]
        tables += [('central','public.layer_styles')]
        files={}
        for donor in ('cartago','central'):
            with backup.admin(donor,values) as conn:
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                for source,table in tables:
                    if source==donor:
                        path=journal/(table+'.bin')
                        export_table(conn,table,path)
                        files[table]=path
        with backup.admin('cartago',values) as conn:
            high=conn.execute('SELECT last_value FROM cartago.sigtec_ids').fetchone()['last_value']
            meta=conn.execute("SELECT seqstart,seqincrement,seqcycle,seqmax FROM pg_sequence WHERE seqrelid='cartago.sigtec_ids'::regclass").fetchone()
            max_id=max(conn.execute(sql.SQL('SELECT coalesce(max(id),0) AS n FROM cartago.{}').format(
                sql.Identifier(layer))).fetchone()['n'] for layer in LAYERS)
            assert not conn.execute('SELECT gid FROM pg_prepared_xacts').fetchall()
        meta['last_value']=pitr.clone_query(clone,'SELECT last_value FROM cartago.sigtec_ids')[0]['last_value']
        proposal=rejoin.next_candidate(1,max_id,meta,max(high,max_id))
        assert proposal['candidate'] is not None
        backup.save(journal/'approved-plan.json',{'fixture_deletion_only':pit['fixture']['id'],
                   'donor_table_hashes':{node:state['data'] for node,state in cut.items()},'sequence':proposal,
                   'exports_sha256':{table:backup.checksum(path) for table,path in files.items()}})
        phase('fence_only_lab_owner')
        with backup.admin('central',values) as conn:
            conn.execute('ALTER SUBSCRIPTION sub_central_cartago DISABLE')
        old_owner=existing['cartago']
        lab.run(['docker','stop','--time','30',old_owner])
        assert not json.loads(lab.run(['docker','inspect',old_owner]))[0]['State']['Running']
        report['old_owner']={'container':'sig-tec-rejoin-lab-cartago-1','stopped':True,'volume_preserved':True}
        phase('reconcile_isolated_copy')
        for table,path in files.items():
            reconcile(clone,table,path,[pit['fixture']['id']] if table=='cartago.edificios' else [])
        clone_sql(clone,"SELECT setval('cartago.sigtec_ids',"+str(proposal['candidate'])+',false);')
        actual=backup.fingerprint(lambda query:pitr.clone_query(clone,query))
        assert actual==cut['cartago']['data']
        assert not pitr.clone_query(clone,'SELECT gid FROM pg_prepared_xacts')
        report['reconciliation']={'all_40_tables_and_styles_match_cut':True,'marker_copied_from_verified_owner':True,
                                  'fixture_deletion_only':pit['fixture']['id'],'sequence_next':proposal['candidate'],
                                  'historical_issued_bound':max(high,max_id),'copy_data_false_basis':'Igualdad completa con el corte congelado'}
        phase('activate_single_replacement')
        lab.run(['docker','stop','--time','30',clone])
        # Se retira solo el contenedor temporal. Su directorio bind se conserva.
        lab.run(['docker','rm',clone])
        replacement='sig-tec-rejoin-lab-cartago-recovered'
        archive_volume=lab.PROJECT+'_cartago_recovered_wal'
        image=json.loads(lab.run(['docker','image','inspect','postgis/postgis:17-3.6']))[0]['Id']
        flags=['wal_level=logical','max_replication_slots=32','max_wal_senders=32',
               'max_logical_replication_workers=32','max_worker_processes=48','max_prepared_transactions=10',
               'archive_mode=on','archive_command='+runtime.config()['archive_command'], 'listen_addresses=*']
        new_id=lab.run(['docker','run','-d','--pull','never','--name',replacement,
            '--label','com.docker.compose.project='+lab.PROJECT,'--label','com.docker.compose.service=cartago',
            '--network',lab.PROJECT+'_control','--network-alias','cartago_recovered','-p','127.0.0.1:58436:5432',
            '--mount',f'type=bind,source={clone_data},target=/var/lib/postgresql/data',
            '--mount',f'type=volume,source={archive_volume},target=/wal-archive',
            '--mount',f'type=bind,source={runtime.ROOT / "archive-wal.sh"},target=/ops/archive-wal.sh,readonly',
            '--mount',f'type=bind,source={runtime.ROOT / "start-postgres.sh"},target=/ops/start-postgres.sh,readonly',
            '--entrypoint','/bin/sh',image,'/ops/start-postgres.sh','postgres',
            *[part for flag in flags for part in ('-c',flag)]]).strip()
        lab.run(['docker','network','connect','--alias','cartago_recovered',lab.PROJECT+'_default',new_id])
        cfg_path=Path(__import__('os').environ['SIGTEC_OPS_CONFIG'])
        cfg=json.loads(cfg_path.read_text(encoding='utf-8'))
        cfg['nodes']['cartago']['port']=58436
        cfg['data_mounts']={'cartago':str(clone_data)}
        cfg['archive_volumes']={'cartago':archive_volume}
        cfg_path.write_text(json.dumps(cfg,indent=2)+'\n',encoding='utf-8')
        new_node=rename.Node('cartago',58436,'cartago')
        rename.CAMPUSES[1]=new_node
        backup.NODES['cartago']=new_node
        def ready():
            try:
                with backup.admin('cartago',values) as conn: return bool(conn.execute('SELECT 1').fetchone())
            except psycopg.Error: return False
        checks.wait_for(ready,'El reemplazo no inició')
        phase('new_slots_without_deleting_old_channels')
        with backup.admin('cartago',values) as conn:
            conn.autocommit=True
            conn.execute("SELECT pg_create_logical_replication_slot('slot_central_cartago_rejoin','pgoutput')")
        with backup.admin('central',values) as conn:
            conn.autocommit=True
            conn.execute("SELECT pg_create_logical_replication_slot('slot_cartago_central_rejoin','pgoutput')")
            create_subscription(conn,'sub_central_cartago_rejoin','cartago_recovered',
                                ['pub_cartago_edificios'],'slot_central_cartago_rejoin',values)
        with backup.admin('cartago',values) as conn:
            conn.autocommit=True
            create_subscription(conn,'sub_cartago_central_rejoin','central',
                [pub for campus,pub in rejoin.PUBLICATIONS.items() if campus!='cartago']+['pub_layer_styles'],
                'slot_cartago_central_rejoin',values)
        phase('verify_replication_and_sequence')
        new_building=checks.fixture('cartago','Alta del único propietario recuperado')
        assert new_building==proposal['candidate'] and new_building>max_id and new_building%5==1
        current=checks.row('cartago','cartago',new_building)
        checks.converge('cartago',new_building,current)
        # UPDATE y DELETE controlados solo sobre esta nueva fila de ensayo.
        with backup.admin('cartago',values) as conn:
            conn.execute('UPDATE cartago.edificios SET nombre=%s WHERE id=%s',('Editado tras reincorporar Ñandú',new_building))
        checks.converge('cartago',new_building,checks.row('cartago','cartago',new_building))
        with backup.admin('cartago',values) as conn:
            conn.execute('DELETE FROM cartago.edificios WHERE id=%s',(new_building,))
        checks.converge('cartago',new_building,None)
        incoming2=checks.fixture('san_jose','Entrada al reemplazo después de activar')
        checks.converge('san_jose',incoming2,checks.row('san_jose','san_jose',incoming2))
        final_op=uuid4()
        assert rename.rename(final_op,1,own_id,'2PC después de reincorporar José 🏢',values)['status']=='completed'
        assert rename.rename(final_op,1,own_id,'2PC después de reincorporar José 🏢',values)['repeated']
        checks.converge('cartago',own_id,checks.row('cartago','cartago',own_id))
        checks.wait_for(checks.all_geography_converged,'No convergen las 40 tablas al finalizar')
        for node in backup.NODES:
            with backup.admin(node,values) as conn:
                assert not conn.execute('SELECT gid FROM pg_prepared_xacts').fetchall()
        assert not json.loads(lab.run(['docker','inspect',old_owner]))[0]['State']['Running']
        assert json.loads(lab.run(['docker','inspect',new_id]))[0]['State']['Running']
        assert len(lab.run(['docker','ps','-q','--filter','label=com.docker.compose.project='+lab.PROJECT,
                           '--filter','label=com.docker.compose.service=cartago']).split())==1
        replication_checks={}
        for node in backup.NODES:
            with backup.admin(node,values) as conn:
                count=conn.execute('SELECT count(*) AS n FROM pg_subscription WHERE subenabled').fetchone()['n']
                assert count==(5 if node=='central' else 1)
                assert not conn.execute("SELECT 1 FROM pg_subscription_rel r JOIN pg_subscription s ON s.oid=r.srsubid WHERE s.subenabled AND r.srsubstate<>'r'").fetchall()
                replication_checks[node]={'enabled_subscriptions':count,'all_active_relations_ready':True}
        report['replication_catalogs']=replication_checks
        actual_inventory=inventory()
        assert all(actual_inventory.get(cid)==state for cid,state in outsiders.items())
        report.update(status='passed',finished_at_utc=datetime.now(timezone.utc).isoformat(),
                      replacement={'container':replacement,'port':58436,'archive_volume':archive_volume},
                      checks={'old_owner_still_stopped':True,'new_owner_only':True,'all_geography_converged':True,
                              'insert_update_delete_both_hops':True,'incoming_replication':True,'two_phase_retry':True,
                              'sequence_class_and_high_water':True,'prepared_transactions':0,'outsiders_unchanged':True,
                              'no_old_slots_or_subscriptions_deleted':True})
        phase('completed')
        return report
    except Exception as error:
        diagnostic=str(error)
        for value in values.values():
            if len(value)>10: diagnostic=diagnostic.replace(value,'[redacted]')
        (journal/'error.txt').write_text(type(error).__name__+': '+diagnostic,encoding='utf-8')
        report.update(status='failed',error_type=type(error).__name__,
                      diagnostic='No se eliminaron volúmenes ni se repararon los nodos ajenos; conservar todos los artefactos.')
        backup.save(out,report)
        raise RuntimeError('Ensayo incompleto en fase '+report['phase']+'; revisar evidencia privada.') from None


def verify_only():
    checks.require_lab()
    import wal
    wal.preflight()
    old=json.loads(lab.run(['docker','inspect','sig-tec-rejoin-lab-cartago-1']))[0]
    assert not old['State']['Running']
    active=lab.run(['docker','ps','-q','--filter','label=com.docker.compose.project='+lab.PROJECT,
                    '--filter','label=com.docker.compose.service=cartago']).split()
    assert len(active)==1
    checks.wait_for(checks.all_geography_converged,'No convergen los seis nodos')
    catalog={}
    for node in backup.NODES:
        with backup.admin(node,rename.configuration()) as conn:
            assert not conn.execute('SELECT gid FROM pg_prepared_xacts').fetchall()
            enabled=conn.execute('SELECT count(*) AS n FROM pg_subscription WHERE subenabled').fetchone()['n']
            assert enabled==(5 if node=='central' else 1)
            relations=conn.execute("SELECT count(*) AS n, bool_and(r.srsubstate='r') AS ready "
                'FROM pg_subscription_rel r JOIN pg_subscription s ON s.oid=r.srsubid WHERE s.subenabled').fetchone()
            assert relations['ready'] and relations['n']==(40 if node=='central' else 33)
            catalog[node]={'enabled_subscriptions':enabled,**relations}
    path=runtime.ROOT/'rejoin-execution-results.json'
    report=json.loads(path.read_text(encoding='utf-8'))
    report['final_read_only_verification']={'executed_at_utc':datetime.now(timezone.utc).isoformat(),
        'replication_catalogs':catalog,'all_geography_converged':True,'prepared_transactions':0,'single_owner':True}
    backup.save(path,report)
    print('Reemplazo validado: un propietario, 5+5 suscripciones activas, relaciones listas y cero GID.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approve-lab-replacement',action='store_true')
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    if args.verify_only: verify_only()
    elif args.approve_lab_replacement: run()
    else: parser.error('Se requiere --verify-only o aprobación explícita del ensayo de laboratorio.')
