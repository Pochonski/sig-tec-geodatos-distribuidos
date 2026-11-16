#!/bin/sh
set -eu
# Solo preparar el directorio montado para WAL, nunca PGDATA ni respaldos.
if ! grep -q ' /wal-archive ' /proc/self/mountinfo; then
    echo 'Falta el montaje persistente /wal-archive' >&2
    exit 1
fi
chown postgres:postgres /wal-archive
chmod 700 /wal-archive
exec /usr/local/bin/docker-entrypoint.sh "$@"
