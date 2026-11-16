"""Arnés exclusivo de pruebas: interrupciones reales sin apagar bases ni contenedores."""
import argparse
from dataclasses import replace
import os
import sys
from uuid import UUID

import rename
import recover

POINTS = ('after_first_prepare', 'after_both_prepare', 'after_decision', 'after_first_commit')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    crash = commands.add_parser('crash')
    crash.add_argument('operation_id', type=UUID)
    crash.add_argument('building_id', type=int)
    crash.add_argument('new_name')
    crash.add_argument('checkpoint', choices=POINTS)
    offline = commands.add_parser('offline')
    offline.add_argument('operation_id', type=UUID)
    offline.add_argument('port', type=int)
    args = parser.parse_args()
    if args.command == 'offline':
        # Solo este proceso usa el puerto inaccesible controlado por la prueba.
        rename.CENTRAL = replace(rename.CENTRAL, port=args.port)
        sys.argv = ['recover.py', str(args.operation_id)]
        return recover.main()

    def checkpoint(point):
        if point == args.checkpoint:
            print(point, flush=True)
            # No finally ni cierre limpio de conexiones: el sistema operativo
            # las cierra y PostgreSQL conserva únicamente las ramas preparadas.
            os._exit(86)

    rename.rename(args.operation_id, 1, args.building_id, args.new_name, _checkpoint=checkpoint)
    raise RuntimeError('El punto de interrupción no fue alcanzado')


if __name__ == '__main__':
    sys.exit(main())
