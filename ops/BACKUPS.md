# Respaldos de Central y Cartago

Usar los contenedores ya activos de `sig-tec-ops`, PostgreSQL 17 y las
dependencias de `ops/requirements.txt`. El script lee las contraseñas
administrativas existentes de `ops/.env`; no genera ni cambia credenciales.
Las pasa por stdin a las herramientas de los contenedores, sin argumentos ni
salida con secretos. El rol limitado de la CLI no recibe nuevos permisos.

## Generar

Desde la raíz del repositorio:

```sh
ops/.venv/bin/python -B ops/backup.py create
```

Genera ambos tipos para ambos nodos. Para limitar una nueva ejecución:

```sh
ops/.venv/bin/python -B ops/backup.py create --node central --kind logical
ops/.venv/bin/python -B ops/backup.py create --node cartago --kind physical
```

Cada ejecución crea un directorio nuevo y no sobrescribe respaldos anteriores:

```text
ops/backups/<fecha-UTC>-<identificador>/
  manifest.json
  central/
    logical.dump
    logical.list
    expected.json
    physical/
      base.tar
      data/                 # copia extraída, incluye backup_manifest
  cartago/
    ...
```

`ops/backups/` está excluido de Git. El script utiliza umask `077`, directorios
privados y archivos de metadatos con permisos `0600`. El respaldo físico contiene
todo el clúster, incluidas las otras bases y los verificadores de contraseñas de
los roles; mantenerlo privado. `ops/backup-results.json` es un resumen sin
credenciales que sí puede versionarse. Se actualiza tras generar o probar una
restauración. Un manifiesto con `status: incomplete` no es un respaldo terminado;
conservarlo para diagnóstico y generar una ejecución nueva.

El lógico usa `pg_dump --format=custom` sobre `sig_tec`. La conexión exporta un
snapshot de solo lectura; tanto el dump como el inventario de tablas y hashes
usan ese mismo snapshot. El respaldo es consistente por base, sin bloquear sus
escrituras. El físico usa `pg_basebackup --format=tar --wal-method=fetch
--checkpoint=fast --manifest-checksums=SHA256`. El checkpoint puede aumentar
temporalmente la E/S. Este procedimiento admite los tablespaces predeterminados;
rechaza tablespaces externos para evitar respaldos incompletos por stdout.

No se cambia `archive_mode`, `pg_hba.conf`, slots ni configuración de los nodos.
Los segmentos necesarios para que el respaldo físico sea consistente se incluyen
en el propio respaldo; esto no configura archivado WAL ni recuperación PITR.

## Verificar respaldos existentes

Sustituir la ruta por la indicada al generar el respaldo:

```sh
ops/.venv/bin/python -B ops/backup.py verify ops/backups/<ID>
```

La verificación no depende de que los nodos originales estén activos. Requiere
que la imagen exacta registrada en `manifest.json` siga disponible localmente.
Se comprueban los SHA-256 del dump, del inventario esperado, del tar físico y del
manifiesto físico. Después se ejecutan:

- `pg_restore --list` para cada archivo personalizado, guardando `logical.list`.
- `pg_verifybackup` sobre cada copia extraída, con comprobación de archivos,
  checksums y análisis del WAL requerido mediante las herramientas PostgreSQL 17.

Las herramientas se ejecutan en contenedores efímeros sin red, con el respaldo
físico montado en solo lectura. No se inicia un servidor desde el respaldo ni
se omite el análisis del WAL. No editar `physical/data/` ni montarlo como PGDATA
de un servidor en ejecución, porque cambiaría el respaldo verificado.

## Restaurar y comprobar los lógicos en aislamiento

```sh
ops/.venv/bin/python -B ops/backup.py restore-test ops/backups/<ID>
```

Primero vuelve a verificar los respaldos. Para cada nodo crea un contenedor
nuevo con la misma imagen, `--network none`, sin puertos publicados y con PGDATA
en tmpfs de 512 MiB. Espera a que PostgreSQL acepte TCP en su loopback interno,
crea `sig_tec` desde `template0` y ejecuta, solo sobre esa instancia nueva:

```text
pg_restore -U postgres -d sig_tec --no-owner --no-privileges \
  --single-transaction --exit-on-error
```

