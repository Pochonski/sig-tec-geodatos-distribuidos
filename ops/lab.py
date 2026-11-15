"""Preparación explícita de un laboratorio nuevo; nunca utiliza volúmenes ajenos."""
import json
import os
from pathlib import Path
import secrets
import socket
import string
import subprocess
import tarfile
import io

import runtime

ROOT=runtime.ROOT
LAB=ROOT/'rejoin-lab'
PROJECT='sig-tec-rejoin-lab'
REFERENCE='f3e1f91e1e61e2f293fac4ba50de209cc0af65ea'
NAMES=('central',*runtime.CAMPUSES.values())


def run(args, *, data=None):
    result=subprocess.run(args,input=data,capture_output=True)
    if result.returncode:
        raise RuntimeError('Falló el comando de laboratorio; salida omitida para proteger credenciales.')
    return result.stdout.decode('utf-8')


def compose(*args):
    return ['docker','compose','-p',PROJECT,'--env-file',str(LAB/'.env'),
            '-f',str(LAB/'source/compose.yaml'),'-f',str(ROOT/'rejoin-lab.override.yaml'),
            '-f',str(LAB/'wal-overlay.json'),*args]


def prepare():
    if LAB.exists(): raise RuntimeError('El laboratorio ya existe; no se sobrescribe.')
    if run(['docker','ps','-aq','--filter',f'label=com.docker.compose.project={PROJECT}']).strip():
        raise RuntimeError('El proyecto de laboratorio tiene contenedores existentes.')
    if run(['docker','volume','ls','-q','--filter',f'label=com.docker.compose.project={PROJECT}']).strip():
        raise RuntimeError('El proyecto de laboratorio tiene volúmenes existentes.')
    for i in range(6):
        with socket.socket() as probe: probe.bind(('127.0.0.1',58430+i))
    os.umask(0o077)
    (LAB/'source').mkdir(parents=True)
    archive=subprocess.check_output(['git','archive',REFERENCE,'compose.yaml','db','.env.example'])
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(LAB/'source',filter='data')
    keys=['SIGTEC_ADMIN_PASSWORD','SIGTEC_REPLICATION_PASSWORD',
          *[f'SIGTEC_{name.upper()}_PASSWORD' for name in runtime.CAMPUSES.values()]]
    credentials={key:''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(40)) for key in keys}
    (LAB/'.env').write_text(''.join(key+'='+value+'\n' for key,value in credentials.items()),encoding='utf-8')
    cfg={'project':PROJECT,'integrated':True,'env_file':'.env','archive_command':'/bin/sh /ops/archive-wal.sh "%p" "%f" /wal-archive','nodes':{}}
    overlay={'services':{},'volumes':{},'networks':{'control':{'driver':'bridge'}}}
    flags=['wal_level=logical','max_replication_slots=32','max_wal_senders=32',
           'max_logical_replication_workers=32','max_worker_processes=48','max_prepared_transactions=10',
           'archive_mode=on','archive_command=/bin/sh /ops/archive-wal.sh "%p" "%f" /wal-archive']
    for i,name in enumerate(NAMES):
        cfg['nodes'][name]={'host':'127.0.0.1','port':58430+i,'admin_password_env':'SIGTEC_ADMIN_PASSWORD',
                            'cli_password_env':f'OPS_{name.upper()}_CLI_PASSWORD'}
        overlay['volumes'][name+'_wal']={}
        overlay['services'][name]={'networks':['default','control'],'entrypoint':['/bin/sh','/ops/start-postgres.sh'],
            'command':['postgres',*[part for flag in flags for part in ('-c',flag)]],
            'volumes':[{'type':'volume','source':name+'_wal','target':'/wal-archive'},
                       *[{'type':'bind','source':str(ROOT/file),'target':'/ops/'+file,'read_only':True}
                         for file in ('archive-wal.sh','start-postgres.sh')]]}
    (LAB/'runtime.json').write_text(json.dumps(cfg,indent=2)+'\n',encoding='utf-8')
    (LAB/'wal-overlay.json').write_text(json.dumps(overlay,indent=2)+'\n',encoding='utf-8')
    validate()


def validate():
    rendered=json.loads(run(compose('config','--format','json')))
    assert all(value['name'].startswith(PROJECT+'_') and not value.get('external') for value in rendered['volumes'].values())
    assert rendered['networks']['default']['internal']
    for name in NAMES:
        assert all(rendered['volumes'][v['source']]['name'].startswith(PROJECT+'_') or v['type']=='bind'
                   for v in rendered['services'][name]['volumes'] if v['type']=='volume')
    print('Laboratorio validado: proyecto, puertos, red interna y volúmenes nuevos.')


def execute(args):
    if json.loads((LAB/'runtime.json').read_text(encoding='utf-8')).get('data_mounts'):
        raise RuntimeError('Laboratorio reincorporado: no ejecutar up/bootstrap ni reactivar el propietario anterior.')
    proc=subprocess.run(args,capture_output=True)
    if proc.returncode:
        (LAB/'last-error.log').write_bytes(proc.stdout+proc.stderr)
        raise RuntimeError('Error de laboratorio; revisar last-error.log privado sin publicar secretos.')
    print('Comando completado.',flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','validate','start','bootstrap'))
    args=parser.parse_args()
    if args.action=='prepare': prepare()
    elif args.action=='validate': validate()
    elif args.action=='start': validate(); execute(compose('up','-d','--pull','never','--wait',*NAMES))
    else: execute(compose('run','--rm','bootstrap'))
