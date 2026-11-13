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

ROOT = Path(__file__).resolve().parent
ROLE = 'sig_tec_ops_cli'


def containers():
    result = {}
    for node in ('central', 'cartago'):
        ids = subprocess.check_output([
            'docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=sig-tec-ops',
            '--filter', f'label=com.docker.compose.service={node}',
        ], text=True).split()
        if len(ids) != 1:
            raise RuntimeError(f'Se requiere un contenedor existente activo para {node}')
        result[node] = ids[0]
    return result


def configuration():
    path = ROOT / '.env'
    values = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('\"\'')
    os.chmod(path, 0o600)
    for node in ('CENTRAL', 'CARTAGO'):
        key = f'OPS_{node}_CLI_PASSWORD'
        if not values.get(key):
            values[key] = secrets.token_urlsafe(48)
            lines = path.read_text().splitlines()
            lines = [line for line in lines if line.split('=', 1)[0].strip() != key]
            lines.append(f'{key}={values[key]}')
            path.write_text('\n'.join(lines) + '\n')
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
        args += ['psql', '-X', '-qAt', '-U', 'postgres', '-d', 'sig_tec',
                 '-v', 'ON_ERROR_STOP=1']
        data = statement
    else:
        # Secreto por stdin, nunca en argumentos, archivos temporales ni salida.
        args += ['sh', '-c', 'IFS= read -r PGPASSWORD; export PGPASSWORD; '
                 'exec psql -X -qAt -h 127.0.0.1 -U sig_tec_ops_cli '
                 '-d sig_tec -v ON_ERROR_STOP=1']
        data = password + '\n' + statement
    proc = subprocess.run(args, input=data, text=True, capture_output=True)
    if proc.returncode:
        # No imprimir SQL, verificadores ni posibles secretos de diagnósticos.
        raise RuntimeError('Falló SQL en el contenedor; salida omitida por seguridad')
    return proc.stdout.strip()


def apply(nodes, values):
    common = (ROOT / 'migrations/001_common.sql').read_text()
    for node, container in nodes.items():
        filename = '002_central.sql' if node == 'central' else '003_cartago.sql'
        statement = 'BEGIN;\nSELECT pg_advisory_xact_lock(57430, 1);\n' + common
        statement += (ROOT / 'migrations' / filename).read_text()
        secret = values[f'OPS_{node.upper()}_CLI_PASSWORD']
        statement += f"\nALTER ROLE {ROLE} PASSWORD '{verifier(secret)}';\nCOMMIT;"
        sql(container, statement)
        print(f'{node}: migración aplicada.')
    sql(nodes['cartago'], 'BEGIN;\n' + (ROOT / 'fixtures/cartago.sql').read_text() + '\nCOMMIT;')
    print('Semilla aplicada sin sobrescribir filas existentes.')


if __name__ == '__main__':
    try:
        apply(containers(), configuration())
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
