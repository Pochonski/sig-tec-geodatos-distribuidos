# Guion y ensayo técnico de la demostración

Objetivo: **9 minutos y 20 segundos**, con 40 segundos de margen hasta el
máximo de 10 minutos. Entrega: **30 de noviembre de 2026, 8:00 a. m.**,
hora de Costa Rica. El reparto de voz propuesto es Joseph (arquitectura y
replicación), Joyce (QGIS) y Armando (2PC y recuperación).

Los pasos visuales y la caída del central se comprobaron el 27 de noviembre
en la instalación original. Las evidencias de 2PC, PITR y reincorporación
proceden del laboratorio `sig-tec-rejoin-lab`; indicar ese proyecto y las
fechas al mostrarlas. Este documento prepara la grabación: todavía no es un
registro de la lectura cronometrada de las tres voces. El 28 de noviembre se
exportó además un video con narración sintética de **8:34,905**, capturas
reales y evidencias históricas rotuladas. Sus archivos y comprobaciones están
en [entrega final](entrega.md). El presupuesto de esta exposición en vivo
sigue siendo 9:20.

## Orden y presupuesto de tiempo

| Tiempo | Voz | Pantalla y acción |
| --- | --- | --- |
| 0:00–0:45 | Joseph | Arquitectura: seis nodos, propiedad por campus y dos saltos de réplica. Mostrar los servicios saludables y la tabla de capas del diseño. |
| 0:45–3:00 | Joyce | Entrar con `demo_cartago`, mostrar ocho capas, estilos y EPSG:8908. Dedicar como máximo 15 segundos al mapa de referencia y volver a las capas editables. Editar el edificio propio, guardar y comprobar su valor. Intentar editar el edificio ajeno, mostrar el rechazo y descartar el intento. |
| 3:00–4:15 | Joseph | Mostrar el mismo ID y nombre en Cartago, central y San Carlos. Mostrar la caída del central: guardado local, nuevo ingreso rechazado, recuperación y convergencia. Restaurar el nombre original. |
| 4:15–6:15 | Armando | Renombrado administrativo y auditoría con un UUID. Mostrar los casos antes/después de la decisión duradera, auditoría única y cero transacciones preparadas pendientes. |
| 6:15–8:40 | Armando | Respaldos lógicos/físicos de los seis nodos. Punto de restauración, fila recuperada por PITR, aislamiento y comprobaciones de reincorporación. |
| 8:40–9:20 | Joseph | Estado final de los seis nodos, filas originales restauradas y ubicación del código, instrucciones y evidencias. Cierre y créditos. |

Preparar las ventanas antes de grabar y reservar las esperas largas para las
tomas de ejecución previas. Rotular los cortes y la evidencia del laboratorio
con su fecha; conservar el UUID y el ID visibles para seguir cada operación.

## Narración base

**Joseph, arquitectura.** «SIG-TEC reúne información geográfica de cinco
campus. Ejecutamos cinco bases operativas y un central, cada una con volumen
propio, PostgreSQL 17 y PostGIS 3.6. Cada campus publica sus ocho tablas; el
central recibe esos datos y distribuye a cada campus las copias de los otros
cuatro y los estilos. Las vistas reúnen datos propios y remotos. La edición
local se confirma en el campus y la réplica es asíncrona.»

**Joyce, QGIS.** «El complemento valida la cuenta en el central, obtiene su
campus y abre ocho vistas del nodo correspondiente. Cada objeto tiene un ID
global, campus y geometría. La secuencia compartida de cada campus avanza de
cinco en cinco. Usamos EPSG:8908 y transformamos los datos de entrada. Aquí
guardamos un cambio de un edificio de Cartago. La cuenta ve también edificios
ajenos, pero PostgreSQL rechaza su modificación. El permiso se aplica en la
base, incluso si se intenta escribir por SQL.»

**Joseph, caída y réplica.** «El mismo ID aparece con el nuevo valor en
Cartago, el central y San Carlos. Con el central detenido, una sesión ya
abierta puede guardar en su campus. Un nuevo inicio de sesión informa que el
central no está disponible. Cuando vuelve el servicio, los cambios pendientes
convergen y el acceso funciona de nuevo. Restauramos el dato original al
terminar la demostración.»

**Armando, 2PC.** «El coordinador recibe un UUID, el campus, el edificio y su
nuevo nombre. Prepara el cambio del campus y la auditoría central. Guarda la
decisión de commit en una transacción independiente y duradera antes de
resolver los participantes. Sin decisión de commit, la recuperación aborta;
con decisión confirmada, termina los commits pendientes. Los marcadores por
UUID hacen que un reintento conserve una sola auditoría. La réplica geográfica
se comprueba después de resolver ambas ramas.»

