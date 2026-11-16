# Integración de la base, QGIS y operaciones

Esta rama reúne la base de Joseph, el complemento de Joyce y el módulo de
operaciones de Armando para probarlos sobre **las mismas seis bases**. Los
procedimientos de prueba usan un proyecto Compose nuevo llamado
`sig-tec-integracion`; no se ejecutaron sobre los volúmenes de la instalación
personal de Joseph.

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

## Secuencia propuesta para fusionar los PR

1. Fusionar #1 en `main` con un merge commit. Cambiar la base de #3 a `main`
   y fusionarlo también con un merge commit.
2. Revisar y fusionar #2 (Joyce) y #4 (Armando) en `main`, conservando sus
   commits. #4 permanece en borrador hasta recibir el visto bueno de Joseph.
3. Cambiar la base de #5 a `main`, revisar que el diff solo contenga la
   integración propia de Joseph y fusionarlo. #5 también sigue en borrador.

#5 ya incluye como ancestros los commits de Joyce y Armando que están en #2 y
#4. Los merge commits permiten que Git reconozca esos cambios cuando se
fusionen sus PR individuales. Si el equipo elige *squash* o *rebase* para
ellos, habrá que reconstruir y revisar el diff de #5 antes de fusionarlo. Los
PR actuales no tienen comprobaciones CI ni revisiones aprobadas en GitHub; las
pruebas locales documentadas aquí son la evidencia disponible.

## Instalación existente de Joseph

El proyecto Compose de la carpeta original es `iiiproyectobasesii` y sus seis
volúmenes de datos llevan ese prefijo. `ops/runtime.py` lo acepta
explícitamente. **Cambiar el nombre del proyecto Compose crearía otros
volúmenes vacíos**, así que antes de reiniciar esa instalación se revisarán
el nombre real, los montajes y los respaldos existentes. Para esa instalación,
el JSON local debe usar `"project": "iiiproyectobasesii"` y el mismo archivo
`.env` que utiliza la base actual. No usar el proyecto de prueba para operar
sobre sus datos.

La actualización debe ejecutarse desde un checkout estable de `main` con #5
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

La actualización integrada sobre esos datos queda pendiente de fusionar las
ramas revisadas. Al aplicarla, conservar el nombre de proyecto
`iiiproyectobasesii` y el `.env` original; comprobar que los seis montajes de
PGDATA apuntan a los mismos volúmenes antes de recrear contenedores. Después
de activar WAL, publicar estilos e instalar `ops`, generar un respaldo físico
nuevo: las copias previas no son la base de un PITR con el archivado futuro.

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
