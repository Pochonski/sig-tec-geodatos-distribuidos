# Archivado WAL: Central y Cartago

Actualización: el mismo archivador se validó en los seis nodos y en el reemplazo
de Cartago (timeline nuevo). Ver [INTEGRACION.md](INTEGRACION.md) y
[wal-sig-tec-rejoin-lab-results.json](wal-sig-tec-rejoin-lab-results.json).
El procedimiento siguiente describe el perfil aislado original.

Esta etapa habilita y comprueba el archivado de PostgreSQL 17, sin restaurar
WAL, implementar PITR ni reincorporar nodos. Los respaldos anteriores no se
modifican ni se usan como destinos. Configuración en `compose.yaml`:

```text
archive_mode=on
archive_command=/bin/sh /opt/sig-tec-ops/archive-wal.sh "%p" "%f" /wal-archive
max_prepared_transactions=10
```

Se conserva `wal_level=replica`, suficiente para archivar. Los scripts se montan
en solo lectura. `start-postgres.sh` exige el montaje de `/wal-archive`, asigna
su directorio raíz a `postgres` con modo `0700` y delega en el entrypoint oficial.
No cambia permisos ni contenido de PGDATA o de respaldos.

| Nodo | PGDATA conservado | Volumen persistente de archivo |
| --- | --- | --- |
| Central | `sig-tec-ops_central_data` | `sig-tec-ops_central_wal` |
| Cartago | `sig-tec-ops_cartago_data` | `sig-tec-ops_cartago_wal` |

Ambos ven su volumen propio como `/wal-archive`. Aunque coincidan los nombres
de segmento, los archivos no se mezclan. Son volúmenes diferentes de PGDATA,
pero en esta demostración comparten el disco físico del anfitrión: no constituyen
protección ante pérdida de ese disco. No se publican como archivos en Git.

## Aplicación vigilada

Con las dependencias Python ya instaladas y `ops/.env` existente, desde la raíz:

```sh
ops/.venv/bin/python -B ops/wal.py preflight
python3 -B ops/test_archive_wal.py
ops/.venv/bin/python -B ops/test_wal_inventory.py
ops/.venv/bin/python -B ops/wal.py apply
```

Trabajar en una ventana sin otros coordinadores ni ediciones. El preflight exige
la rama `armando/operaciones`, ambas bases activas, al menos 5 GiB y 10% libre
tanto en `ops/` como en el filesystem Docker, imagen local idéntica a la que
ejecutan los nodos, PGDATA esperado y PostgreSQL 17. Rechaza cualquier GID
preparado, sesiones del coordinador, solicitudes sin decisión, decisiones COMMIT
sin auditoría/marcador coincidentes, ABORT con efectos aplicados o marcadores
huérfanos. Ante un rechazo, detenerse y revisar: no recupera operaciones desconocidas.

Si los contenedores existentes estaban detenidos con salida normal, primero
iniciarlos con `docker start sig-tec-ops-central-1 sig-tec-ops-cartago-1` y
consultar su estado con la configuración anterior. No ejecutar `apply` si no se
puede consultar ambas bases o hay indicios de fallo de disco, OOM o corrupción.

`apply` valida Compose sin imprimir la configuración resuelta y repite el
preflight justo antes de `up --no-deps --pull never --wait central cartago`.
Recrea exclusivamente esos dos contenedores para agregar los montajes y activar
`archive_mode`; conserva y comprueba los nombres de sus volúmenes de datos.
Compara hashes de todas las tablas antes/después y el estado de otros contenedores.
No utiliza `down`, `down -v`, `prune` ni elimina volúmenes.

La evidencia previa privada queda en `ops/.wal-state.json`, modo `0600`, excluida
de Git; conservarla durante esta validación. Incluye hashes por registro y el
inventario anterior, no contraseñas. No volver a ejecutar `apply` para sobrescribir
la evidencia de un fallo: primero inspeccionar y reconciliar lo ocurrido.

## Publicación segura de segmentos

`archive-wal.sh` recibe origen, nombre y directorio. Acepta nombres PostgreSQL de
segmento, historial y respaldo; rechaza rutas o archivos de origen ausentes,
vacíos o simbólicos. En el volumen destino:

1. Si el nombre ya existe, solo acepta un archivo regular idéntico según `cmp`.
2. Copia a un temporal privado en el mismo filesystem y fuerza su persistencia.
3. Publica mediante un enlace duro atómico `ln -T`, que nunca reemplaza destinos.
4. Si otro publicador ganó la carrera, vuelve a comparar el contenido.
5. Retira solo su temporal y sincroniza el filesystem antes de devolver éxito.

