# Ejecución integrada y respuesta a la revisión del PR #4

Se conserva el protocolo 2PC original. Los cambios principales son UTF-8
explícito, un inventario de conexiones compartido y la validación sobre una
copia del modelo de seis nodos de Joseph, fijado a
`f3e1f91e1e61e2f293fac4ba50de209cc0af65ea`.

## Configuración de los dos entornos

Sin `SIGTEC_OPS_CONFIG`, los módulos siguen usando `sig-tec-ops`, `ops/.env`
y los puertos `57430/57431`. No se cambió ni se inició ese entorno durante el
ensayo integrado; sus volúmenes se conservaron.

Para otra instalación, copiar `runtime.integrated.example.json` a un archivo
local, revisar el nombre real del proyecto Compose, hosts y puertos y crear
`ops/.env.integrated` privado. El ejemplo usa `55430`–`55435`. El inventario
solo contiene nombres de variables de contraseña; no acepta contraseñas literales.
La variable `SIGTEC_ADMIN_PASSWORD` debe coincidir con la administración existente
de Joseph; no cambiarla para esta integración. Puede suministrarse por entorno
en vez de duplicarla en el archivo. `migrate.py` genera contraseñas locales
`OPS_<NODO>_CLI_PASSWORD` cuando faltan y solo escribe credenciales dentro de `ops/`.

En Parrot, guardar archivos locales de credenciales con `chmod 600` y ejecutar:

```sh
export SIGTEC_OPS_CONFIG=ops/runtime.integrated.example.json
ops/.venv/bin/python -B ops/migrate.py
ops/.venv/bin/python -B ops/rename.py UUID CAMPUS_ID EDIFICIO_ID 'José Ñandú 🏢'
ops/.venv/bin/python -B ops/recover.py UUID
ops/.venv/bin/python -B ops/backup.py create --node all
```

**Revisar y aprobar el inventario antes de ejecutar sobre una instalación real.**
Los comandos anteriores son instrucciones, no se ejecutaron contra la base
personal de Joseph. Para el laboratorio probado se selecciona en su lugar
`ops/rejoin-lab/runtime.json`; después de la reincorporación ese inventario
contiene el puerto del reemplazo (`58436`) y sus montajes explícitos.
Cambiar el inventario antes de iniciar cada proceso Python; no editarlo mientras
una CLI o respaldo está en curso.

`runtime.py` resuelve proyecto, nodos, endpoints y variables de credenciales.
`migrate.py` descubre exclusivamente contenedores activos con ese proyecto y
servicio. `rename.py`, `recover.py` y `backup.py` utilizan el mismo inventario;
los cinco campus conservan sus esquemas y GID originales. Los respaldos se
separan por nodo y verifican la imagen exacta de cada fuente.

### Migraciones y permisos

En perfil integrado, las tablas geográficas deben existir previamente. Se aplican:

- `001_common.sql` a los seis nodos y `002_central.sql` al central.
- `004_participant.sql`, parametrizado por campus, a los cinco propietarios.

No se aplica `003_cartago.sql` ni la semilla mínima al perfil integrado.
No se sustituyen tablas, geometrías, secuencias, vistas ni roles de Joseph.
El rol CLI mantiene SELECT de `id/campus_id/nombre`, UPDATE solo de `nombre`
y los permisos de lectura/inserción necesarios en `ops`. No obtiene permisos
para modificar geometría, IDs, campus, borrar edificios ni administrar replicación.
Las publicaciones de Joseph siguen publicando sus tablas geográficas explícitas;
no se incorporan auditorías, solicitudes o marcadores al flujo lógico.

### UTF-8

Se corrigieron lecturas/escrituras de texto que dependían de la codificación
regional. El archivo de entorno admite UTF-8 con BOM y CRLF. La entrada de
`migrate.sql()` se codifica a bytes UTF-8, se fija `PGCLIENTENCODING=UTF8` para
psql y se decodifica su salida explícitamente. Una salida UTF-8 inválida se
rechaza, no se sustituye silenciosamente. Las herramientas de texto usan UTF-8
explícito; los dumps, tar y COPY BINARY se mantienen como bytes.

`.gitattributes` fija LF para shell/SQL/Python. No se necesita instalar Python
dentro de los contenedores PostgreSQL. Los diagnósticos de SQL no imprimen
contraseñas ni sentencias con secretos.

## Laboratorio independiente probado

`lab.py` materializa una copia sin cambios de `compose.yaml` y `db/` de Joseph
dentro de `ops/rejoin-lab/`, excluido de Git. Genera credenciales alfanuméricas
locales diferentes de las existentes y valida puertos, proyecto y nombres de
volúmenes antes de iniciar servicios nuevos:

```sh
ops/.venv/bin/python -B ops/lab.py prepare
ops/.venv/bin/python -B ops/lab.py validate
ops/.venv/bin/python -B ops/lab.py start
ops/.venv/bin/python -B ops/lab.py bootstrap
export SIGTEC_OPS_CONFIG=ops/rejoin-lab/runtime.json
ops/.venv/bin/python -B ops/migrate.py
```

