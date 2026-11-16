# Integración de la base, QGIS y operaciones

El repositorio reúne la base de Joseph, el complemento de Joyce y el módulo de
operaciones de Armando para probarlos sobre **las mismas seis bases**. La
primera prueba conjunta usó un proyecto Compose nuevo llamado
`sig-tec-integracion`. Después se aplicó la integración a la instalación
existente de Joseph, con el proyecto `iiiproyectobasesii` y sus volúmenes
originales.

## Orden de arranque en un proyecto de prueba nuevo

Usar PowerShell desde la raíz del repositorio, Docker Desktop con contenedores
Linux, Python 3.12 o posterior y QGIS 3.44. Crear `.env` a partir de
`.env.example` con siete contraseñas alfanuméricas distintas, de 24 caracteres
o más. Los puertos `55430` a `55435` deben estar libres. El nombre
`sig-tec-integracion` identifica únicamente este proyecto de prueba.

```powershell
Copy-Item .env.example .env
notepad .env
python -m pip install -r ops/requirements.txt
$project = 'sig-tec-integracion'
docker compose -p $project up -d --wait
docker compose -p $project run --rm bootstrap
```

El bootstrap crea primero las tablas geográficas, vistas, cuentas y
suscripciones. Después se instalan las tablas y los permisos de 2PC. Las
migraciones integradas no crean la tabla mínima ni la semilla aislada de
`ops/`.

```powershell
Copy-Item .env ops/.env.integrated
Copy-Item ops/runtime.integrated.example.json ops/runtime.integrated.json
notepad ops/runtime.integrated.json
```

En el JSON local, poner `"project": "sig-tec-integracion"`. Conservar los seis
nodos, puertos, variables de contraseña y `archive_command` del ejemplo.
Ambos archivos locales quedan ignorados por Git. `migrate.py` genera en
`ops/.env.integrated` una contraseña CLI independiente por nodo si falta.

```powershell
$env:SIGTEC_OPS_CONFIG = (Resolve-Path ops/runtime.integrated.json).Path
python -B ops/migrate.py
python -B db/publicar_estilos.py --project $project
```

El publicador transmite el SQL de Joyce como bytes UTF-8 al central; no pasa
contraseñas por la línea de comandos. `public.layer_styles` se replica a los
cinco campus. Para una instalación ya iniciada, repetir bootstrap, migraciones
y publicación conserva datos y evita estilos `SIG-TEC` duplicados.

## Pruebas conjuntas

```powershell
docker compose -p $project run --rm bootstrap /db/smoke.sh
$env:SIG_TEC_ENTORNO = 'integracion'
$env:SIG_TEC_PROYECTO_COMPOSE = $project
$env:SIG_TEC_ENV = (Resolve-Path .env).Path
python -B -m unittest discover -s qgis/pruebas -v
$env:QT_QPA_PLATFORM = 'offscreen'
& 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat' qgis/pruebas/test_qgis.py
& 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat' db/qgis_smoke.py
python -B ops/integration_checks.py
python -B ops/test_rename.py
python -B ops/test_recovery.py
python -B ops/wal.py capture
python -B ops/wal.py verify
python -B ops/backup.py create --node all
python -B ops/backup.py restore-test ops/backups/<ID>
python -B ops/pitr.py run
```

Sustituir `<ID>` por el directorio que imprimió `backup.py create`.
En un perfil integrado, `backup.py` conserva el resumen versionado del
laboratorio `ops/backup-results.json`: la ejecución nueva queda en el
`manifest.json` privado de `ops/backups/<ID>/`. El informe WAL del proyecto
original también queda fuera de Git.
Si se crea por adelantado para fijar permisos, el informe debe contener JSON
válido, por ejemplo `{"verifications":[]}`; un archivo vacío hace fallar
`wal.py verify` después de comprobar los segmentos.
`integration_checks.py` acepta escrituras solo en los proyectos de laboratorio
`sig-tec-integracion` y `sig-tec-rejoin-lab`. `wal.py` admite la rama
`joseph/integracion-final` solo con el proyecto descartable
`sig-tec-integracion`; después de fusionar, admite `main`. PITR crea una copia
aislada de Cartago y comprueba el punto de restauración sin reincorporarla.
El ensayo de reincorporación con un único propietario está en
[REINCORPORACION.md](../ops/REINCORPORACION.md) y se ejecuta solo en el
laboratorio `sig-tec-rejoin-lab`.

QGIS Desktop requiere que el complemento `qgis/sig_tec` del repositorio
integrado esté instalado en el perfil activo. La prueba automatizada con
`python-qgis-ltr.bat` carga directamente esta versión y verifica inicio de
sesión, estilos, ocho capas, CRUD, edición ajena y cambios de sesión.

## Integración de los PR

