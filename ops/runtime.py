"""Configuración local explícita; no almacena contraseñas en el inventario JSON."""
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
CAMPUSES = {1:'cartago', 2:'san_jose', 3:'san_carlos', 4:'alajuela', 5:'limon'}


def config():
    path = os.environ.get('SIGTEC_OPS_CONFIG')
    if path:
        result = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        result['env_file'] = str((Path(path).resolve().parent / result['env_file']).resolve())
    else:
        result = {'project':'sig-tec-ops','env_file':str(ROOT/'.env'),'integrated':False,
                  'nodes':{name:{'host':'127.0.0.1','port':port,'admin_password_env':f'OPS_{name.upper()}_PASSWORD',
                                 'cli_password_env':f'OPS_{name.upper()}_CLI_PASSWORD'}
                           for name,port in (('central',57430),('cartago',57431))}}
    # El proyecto Compose de la instalación inicial de Joseph ya tiene volúmenes
    # persistentes con este prefijo. No cambiarlo al incorporar operaciones.
    allowed = result['project'] == 'iiiproyectobasesii' or re.fullmatch(r'sig-tec[-a-z0-9]+', result['project'])
    if not allowed:
        raise RuntimeError('Proyecto Docker fuera del espacio sig-tec.')
    if 'central' not in result['nodes'] or set(result['nodes'])-{'central',*CAMPUSES.values()}:
        raise RuntimeError('Inventario de nodos inválido.')
    for node in result['nodes'].values():
        if set(node)-{'host','port','admin_password_env','cli_password_env'}:
            raise RuntimeError('El inventario no admite contraseñas literales.')
        for key in ('admin_password_env','cli_password_env'):
            if not re.fullmatch(r'[A-Z][A-Z0-9_]*',node[key]): raise RuntimeError('Variable de contraseña inválida.')
    return result


def values():
    result = {}
    for line in Path(config()['env_file']).read_text(encoding='utf-8-sig').splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            key,value = line.split('=',1)
            value=value.strip()
            if len(value)>=2 and value[0]==value[-1] and value[0] in "\"'": value=value[1:-1]
            result[key.strip()]=value
    for node in config().get('nodes',{}).values():
        for field in ('admin_password_env','cli_password_env'):
            key=node[field]
            if key in os.environ: result[key]=os.environ[key]
    return result


def password(node, kind, credentials):
    key=config()['nodes'][node][kind+'_password_env']
    value=os.environ.get(key) or credentials.get(key)
    if not value: raise RuntimeError('Falta la variable local '+key)
    return value