No repetir `prepare` sobre un directorio o proyecto existente: se rechaza.
No hay comando de reset, prune o borrado de volúmenes. El bootstrap se usa solo
en las seis bases nuevas; no es un procedimiento de reparación de producción.

Proyecto: `sig-tec-rejoin-lab`. Puertos iniciales: `58430`–`58435` en loopback.
La red interna conserva la separación de la fuente; una segunda red de control
propia del laboratorio permite la publicación de puertos y la administración
desde el anfitrión. No se comparte ninguna red ni volumen con wger o sig-tec-ops.
El primer diseño bloqueaba tráfico entre pares en la red de control y Docker
podía resolver nombres por esa interfaz; la prueba de convergencia detectó el
fallo. Se corrigió únicamente el laboratorio y se repitieron las pruebas.
No se publica evidencia de ese primer intento como integración aprobada.

El overlay conserva `wal_level=logical`, slots/senders/workers de Joseph y
`max_prepared_transactions=10`; añade archivado WAL persistente por nodo.
Los scripts existentes de archivo se reutilizan sin sobrescribir WAL diferente.

## WAL, respaldos y PITR del modelo real

```sh
ops/.venv/bin/python -B ops/wal.py capture
ops/.venv/bin/python -B ops/wal.py verify
ops/.venv/bin/python -B ops/backup.py create
ops/.venv/bin/python -B ops/backup.py restore-test ops/backups/ID
ops/.venv/bin/python -B ops/pitr.py run
```

`capture` guarda una referencia de comprobación sin recrear nodos; `apply` no
recrea una instalación integrada. Su configuración debe incorporarse mediante
un Compose revisado, como el overlay del laboratorio. `verify` comprueba los
seis archivos y `pg_stat_archiver` por nodo. Después de un cambio de topología
aprobado, capturar una nueva referencia, conservando el informe anterior.

PITR reconoce el perfil integrado: el fixture usa la vista real `sig.edificios`,
la secuencia del propietario, código, área, pisos y geometría Polygon EPSG:8908.
Comprueba todos sus atributos y EWKB después de recuperar.
La copia conserva los límites de `max_connections`, `max_worker_processes`,
`max_wal_senders`, `max_prepared_transactions`, `max_locks_per_transaction` y
`max_replication_slots` del primario. Este ajuste resolvió un fallo real del
primer intento: PostgreSQL rechazaba recuperar con 8 workers cuando el primario
tenía 48. Ese intento, su respaldo y logs quedaron conservados.

Durante PITR, `max_logical_replication_workers=0`, sin red ni puertos y WAL en
solo lectura impiden que las suscripciones copiadas se comuniquen con fuentes.
Se verifica la pausa exacta en el punto nombrado por SQL y logs antes de
reanudar hasta completar recovery. `--keep-copy` conserva la copia activa pero
aislada para el ensayo siguiente; sin esa opción se mantiene el cierre y
retirada del contenedor temporal de la prueba original.

## Reincorporación real ensayada, solo en el laboratorio

```sh
ops/.venv/bin/python -B ops/rejoin_lab.py --approve-lab-replacement
ops/.venv/bin/python -B ops/rejoin_lab.py --verify-only
```

El primer comando modifica exclusivamente un laboratorio nuevo conocido y exige
aprobación explícita. No ejecutarlo en producción. Es un ensayo de una sola
sustitución, no un sistema automático de failover ni un reset repetible de
volúmenes existentes. Después de la sustitución, `lab.py start/bootstrap` se
bloquean para impedir reactivar accidentalmente al propietario anterior.

Flujo ejecutado:

1. PITR real y copia sin red. Deshabilitar en esa copia la suscripción heredada.
2. Generar cambios posteriores controlados: COMMIT 2PC de un fixture de Cartago,
   un alta de San José y una operación realmente preparada que se recupera con
   ABORT. No se resuelven transacciones desconocidas.
3. Esperar convergencia y guardar un corte consistente conocido de las 40 tablas,
   estilos, marcadores y posiciones de secuencia. Conservar exportaciones
   COPY BINARY y hashes en un journal privado.
4. Deshabilitar el canal antiguo del central y **detener solo el Cartago del
   laboratorio**, antes de dar red al reemplazo. Mantener su volumen intacto.
5. Reconciliar la copia con los donantes autorizados del corte: ocho tablas
   propias y marcadores desde el propietario anterior, 32 copias remotas y
   estilos desde el central. El único borrado permitido es el fixture propio
   creado y eliminado para esta prueba PITR; cualquier otro borrado bloquea el
   proceso antes de modificar esa tabla. Las exportaciones no se destruyen.