**Armando, recuperación.** «Los seis nodos tienen respaldo lógico y físico
verificado. Para PITR creamos un punto después del respaldo, eliminamos una
fila y archivamos los WAL necesarios. La copia aislada alcanzó el punto
nombrado y recuperó los atributos y la geometría. La reincorporación se ensayó
en laboratorio: se detuvo el propietario anterior, se reconciliaron datos y
operaciones, se adelantó la secuencia y se comprobó que solo quedara un
propietario activo y que la réplica funcionara en ambos sentidos.»

**Joseph, cierre.** «Terminamos con los seis nodos saludables, los datos de
prueba restaurados y ninguna transacción preparada pendiente. El repositorio
incluye el diseño, las instrucciones de arranque y las evidencias de
validación. La demostración usa datos ficticios.»

## Preparar y mostrar la instalación original

Ejecutar desde la raíz estable del repositorio, después de integrar los PR
#6, #7 y #8. Mantener el proyecto Compose `iiiproyectobasesii` y usar el perfil
QGIS validado `sig_tec_mapas_20261127`, con el proyecto local
`qgis/SIG-TEC-mapas-local.qgz`. El perfil anterior `sig_tec_main` quedó sin
responder durante la revisión de mapas; no cerrar su proceso sin comprobar
antes sus cambios. Cerrar del encuadre `.env` y los archivos locales de credenciales.
La contraseña se introduce manualmente y permanece oculta.

```powershell
docker compose -p iiiproyectobasesii up -d --wait
docker compose -p iiiproyectobasesii ps --format '{{.Service}}|{{.State}}|{{.Health}}'
Get-Content -Raw -Encoding utf8 db/demo_lectura.sql | docker compose -p iiiproyectobasesii exec -T central psql -v ON_ERROR_STOP=1 -P pager=off -U postgres -d sig_tec
```

La consulta usa una transacción de solo lectura. Se esperan cinco objetos por
capa, 40 IDs distintos, 40 geometrías correctas en SRID 8908, cinco campus,
ocho estilos predeterminados y cero transacciones preparadas. En el central
deben aparecer cinco suscripciones con 8/8 tablas listas; en cada campus,
una con 33/33. Los slots deben estar activos.

Para comparar el edificio durante una edición desde QGIS:

```powershell
foreach ($demoNodo in @('cartago', 'central', 'san_carlos')) {
    Write-Output $demoNodo
    docker compose -p iiiproyectobasesii exec -T $demoNodo psql -U postgres -d sig_tec -c 'SELECT id,campus_id,nombre FROM sig.edificios WHERE id=1'
}
```

Usar `id=1`, `campus_id=1`, como edificio propio y `id=3`, `campus_id=3`, como
ajeno. Guardar el nombre original antes de editarlo. Después del rechazo,
descartar el cambio pendiente en QGIS. Al terminar, restaurar el nombre propio
y comprobarlo en los tres nodos.

Para la toma de caída del central, conservar abierta la sesión de Cartago y
detener solo `central`. Guardar una edición propia en QGIS, comprobarla en
Cartago y comparar con San Carlos. Intentar un nuevo ingreso y mostrar el
mensaje; después reiniciar el central, esperar el mismo valor en los seis
nodos y reintentar el ingreso. Reiniciar el servicio también si se interrumpe
la toma:

```powershell
docker compose -p iiiproyectobasesii stop central
# Realizar las acciones de QGIS y las consultas mientras el central está detenido.
docker compose -p iiiproyectobasesii up -d --wait central
```

El ensayo automático `python -B db/outage_demo.py --scenario campus` crea y
limpia su propio edificio temporal. Su caso `--scenario central` verifica
edición SQL y reinicia el servicio automáticamente; no deja una pausa durante
la caída para el intento manual de autenticación. `--hold-seconds` pausa
después de la recuperación. La toma visual usa la secuencia manual anterior.

## Mostrar evidencias de operaciones

Los siguientes bloques solo leen informes de ejecuciones anteriores. Mostrar
el proyecto y la fecha del informe junto al resultado. Los procedimientos para
repetir las ejecuciones están en [operaciones](../ops/INTEGRACION.md),
[respaldos](../ops/BACKUPS.md), [PITR](../ops/PITR.md) y
[reincorporación](../ops/REINCORPORACION.md).