El 16 de noviembre de 2026 se fusionaron en `main` los PR #1, #3, #2, #4 y
#5, en ese orden, con merge commits. La base de #3 y #5 se cambió a `main`
antes de fusionarlos. #5 incluyó únicamente los cambios propios de la
integración después de incorporar `main` a su rama. El resultado integrado
quedó en `dc956c9`; los resultados locales se indican más abajo.

## Instalación existente de Joseph

El proyecto Compose de la carpeta original es `iiiproyectobasesii` y sus seis
volúmenes de datos llevan ese prefijo. `ops/runtime.py` lo acepta
explícitamente. **Cambiar el nombre del proyecto Compose crearía otros
volúmenes vacíos**, así que antes de reiniciar esa instalación se revisarán
el nombre real, los montajes y los respaldos existentes. Para esa instalación,
el JSON local debe usar `"project": "iiiproyectobasesii"` y el mismo archivo
`.env` que utiliza la base actual. No usar el proyecto de prueba para operar
sobre sus datos.

La actualización se ejecutó desde un checkout estable de `main` con #5
fusionado. El Compose integrado monta `./ops/start-postgres.sh` y
`./ops/archive-wal.sh` en los seis contenedores: eliminar un worktree temporal
desde el que se hayan creado dejaría esos montajes sin sus archivos. La
herramienta WAL también exige `main` para operar sobre `iiiproyectobasesii`.

El Compose integrado conserva los seis volúmenes PGDATA y los parámetros de
replicación; añade un volumen WAL persistente por nodo. Activar el archivado
reinicia los contenedores. Para un PITR futuro se debe generar un respaldo
físico **después** de activar el archivado y conservar los segmentos WAL
necesarios. La retención de WAL, el corte de un nodo y la resolución de cambios
de QGIS posteriores al punto recuperado requieren una decisión antes de
reincorporar una copia. El ensayo de laboratorio no sustituye ese plan.
No usar `docker compose down -v` sobre esta instalación. Volver al Compose
anterior solo desactiva los parámetros nuevos; no deshace migraciones SQL. Una
reversión completa exige detener los seis nodos y restaurar juntas las seis
copias previas, antes de reabrir conexiones de QGIS o replicación.

### Auditoría previa del 16 de noviembre de 2026

Se comprobó la instalación original sin recrear sus contenedores. El proyecto
Compose es `iiiproyectobasesii`, con seis volúmenes `*_data` montados en
`/var/lib/postgresql/data` y los puertos `55430` a `55435` publicados solo en
`127.0.0.1`. Los seis nodos usan PostgreSQL 17.11, `wal_level=logical` y
`max_prepared_transactions=10`. Al iniciarlos con `docker compose start`, cada
vista `sig.*` mostró cinco filas. El central tenía cinco suscripciones activas
y cada campus una; todas sus tablas estaban listas, los slots estaban activos
y no había transacciones preparadas pendientes. Las cinco cuentas de prueba
funcionaron tanto en el central como en su campus. Se volvieron a detener los
contenedores al terminar la revisión.

En los seis nodos, `archive_mode` estaba apagado, `public.layer_styles` no
tenía filas y el esquema `ops` aún no existía. Antes de iniciar los nodos se
hicieron seis copias comprimidas de los volúmenes detenidos en
`backups/preintegracion-2026-11-16/`, excluido de Git. Cada archivo pasó la
lectura completa de `tar`, tiene SHA-256 registrado en `manifest.json` y su
PGDATA reportó un apagado limpio. Se restringió la ACL del `.env` original a
Joseph, SYSTEM y Administradores, sin mostrar ni cambiar las contraseñas. La
misma restricción se aplicó a los archivos de respaldo y su manifiesto.

Las copias previas siguen disponibles para una reversión completa. La
actualización conservó el nombre de proyecto `iiiproyectobasesii` y el `.env`
original; los seis montajes de PGDATA se comprobaron antes y después de
recrear los contenedores. Las copias previas al archivado no sirven como base
para un PITR con el WAL nuevo; por eso se generaron respaldos físicos nuevos.

### Despliegue de la instalación existente el 16 de noviembre de 2026

Se ejecutaron `docker compose -p iiiproyectobasesii up -d --wait` y el
bootstrap sobre los seis volúmenes originales, sin `down -v`. Se añadieron
seis volúmenes WAL persistentes y quedó `archive_mode=on` en cada nodo.
Bootstrap reutilizó las diez suscripciones y sus slots; sus tablas quedaron
listas. Se aplicó `ops/migrate.py` y se publicaron ocho
estilos predeterminados, visibles en cada nodo. Cada una de las ocho vistas
`sig.*` mostró cinco objetos. El edificio de Cartago editado previamente en
QGIS conservó su nombre en los seis nodos.