6. Comprobar igualdad completa de hashes y marcadores frente al corte. El
   marcador COMMIT posterior a PITR se obtiene del propietario verificado; no
   se inventa una auditoría ni se presenta como recuperación automática de una
   rama perdida. Una reincorporación real sin donante/historia autoritativa
   continúa bloqueada hasta una decisión explícita de reconciliación.
7. Avanzar la secuencia compartida por encima de todos los IDs de las ocho capas
   y del máximo emitido/reservado observado en el propietario congelado. Usar
   `is_called=false`, incremento 5 y clase de Cartago; comprobar el ID del
   siguiente alta y ausencia de colisiones.
8. Activar un único reemplazo con PGDATA propio y archivo WAL nuevo, endpoint
   `58436` y alias `cartago_recovered`. El original permanece detenido.
9. Crear slots y suscripciones **nuevos**, sin borrar los anteriores:
   `slot_central_cartago_rejoin` / `sub_central_cartago_rejoin` hacia el central;
   `slot_cartago_central_rejoin` / `sub_cartago_central_rejoin` hacia el reemplazo.
   Se usa `copy_data=false` únicamente porque se demostró igualdad con el corte
   congelado antes de crear los slots. No se reutilizan posiciones anteriores
   a PITR, no se truncan tablas ni se recopian esquemas ajenos.
10. Probar INSERT/UPDATE/DELETE de una fila propia nueva en los dos saltos,
    entrada desde San José, 2PC y reintento, cinco suscripciones activas en central,
    una por campus, todas las relaciones activas en `r` y cero GID pendientes.

Los canales antiguos permanecen deshabilitados; sus slots se conservan como
evidencia y pueden retener WAL. La elección de nombres canónicos, transición de
DNS/endpoints, presupuesto de retención y retirada posterior de esos canales
requieren revisión de Joseph antes de una operación real. **No habilitar el canal
antiguo ni arrancar el propietario detenido.**

La alternativa de copia inicial selectiva documentada en REINCORPORACION.md
sigue siendo necesaria si no puede demostrarse continuidad/igualdad con un corte.
Este ensayo no certifica esa alternativa ni autoriza vaciar 33 tablas a ciegas.

## Windows: preparado, ejecución real pendiente

No hubo acceso a Windows real en esta sesión. Ningún resultado Linux se etiqueta
como Windows. `windows-results.json` registra `pending`.

Requisitos: Windows, Python >=3.12, Git, Docker Desktop con contenedores Linux
y la imagen PostgreSQL/PostGIS fijada disponible. En PowerShell desde la raíz:

```powershell
py -3 -m venv ops/.venv-win
ops/.venv-win/Scripts/python.exe -m pip install --no-cache-dir -r ops/requirements.txt
& ./ops/test_windows.ps1
```

El runner exige Windows real, fuerza `PYTHONUTF8=0` y salida cp1252 para que
la prueba no dependa de activar modo UTF-8 global; verifica el protocolo por
bytes, BOM/CRLF y caracteres fuera de cp1252. Al terminar escribe evidencia
UTF-8 sin BOM con plataforma y versión de PowerShell.

Después de preparar un laboratorio independiente en Windows:

```powershell
$env:SIGTEC_OPS_CONFIG = (Resolve-Path ops/rejoin-lab/runtime.json).Path
ops/.venv-win/Scripts/python.exe -B ops/migrate.py
& ./ops/test_windows.ps1 -Integration -Config ops/rejoin-lab/runtime.json
```

Integration solo acepta `sig-tec-rejoin-lab`. Las credenciales locales deben
tener ACL restringida al operador. PITR/reincorporación y permisos del PGDATA
copiado en Docker Desktop necesitan validación real adicional en Windows; el
runner no afirma haberlos probado ni los ejecuta implícitamente.

## Evidencia y alcance

Ver `integration-validation.json` para el resumen de esta revisión;
`integrated-results.json` para cinco campus y Unicode; `recovery-results.json`
para interrupciones; `backup-results.json` para los seis respaldos y sus
restauraciones; `wal-sig-tec-rejoin-lab-results.json`, `pitr-results.json` y
`rejoin-execution-results.json` para archivo, punto alcanzado y sustitución.

Se conservan privados y fuera de Git: `.env`, `rejoin-lab/`, `.runtime-state/`,
backups, WAL, exportaciones COPY, PGDATA de recuperación y logs completos.
La copia PITR aprobada se utiliza como PGDATA del reemplazo de laboratorio;
para volver a recuperar el punto se debe preparar otra copia nueva del respaldo
inmutable, no reusar ese PGDATA ya reconciliado.

La validación de Joseph pendiente es sobre su instalación real: inventario de
conexiones y credenciales, incorporación del overlay WAL manteniendo parámetros
lógicos, aplicación de migraciones sin fixtures mínimos, política de
reconciliación de cambios no auditados de QGIS y aprobación del corte/IDs/slots.
No se hicieron merges ni se modificó `db/`, QGIS o el trabajo de sus ramas.