### 2PC y recuperación del coordinador

```powershell
$demo2pc = Get-Content -Raw -Encoding utf8 ops/recovery-results.json | ConvertFrom-Json
$demo2pc | Select-Object executed_at_utc, success, tests, duration_seconds
$demo2pc.scenarios | Where-Object { $_.scenario -in @('test_after_first_prepare', 'test_after_both_prepare_before_decision', 'test_after_commit_decision', 'test_after_only_one_commit') } | Select-Object scenario, operation_id, building_id, name, decision, audit_rows, campus_markers, prepared_transactions, retries_unchanged | Format-List
```

Se esperan nueve pruebas aprobadas. En los casos seleccionados, `ABORT`
conserva cero auditorías; `COMMIT` deja una auditoría y un marcador de campus.
`prepared_transactions=0` y `retries_unchanged=true` muestran resolución e
idempotencia. Mostrar también el cambio de nombre del escenario COMMIT en el
informe. Estas operaciones usan UUID nuevos por solicitud.

### Respaldos y PITR

```powershell
$demoBackup = Get-Content -Raw -Encoding utf8 ops/backup-results.json | ConvertFrom-Json
$demoBackup | Select-Object created_at_utc, status
$demoBackup.nodes.PSObject.Properties | ForEach-Object {
    [pscustomobject]@{ Nodo=$_.Name; Logico=$_.Value.logical.verified; Fisico=$_.Value.physical.verified; Restauracion=$demoBackup.logical_restore_test.nodes.($_.Name).verified }
} | Format-Table -AutoSize
$demoPitr = Get-Content -Raw -Encoding utf8 ops/pitr-results.json | ConvertFrom-Json
$demoPitr | Select-Object started_at_utc, status
$demoPitr.restore_point | Format-List
$demoPitr.target_reached.paused | Format-List
$demoPitr.recovery_finished.restored_fixture | Select-Object id, campus_id, nombre, codigo, area, pisos
$demoPitr.checks | Format-List
```

El respaldo físico se verifica con `pg_verifybackup`; el lógico, con
`pg_restore --list` y restauración aislada. Mostrar en PITR `state=paused`,
el punto y LSN alcanzados, `restored_fixture_matches=true` y
`original_fixture_deleted=true`. La fila recuperada del informe es `id=121`.
Su copia usó red `none`, sin puertos y WAL de solo lectura. El respaldo
original y los WAL se conservaron.

El resumen versionado de respaldos corresponde al laboratorio. La instalación
original tiene además sus seis respaldos del 16 de noviembre y el manifiesto
privado descrito en [integración](../db/INTEGRACION.md); no confundir ambos
conjuntos al presentar sus fechas.

### Reincorporación

```powershell
$demoRejoin = Get-Content -Raw -Encoding utf8 ops/rejoin-execution-results.json | ConvertFrom-Json
$demoRejoin | Select-Object project, started_at_utc, status, phase
$demoRejoin.checks | Format-List
```

Mostrar `new_owner_only=true`, `all_geography_converged=true`,
`insert_update_delete_both_hops=true` y `prepared_transactions=0`. El
propietario anterior permanece detenido. Esta ejecución ya sustituyó el nodo
de laboratorio; no repetir el procedimiento sobre ese mismo reemplazo para
obtener una toma nueva.

## Resultado del ensayo técnico del 27 de noviembre

- La consulta de lectura se ejecutó con éxito en los seis nodos originales:
  PostgreSQL **17.11**, PostGIS **3.6.4**, ocho capas y el total
  `40 objetos / 40 IDs / 5 campus / 40 geometrías correctas` en cada nodo.
- Se comprobaron 40/40 relaciones listas en el central y 33/33 en cada campus,
  diez slots activos, ocho estilos por nodo y cero transacciones preparadas.
- La prueba visual de ingreso, edición propia, rechazo ajeno, caída del central,
  convergencia y reingreso está en [validacion.md](validacion.md).
- Se ensayó la lectura de los informes de 2PC, respaldo, PITR y reincorporación.
  Los comandos anteriores no repiten esas operaciones ni cambian sus datos.

El tiempo de **9:20 es el presupuesto de la exposición en vivo**, no una
duración observada de las tres voces. El video narrado ya exportado dura
**8:34,905**, utiliza voz sintética en español e incluye subtítulos. Se
decodificó completo sin errores, se verificaron audio y duración y se
revisaron fotogramas de los capítulos principales. La información de
fuentes, generación, archivos y estado de Moodle está en
[entrega final](entrega.md).