`ops/wal.py verify` archivó y leyó un segmento de 16 MiB en cada nodo, sin
aumento de `failed_count`. `ops/backup.py create --node all` generó seis
respaldos lógicos y seis físicos en el directorio privado
`ops/backups/20261116T211337Z-560cfd46/`. Una ejecución independiente de
`backup.py verify` aprobó los seis. `backup.py restore-test` restauró cada
respaldo lógico en un contenedor nuevo sin red y comparó tablas, conteos y
hashes de registros. El manifiesto registró `status=complete`, seis nodos y
`source_data_prepared_containers_unchanged=true`.

El `db/qgis_smoke.py` de QGIS 3.44.15 abrió las 40 vistas, verificó EPSG:8908,
geometrías válidas y 40 IDs únicos, y probó altas, cambios de atributos y
geometría, bajas, réplica y rechazo de escrituras ajenas en las ocho capas.
Tras limpiar los objetos temporales, volvió a comprobar el inventario.
`qgis/pruebas/test_qgis.py` aprobó siete casos del complemento; omitió el caso
de cuenta sin campus, que no se aprovisionó en esta instalación. Finalmente,
`ops/wal.py check-preserved` confirmó que las filas protegidas, los montajes
de los volúmenes originales y los demás contenedores se conservaron, y que no
había 2PC pendiente. Los seis
servicios quedaron `healthy` y el árbol Git permaneció limpio.

Para repetir la validación PyQGIS sobre esta instalación, usar el proyecto
Compose y el archivo de entorno originales:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:SIG_TEC_ENTORNO = 'integracion'
$env:SIG_TEC_PROYECTO_COMPOSE = 'iiiproyectobasesii'
$env:SIG_TEC_ENV = (Resolve-Path .env).Path
& 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat' db/qgis_smoke.py
& 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat' qgis/pruebas/test_qgis.py
```

El perfil QGIS `sig_tec_main` contiene una copia comprobada de los 15 archivos
del complemento de `main`. Se abre con
`C:\Program Files\QGIS 3.44.15\bin\qgis-ltr.bat --profile sig_tec_main`.
Allí aparece **Database > SIG-TEC > Iniciar sesión** y el diálogo propone
`127.0.0.1:55430`, base `sig_tec`. El perfil `default` conserva una unión a un
directorio temporal de la prueba anterior; usar `sig_tec_main` para la
demostración. La entrada de credenciales en el diálogo queda para Joseph.

## Resultado de la prueba integrada

En Windows con QGIS 3.44.15 y volúmenes nuevos se verificó:

- Bootstrap y prueba SQL: 40 filas ficticias, diez suscripciones y CRUD de
  ocho capas en los cinco campus, incluidos permisos y `ROLLBACK`.
- Ocho estilos publicados; la prueba de estilos en base confirmó una sola
  fila predeterminada por vista. PyQGIS pasó siete casos y omitió únicamente
  la cuenta sin campus, que no existe en la base integrada.
- 2PC: renombrado e idempotencia en los cinco campus, una auditoría por UUID,
  geometría intacta y convergencia en los seis nodos; cuatro pruebas de CLI y
  nueve escenarios de recuperación aprobados.
- WAL: los seis nodos archivaron un segmento legible sin aumentar
  `failed_count`. Se generaron y verificaron seis respaldos lógicos y físicos;
  las seis restauraciones lógicas aisladas coincidieron en tablas, conteos y
  hashes. PITR recuperó en una copia aislada un edificio eliminado después del
  punto nombrado, con atributos y geometría iguales.
- Una segunda ejecución de bootstrap y migraciones conservó todas las tablas,
  auditorías, estilos, suscripciones y transacciones preparadas de los seis nodos.

La prueba se hizo en `sig-tec-integracion`. Los archivos privados de prueba,
respaldos y WAL permanecen fuera del historial de Git.

### Comprobación visual de QGIS Desktop

En un perfil temporal de QGIS 3.44.15 se abrió un proyecto con las ocho vistas
de Cartago y las ocho de San Carlos. Las 16 capas fueron válidas, tenían
EPSG:8908 y cargaron el estilo predeterminado desde el central. En el mapa
aparecieron los símbolos y etiquetas; en la tabla `Edificios` de Cartago se
vieron las cinco filas, una por campus. El complemento integrado se activó en
ese perfil, apareció en **Database > SIG-TEC** y abrió su diálogo de acceso.

Desde la tabla de QGIS, con la cuenta de Cartago conectada directamente a su
nodo, se cambió el nombre de su edificio ficticio. El central y San Carlos
recibieron el cambio; luego se restauró el nombre original y ambos nodos
convergieron. Un intento de editar la fila de San José desde Cartago no se
guardó, y los tres nodos consultados conservaron el dato original. La sesión
visual del complemento no introdujo credenciales en su diálogo; el flujo de
inicio de sesión, carga, estilos y edición del complemento se verificó además
con `python-qgis-ltr.bat`: siete pruebas aprobadas y una omitida porque la
instalación integrada no tiene cuenta sin campus.