Usa herramientas GNU presentes en la imagen y `sync -f` (syncfs en Linux).
Código `0`: copia duradera o reintento idéntico; `1`: fallo de E/S, conflicto o
tipo de archivo inválido; `64`: argumentos o nombre inválidos. Nunca borra un
segmento publicado. Una caída puede dejar un temporal oculto, pero no publica
copias parciales ni autoriza reciclar el WAL sin éxito.

## Verificar y forzar un segmento

```sh
ops/.venv/bin/python -B ops/wal.py verify
ops/.venv/bin/python -B ops/wal.py check-preserved
```

`verify` comprueba los parámetros y `pg_stat_archiver`, emite un mensaje WAL
no transaccional sin cambiar tablas y ejecuta `pg_switch_wal()` una vez por nodo.
Espera hasta 90 segundos y exige que el archivo sea legible por `postgres`, mida
`wal_segment_size`, avance `archived_count` y `pg_waldump` pueda leer un registro.
Registra SHA-256, volumen, segmento y estadísticas. Cualquier aumento de
`failed_count` o reinicio de estadísticas desde el preflight detiene la validación.

Consultas manuales, usando únicamente el socket local de los contenedores:

```sh
docker exec sig-tec-ops-central-1 psql -X -U postgres -d sig_tec \
  -c 'SHOW archive_mode' -c 'SHOW archive_command' \
  -c 'SHOW max_prepared_transactions' -c 'TABLE pg_stat_archiver'
docker exec sig-tec-ops-cartago-1 psql -X -U postgres -d sig_tec \
  -c 'SHOW archive_mode' -c 'SHOW archive_command' \
  -c 'SHOW max_prepared_transactions' -c 'TABLE pg_stat_archiver'
docker exec -u postgres sig-tec-ops-central-1 ls -l /wal-archive
docker exec -u postgres sig-tec-ops-cartago-1 ls -l /wal-archive
```

Para un cambio manual controlado de segmento, solo tras pasar el preflight:
`SELECT pg_switch_wal();`. Sin actividad desde el último cambio, puede no generar
un segmento nuevo; por eso `verify` emite primero un mensaje WAL.

## Pruebas 2PC y conservación

Después de confirmar archivado correcto y ausencia de operaciones pendientes:

```sh
ops/.venv/bin/python -B ops/test_rename.py
ops/.venv/bin/python -B ops/test_recovery.py
ops/.venv/bin/python -B ops/wal.py check-preserved
ops/.venv/bin/python -B ops/wal.py verify
```

Las pruebas usan sus edificios y UUID nuevos. `check-preserved` exige que cada
registro anterior de edificios, solicitudes, decisiones, auditorías y marcadores
conserve su hash, y que no cambien los volúmenes PGDATA ni los demás contenedores.
No exige conteos totales idénticos después de las pruebas porque estas conservan
sus propios fixtures. No resuelve transacciones ajenas.

Resultados reproducibles y sin credenciales en [wal-results.json](wal-results.json):
dos rondas de archivado (antes y después de 2PC), volúmenes y hashes, parámetros,
estadísticas y registros protegidos. También se actualiza la evidencia propia
de recuperación en `recovery-results.json`. Se ejecutaron 5 pruebas de publicación,
1 de normalización de IDs Docker, 4 de renombrado y 9 de recuperación.

La aplicación inicial detectó un falso positivo en el inventario: se comparaban
IDs cortos de `docker ps -q` con IDs completos, incluyendo por error los nodos
objetivo entre los contenedores ajenos. Se detuvo la aplicación, se inspeccionaron
en solo lectura todos los contenedores y los datos, y se confirmó que no hubo
cambios ajenos. Se corrigió la comparación y únicamente esa parte del estado
privado, conservando la evidencia original de datos y volúmenes. La prueba de
regresión cubre esta situación. No fue necesario reaplicar la configuración.

El archivo crece sin limpieza automática. Revisar periódicamente espacio libre,
`failed_count`, tiempos del último archivado y acumulación en `pg_wal`; no borrar
WAL de PGDATA ni del archivo para resolver falta de espacio sin una política de
retención acordada. Si el archivador falla, PostgreSQL retiene WAL y puede llenar
el disco. Esta etapa no promete continuidad WAL para los respaldos físicos que
se generaron antes de habilitar el archivo; se necesitará un nuevo respaldo base
para PITR. La prueba posterior con un respaldo nuevo se documenta en [PITR.md](PITR.md);
no reutiliza los respaldos anteriores como destinos de escritura.

Referencia: [archivado continuo de PostgreSQL 17](https://www.postgresql.org/docs/17/continuous-archiving.html).
