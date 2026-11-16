#!/usr/bin/env python3
"""Publica los ocho QML en el central del proyecto Compose indicado."""

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, help='Nombre exacto del proyecto Compose')
    args = parser.parse_args()

    # El SQL contiene QML y se transmite como bytes para preservar Unicode en Windows.
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    generated = subprocess.run(
        [sys.executable, '-B', str(ROOT / 'qgis/herramientas/publicar_estilos.py')],
        cwd=ROOT, env=env, capture_output=True,
    )
    if generated.returncode:
        parser.exit(1, 'No se pudo generar el SQL de estilos.\n')

    found = subprocess.run(
        ['docker', 'ps', '-q',
         '--filter', f'label=com.docker.compose.project={args.project}',
         '--filter', 'label=com.docker.compose.service=central'],
        capture_output=True, text=True, encoding='utf-8',
    )
    if found.returncode or len(found.stdout.split()) != 1:
        parser.exit(1, f'Se requiere un central activo del proyecto {args.project}.\n')

    applied = subprocess.run(
        ['docker', 'exec', '-i', found.stdout.strip(), 'env', 'PGCLIENTENCODING=UTF8',
         'psql', '-X', '-q', '-U', 'postgres', '-d', 'sig_tec', '-v', 'ON_ERROR_STOP=1'],
        input=generated.stdout, capture_output=True,
    )
    if applied.returncode:
        parser.exit(1, 'Falló la publicación de estilos en el central.\n')
    print(f'Ocho estilos publicados en el central de {args.project}.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
