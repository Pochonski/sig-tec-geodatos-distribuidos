"""Pruebas del módulo sobre el modelo completo; solo en sig-tec-rejoin-lab."""
from datetime import datetime, timezone
import json
import sys
import time
from uuid import uuid4

import psycopg
from psycopg import sql

import backup
import rename
import runtime


def require_lab():
    if runtime.config()['project']!='sig-tec-rejoin-lab' or not runtime.config().get('integrated'):
        raise RuntimeError('Esta prueba con escrituras solo se permite en sig-tec-rejoin-lab.')


def wait_for(condition, message, timeout=90):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if condition(): return
        time.sleep(0.3)
    raise RuntimeError(message)


def fixture(campus, name):
    with backup.admin(campus,rename.configuration()) as conn:
        row=conn.execute('INSERT INTO sig.edificios (nombre,codigo,area,pisos,geom) '
            'VALUES (%s,%s,4,1,public.ST_MakeEnvelope(500000,1100000,500002,1100002,8908)) RETURNING id',
            (name,'OPS-'+uuid4().hex)).fetchone()
        return row['id']


def row(node,campus,identifier):
    with backup.admin(node,rename.configuration()) as conn:
        return conn.execute(sql.SQL("SELECT id,campus_id,nombre,codigo,area,pisos,encode(public.ST_AsEWKB(geom),'hex') AS geom "
                                    'FROM {}.edificios WHERE id=%s').format(sql.Identifier(campus)),(identifier,)).fetchone()


def converge(campus, identifier, expected):
    wait_for(lambda: all(row(node,campus,identifier)==expected for node in backup.NODES),
             'No convergieron los seis nodos para '+campus)


def geographic_hashes(node):
    with backup.admin(node,rename.configuration()) as conn:
        result=backup.fingerprint(lambda query:conn.execute(query).fetchall())
    return {name:d['sha256'] for name,d in result['tables'].items()
            if name.split('.')[0] in runtime.CAMPUSES.values() or name=='public.layer_styles'}


def all_geography_converged():
    reference=geographic_hashes('central')
    return all(geographic_hashes(node)==reference for node in runtime.CAMPUSES.values())


def run():
    require_lab()
    values=rename.configuration()
    checks=[]
    for campus_id,campus in runtime.CAMPUSES.items():
        identifier=fixture(campus,'Fixture integrado '+uuid4().hex)
        original=row(campus,campus,identifier)
        converge(campus,identifier,original)
        operation=uuid4()
        name=f'José Ñandú – Cartago 🏢 東京 / {campus}'
        result=rename.rename(operation,campus_id,identifier,name,values)
        assert result['status']=='completed'
        expected={**original,'nombre':name}
        converge(campus,identifier,expected)
        retry=rename.rename(operation,campus_id,identifier,name,values)
        assert retry['repeated']
        try: rename.rename(operation,campus_id,identifier,'Datos diferentes',values)
        except rename.OperationError: pass
        else: raise AssertionError('Se aceptó UUID con datos distintos')
        with rename.connect(rename.CAMPUSES[campus_id],values) as conn:
            for column in ('id','campus_id','geom'):
                try:
                    conn.execute(sql.SQL('UPDATE {}.edificios SET {}={} WHERE id=%s').format(
                        sql.Identifier(campus),sql.Identifier(column),sql.Identifier(column)),(identifier,))
                except psycopg.errors.InsufficientPrivilege: pass
                else: raise AssertionError('Permiso excesivo para '+column)
        with backup.admin('central',values) as conn:
            assert conn.execute('SELECT decision FROM ops.decisions WHERE operation_id=%s',(operation,)).fetchone()['decision']=='COMMIT'
            assert conn.execute('SELECT count(*) AS n FROM ops.audit WHERE operation_id=%s',(operation,)).fetchone()['n']==1
        for node in ('central',campus):
            with backup.admin(node,values) as conn:
                assert not conn.execute('SELECT gid FROM pg_prepared_xacts').fetchall()
        checks.append({'campus':campus,'building_id':identifier,'operation_id':str(operation),
                       'utf8_roundtrip':True,'replication_six_nodes':True,'geom_preserved':True,
                       'retry_idempotent':True,'permissions_rejected':['id','campus_id','geom']})
    wait_for(all_geography_converged,'Hay diferencias geográficas entre nodos')
    report={'executed_at_utc':datetime.now(timezone.utc).isoformat(),'project':runtime.config()['project'],
            'status':'passed','campus_checks':checks,'all_40_geographic_tables_converged':True,
            'prepared_transactions':0,'windows_execution':'pending; estas pruebas se ejecutaron en Parrot/Linux'}
    backup.save(runtime.ROOT/'integrated-results.json',report)
    print('Cinco campus: UTF-8, 2PC, permisos y replicación verificados.')
    return report


if __name__=='__main__': run()
