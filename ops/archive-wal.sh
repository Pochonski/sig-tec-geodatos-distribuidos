#!/bin/sh
# Uso: sh archive-wal.sh %p %f /wal-archive
# PostgreSQL solo puede reciclar el segmento si terminamos con código 0.
set -eu
umask 077

if [ "$#" -ne 3 ]; then
    echo 'archive-wal: se requieren origen, nombre y directorio de archivo' >&2
    exit 64
fi
source_file=$1
wal_name=$2
archive_dir=$3

if ! printf '%s\n' "$wal_name" | grep -Eq '^([0-9A-F]{24}|[0-9A-F]{8}\.history|[0-9A-F]{24}\.[0-9A-F]{8}\.backup)$'; then
    echo 'archive-wal: nombre WAL inválido' >&2
    exit 64
fi
if [ ! -f "$source_file" ] || [ ! -s "$source_file" ] || [ -L "$source_file" ]; then
    echo 'archive-wal: origen ausente, vacío o no regular' >&2
    exit 1
fi
if [ ! -d "$archive_dir" ] || [ -L "$archive_dir" ]; then
    echo 'archive-wal: directorio persistente no disponible' >&2
    exit 1
fi
destination=$archive_dir/$wal_name
identical() {
    [ ! -L "$destination" ] && [ -f "$destination" ] && cmp -s -- "$source_file" "$destination"
}

# Nunca reescribir un archivo publicado, aunque exista tras una caída previa.
if [ -e "$destination" ] || [ -L "$destination" ]; then
    if identical; then
        sync -f "$destination"
        sync -f "$archive_dir"
        exit 0
    fi
    echo 'archive-wal: destino existente con contenido diferente o tipo inválido' >&2
    exit 1
fi

# Copia privada en el mismo filesystem. Publicación atómica sin reemplazo:
# ln -T falla si otro proceso ya creó el destino (también si es un directorio).
temporary=$(mktemp "$archive_dir/.wal-$wal_name.XXXXXX")
trap 'rm -f -- "$temporary"' EXIT
trap 'exit 1' HUP INT TERM
cp -- "$source_file" "$temporary"
chmod 600 "$temporary"
sync -f "$temporary"
if ! ln -T -- "$temporary" "$destination" 2>/dev/null; then
    if ! identical; then
        echo 'archive-wal: no se pudo publicar el segmento sin sobrescribir' >&2
        exit 1
    fi
fi
rm -f -- "$temporary"
trap - EXIT
# sync -f usa syncfs en Linux: también hace duradero el enlace de directorio.
sync -f "$archive_dir"
exit 0