El dump se transmite por stdin. La instancia aislada usa autenticación local
de prueba y no recibe contraseñas de los nodos de origen. Se comparan todas las
tablas de usuario y de extensiones, columnas, restricciones, versiones de
extensiones, conteos y SHA-256 de todas sus filas con `expected.json`. Se incluyen
las tablas de operaciones, edificios y catálogos PostGIS. Los hashes ordenan por
representación JSON con collation `C`, conservan duplicados y comparan valores,
no solo conteos. Las tablas particionadas se cuentan con `ONLY` y sus particiones
por separado para no duplicar filas. El agregado completo está pensado para el
volumen pequeño de esta demostración.

Los contenedores temporales se eliminan al terminar, también si la comparación
falla. No se crea ni elimina ningún volumen persistente de origen. Los datos
restaurados son temporales: para repetir la inspección se vuelve a ejecutar el
comando. Para conjuntos mayores será necesario aumentar el tmpfs de pruebas.

La prueba omite propietarios y ACL al restaurar porque un dump de una base no
crea los roles globales. El archivo original sí conserva sus referencias y ACL.
Para una restauración destinada a conservar permisos, preparar antes los roles
con las migraciones y configuración local y restaurar sin `--no-privileges`;
esa restauración sobre una base operativa queda fuera de estos scripts.

## Procedimiento de restauración física en una instancia nueva

La restauración física no forma parte de la prueba ejecutada en esta etapa:
se generó y comprobó con `pg_verifybackup`. Para ensayarla posteriormente sin
alterar los respaldos ni los nodos actuales, usar **una copia nueva** del PGDATA
verificado y la imagen exacta de la ejecución. Ejemplo desde la raíz, tras
sustituir `<ID>` y seleccionar `central` o `cartago`:

```sh
sigtec_backup_run=ops/backups/<ID>
sigtec_backup_node=central
sigtec_backup_image="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["nodes"][sys.argv[2]]["image"])' "$sigtec_backup_run/manifest.json" "$sigtec_backup_node")"
sigtec_restore_copy="$sigtec_backup_run/$sigtec_backup_node/physical-review"
test ! -e "$sigtec_restore_copy"
# Continuar únicamente si el destino no existe.
cp -a "$sigtec_backup_run/$sigtec_backup_node/physical/data" "$sigtec_restore_copy"
docker run -d --pull never --name sig-tec-ops-physical-review --network none \
  --mount "type=bind,source=$(realpath "$sigtec_restore_copy"),target=/var/lib/postgresql/data" \
  "$sigtec_backup_image" postgres -c listen_addresses= \
  -c max_prepared_transactions=10 -c archive_mode=off
docker exec sig-tec-ops-physical-review pg_isready -U postgres -d sig_tec
docker exec sig-tec-ops-physical-review psql -U postgres -d sig_tec -c '\dt ops.*'
```

Esperar a que el servidor esté listo antes de consultar. Su arranque reproduce
el WAL incluido para alcanzar el estado consistente del respaldo, sin objetivo
temporal, sin archivado y sin reincorporarlo a la red. La imagen ajustará el
propietario de la copia nueva para el usuario PostgreSQL. Conservar las
decisiones y transacciones preparadas que pudiera contener el clúster; no
resolverlas sin reconciliar ambos participantes. Al terminar, detener y retirar
únicamente ese contenedor de inspección:

```sh
docker stop sig-tec-ops-physical-review
docker rm sig-tec-ops-physical-review
```

No montar volúmenes de los nodos actuales en ese contenedor ni reutilizar la
copia modificada como respaldo original. No se ejecutó este procedimiento
físico durante la validación actual.

## Alcance y resultados

Los respaldos de los dos nodos son independientes, no un corte distribuido
coordinado. `pg_dump` incluye datos confirmados y no reproduce transacciones
preparadas; el físico conserva el estado del clúster y requiere reconciliación
de operaciones distribuidas si se restaura posteriormente. Los scripts no
confirman ni abortan transacciones de aplicación. Comparan datos, GID preparados
y estado de los contenedores antes y después; si hay actividad concurrente que
cambia esos valores, informan el cambio sin modificarlo ni descartarlo.

La ejecución registrada en [backup-results.json](backup-results.json) restauró
las solicitudes, decisiones, auditorías y edificios, además de las tablas de
extensiones. No hay aún geometrías en la tabla mínima `cartago.edificios`, por
lo que no se afirma haber probado la restauración de geometrías del modelo
completo. No se implementan archivado WAL, PITR, reincorporación ni políticas
automáticas de retención/borrado.

Referencias: [pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html),
[pg_basebackup](https://www.postgresql.org/docs/17/app-pgbasebackup.html) y
[pg_verifybackup](https://www.postgresql.org/docs/17/app-pgverifybackup.html).
