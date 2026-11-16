#!/usr/bin/env python3
"""Aplica SQL a los contenedores existentes; no gestiona su ciclo de vida."""
import base64
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import subprocess
import runtime

ROOT = Path(__file__).resolve().parent
ROLE = 'sig_tec_ops_cli'


def containers():
    result = {}
    for node in runtime.config()['nodes']:
        ids = subprocess.check_output([
            'docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=' + runtime.config()['project'],
            '--filter', f'label=com.docker.compose.service={node}',
        ], text=True, encoding='utf-8').split()
        if len(ids) != 1:
            raise RuntimeError(f'Se requiere un contenedor existente activo para {node}')
        result[node] = ids[0]
    return result


def configuration():
    path = Path(runtime.config()['env_file'])
    if not path.resolve().is_relative_to(ROOT):
        raise RuntimeError('El archivo de credenciales modificable debe estar dentro de ops/.')
    values = runtime.values()
    os.chmod(path, 0o600)
    for node in runtime.config()['nodes'].values():
        key = node['cli_password_env']
        if not values.get(key):
            values[key] = secrets.token_urlsafe(48)
            lines = path.read_text(encoding='utf-8-sig').splitlines()
            lines = [line for line in lines if line.split('=',1)[0].strip() != key]
            lines.append(f'{key}={values[key]}')
            path.write_text('\n'.join(lines)+'\n', encoding='utf-8')
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,}', values[key]):
            raise RuntimeError(f'{key} requiere al menos 32 caracteres A-Z, a-z, 0-9, _ o -')
    return values


def verifier(password):
    """SCRAM-SHA-256: el SQL no contiene la contraseña en texto claro."""
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 4096)
    client = hmac.digest(salted, b'Client Key', 'sha256')
    stored = hashlib.sha256(client).digest()
    server = hmac.digest(salted, b'Server Key', 'sha256')
    enc = lambda value: base64.b64encode(value).decode()
    return f'SCRAM-SHA-256$4096:{enc(salt)}${enc(stored)}:{enc(server)}'


def sql(container, statement, password=None):
    args = ['docker', 'exec', '-i', container]
    if password is None:
        args += ['env', 'PGCLIENTENCODING=UTF8', 'psql', '-X', '-qAt', '-U', 'postgres', '-d', 'sig_tec',
                 '-v', 'ON_ERROR_STOP=1']
        data = statement
    else:
        # Secreto por stdin, nunca en argumentos, archivos temporales ni salida.
        args += ['sh', '-c', 'IFS= read -r PGPASSWORD; export PGPASSWORD; '
                 'exec env PGCLIENTENCODING=UTF8 psql -X -qAt -h 127.0.0.1 -U sig_tec_ops_cli '
                 '-d sig_tec -v ON_ERROR_STOP=1']
        data = password + '\n' + statement
    proc = subprocess.run(args, input=data.encode('utf-8'), capture_output=True)
    if proc.returncode:
        # No imprimir SQL, verificadores ni posibles secretos de diagnósticos.
        raise RuntimeError('Falló SQL en el contenedor; salida omitida por seguridad')
    return proc.stdout.decode('utf-8').strip()


def apply(nodes, values):
    common = (ROOT / 'migrations/001_common.sql').read_text(encoding='utf-8')
    for node, container in nodes.items():
        filename = '002_central.sql' if node == 'central' else ('004_participant.sql' if runtime.config().get('integrated') else '003_cartago.sql')
        statement = 'BEGIN;\nSELECT pg_advisory_xact_lock(57430, 1);\n' + common
        participant = (ROOT / 'migrations' / filename).read_text(encoding='utf-8')
        if filename == '004_participant.sql':
            campus_id = next(key for key,value in runtime.CAMPUSES.items() if value == node)
            participant = participant.replace(':campus_id',str(campus_id)).replace(':campus_schema',node)
        statement += participant
        secret = runtime.password(node,'cli',values)
        statement += f"\nALTER ROLE {ROLE} PASSWORD '{verifier(secret)}';\nCOMMIT;"
        sql(container, statement)
        print(f'{node}: migración aplicada.')
    if not runtime.config().get('integrated'):
        sql(nodes['cartago'], 'BEGIN;\n' + (ROOT / 'fixtures/cartago.sql').read_text(encoding='utf-8') + '\nCOMMIT;')
        print('Semilla aplicada sin sobrescribir filas existentes.')


if __name__ == '__main__':
    try:
        apply(containers(), configuration())
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
