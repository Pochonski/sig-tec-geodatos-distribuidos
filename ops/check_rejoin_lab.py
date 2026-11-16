"""Valida el Compose de laboratorio en memoria. No crea recursos Docker."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess

import backup
import rejoin
from verify import inventory

ROOT = Path(__file__).resolve().parent


def check():
    before = inventory()
    contract = rejoin.reference_contract()
    source = rejoin.command(['git','show',contract['commit'] + ':compose.yaml'])
    variables = ['SIGTEC_ADMIN_PASSWORD','SIGTEC_REPLICATION_PASSWORD',
                 *['SIGTEC_' + campus.upper() + '_PASSWORD' for campus in rejoin.CAMPUSES.values()]]
    # Valores efímeros solo para interpolar; nunca se inicia el stack ni se imprimen.
    environment = {**os.environ, **{key: secrets.token_hex(16) for key in variables}}
    proc = subprocess.run(['docker','compose','-p','sig-tec-rejoin-lab','--env-file','/dev/null',
        '--project-directory',str(ROOT/'rejoin-lab/source'), '-f','-',
        '-f',str(ROOT/'rejoin-lab.override.yaml'),'config','--format','json'],
        input=source,env=environment,text=True,capture_output=True, encoding='utf-8')
    if proc.returncode:
        raise rejoin.CheckError('Falta soporte Compose !override (requiere >=2.24.4) o la configuración no valida.')
    rendered = json.loads(proc.stdout)
    assert rendered['networks']['default']['internal'] is True
    ports = {}
    for index,node in enumerate(contract['nodes']):
        published = rendered['services'][node]['ports']
        assert len(published)==1 and published[0]['host_ip']=='127.0.0.1'
        assert int(published[0]['published'])==58430+index
        ports[node] = int(published[0]['published'])
    volumes = [entry['name'] for entry in rendered['volumes'].values()]
    assert all(name.startswith('sig-tec-rejoin-lab_') for name in volumes)
    available = {}
    for node,port in ports.items():
        try:
            with socket.socket() as listener: listener.bind(('127.0.0.1',port))
            available[node] = True
        except OSError:
            available[node] = False
    existing = rejoin.command(['docker','ps','-aq','--filter','label=com.docker.compose.project=sig-tec-rejoin-lab'])
    assert inventory()==before
    report = {'checked_at_utc':datetime.now(timezone.utc).isoformat(), 'reference_commit':contract['commit'],
              'compose_version':rejoin.command(['docker','compose','version','--short']),
              'configuration_valid':True,'database_started':False,'existing_containers_unchanged':True,
              'ports':ports,'ports_free':available,'volume_names':volumes,
              'lab_containers_already_exist':bool(existing),
              'missing_before_runtime_test':['Materializar la fuente fijada en ops/rejoin-lab/source',
                  'Crear ops/rejoin-lab/.env con las siete variables SIGTEC de Joseph',
                  'Aprobar creación y bootstrap de un stack nuevo aislado de seis nodos',
                  'Integrar migraciones ops sin fixtures mínimos, rutas de CLI y respaldo/PITR con geometría',
                  'Disponer de una copia restaurada sin red, historial de cambios e IDs emitidos y fencing validado']}
    backup.save(ROOT/'rejoin-lab-check.json',report)
    print('Compose de seis nodos validado sin crear recursos; ver ops/rejoin-lab-check.json')
    return report


if __name__ == '__main__':
    try:
        check()
    except (rejoin.CheckError, OSError, ValueError, KeyError, AssertionError):
        raise SystemExit('Validación incompleta; no se creó ningún recurso. Revisar referencia, Compose e inventario.') from None
