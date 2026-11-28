# Validación y demostración de SIG-TEC

Este documento define las pruebas de aceptación y sus resultados esperados. Registrar para cada prueba el commit, las versiones, el resultado y la evidencia. Ejecutar con PostgreSQL 17, PostGIS 3.6, QGIS 3.44 LTR y datos sintéticos.

## Primer hito

Levantar Cartago, el central y San Carlos con `sig.edificios`. Iniciar sesión en QGIS en ambos campus, editar un edificio propio desde cada uno y verificar los dos recorridos por el central. Cada vista debe mostrar los edificios de ambos campus, admitir las ediciones propias y rechazar las ajenas. Completar este hito antes de ampliar la prueba a las ocho capas y los cinco campus.

## QGIS y modelo geográfico

Partir de una instalación nueva con los cinco campus y el nodo central. La semilla carga un objeto por capa en cada campus. El proyecto QGIS de prueba empieza vacío.

| Prueba | Resultado esperado |
| --- | --- |
| Inventario inicial | Las ocho vistas del esquema `sig` muestran cinco objetos cada una. Comprobar `edificios`, `parqueos` y `zonas_verdes` como `Polygon`, `carreteras`, `aceras` y `accesibilidad` como `LineString`, y `puntos_interes` e `iluminacion` como `Point`. Las 40 geometrías son válidas y tienen SRID 8908, provisional hasta confirmar el institucional. |
| Identidad y pertenencia | Comprobar identificadores `BIGINT` únicos entre campus y capas. Verificar que cada `id` sigue la secuencia que arranca en `campus_id` y avanza de cinco en cinco. Contrastar `campus_id` con el nodo propietario. |
| Autenticación | Abrir el complemento con una cuenta de cada campus. El servidor central valida la identidad y el complemento carga ocho vistas del nodo correspondiente a Cartago (1), San José (2), San Carlos (3), Alajuela (4) o Limón (5). Cada sesión ve objetos de los cinco campus. Con credenciales inválidas, el complemento rechaza el acceso y el proyecto vacío conserva cero capas. |
| Edición local | En cada campus insertar, cambiar atributos y geometría, y eliminar un objeto propio desde QGIS. Cubrir las ocho capas entre las cinco sesiones, por ejemplo Cartago con edificios y carreteras, San José con aceras y parqueos, San Carlos con zonas verdes y puntos de interés, Alajuela con iluminación y Limón con accesibilidad. Verificar el resultado en la tabla de origen y recargar la vista después de guardar. |
| Aislamiento | Desde una cuenta de campus, intentar actualizar y eliminar un objeto ajeno en QGIS y repetir por SQL sobre la vista con la misma cuenta. Probar insertar con `campus_id` ajeno, cambiar el `campus_id` de un objeto propio y escribir directamente en una tabla física. PostgreSQL rechaza esas operaciones. Comparar los registros antes y después. |
| Estilos | Cargar las ocho capas en proyectos vacíos de dos campus. Verificar que cada capa recibe el estilo compartido que corresponde a su vista. Publicar un cambio visible de estilo desde el central y comprobarlo al volver a cargar la capa en ambos nodos, una vez aplicada la réplica. |

## Replicación lógica y fallos

1. Desde `sig.edificios` en Cartago, hacer `INSERT`, `UPDATE` y `DELETE` en operaciones separadas sobre un edificio de prueba. Para cada operación, comprobar el cambio en origen, en el esquema de Cartago del central y en `sig.edificios` de San Carlos. Tras la inserción, la vista de Cartago muestra exactamente un objeto con ese identificador. Usar sondeo con tiempo límite y registrar el tiempo observado de convergencia.
2. Guardar dos cambios de prueba dentro de una transacción local y confirmar que ambos aparecen en el destino una vez aplicada la suscripción. Repetir con `ROLLBACK` y verificar que los valores anteriores se conservan en origen, central y destino.
3. Detener temporalmente el nodo de San Carlos. Confirmar un cambio en Cartago y verificar que se aplica al central. Reiniciar San Carlos y comprobar que la suscripción reanuda el consumo y aplica el cambio una sola vez. Revisar `pg_stat_subscription` y `pg_replication_slots` ante retrasos o errores.
4. Detener el central con una sesión de edición local ya abierta. Confirmar un cambio en el campus de origen y verificar que un nuevo inicio de sesión informa que el central está indisponible. Reiniciar el central y comprobar que el complemento vuelve a admitir el ingreso y que el cambio pendiente llega al resto de campus. Registrar el identificador y verificar el valor esperado del objeto en cada nodo.

## Renombrado administrativo con 2PC

Ejecutar la CLI de Python con Psycopg mediante un UUID de operación, el campus propietario, el identificador del edificio y el nuevo nombre. Comprobar siempre los dos efectos de negocio, el nombre en el campus y la fila de auditoría en el central. Consultar por separado el registro de decisión del coordinador y las transacciones en `pg_prepared_xacts`.

| Caso | Resultado esperado |
| --- | --- |
| Confirmación | El coordinador registra `COMMIT` de forma duradera antes de resolver la segunda fase. Cambia el nombre en el campus y se confirma una fila de auditoría en el central. Ambos participantes registran el UUID aplicado. |
| Aborto | Provocar un fallo durante la preparación después de que el primer participante quede preparado. Al resolver, se conserva el nombre anterior, no aparece la auditoría de negocio y se libera la transacción preparada. |
| Caída antes de la decisión duradera | Interrumpir el coordinador tras preparar ambos participantes y antes de registrar `COMMIT`. Al reiniciar, la recuperación resuelve el aborto y libera ambos participantes. Verificar que el edificio y la auditoría conservan su estado inicial. |
| Caída después de la decisión duradera | Interrumpir tras persistir `COMMIT`, primero antes de finalizar un participante y luego después de finalizar uno. La operación figura como pendiente hasta que ambos participantes confirmen. Al reiniciar, el coordinador confirma los participantes pendientes. Se observa un solo cambio de nombre, una fila de auditoría y cero transacciones preparadas para el UUID. |
| Reintento | Repetir la misma solicitud con el mismo UUID después de confirmar. La CLI devuelve el resultado original y se verifica un solo efecto por participante. Repetir con el mismo UUID y un nombre distinto. La CLI rechaza la solicitud y conserva el resultado original. |

La visibilidad del nombre en las vistas de otros campus se verifica después de la convergencia de la replicación lógica. La decisión 2PC cubre las escrituras en el campus propietario y el central.

## Respaldos, PITR y reincorporación

1. En los seis nodos, generar un respaldo lógico de `sig_tec` con `pg_dump` y un respaldo físico con `pg_basebackup`. Verificar que el respaldo lógico es legible con `pg_restore --list` y que el respaldo físico pasa `pg_verifybackup`. Forzar un cambio de segmento si es necesario y comprobar en `pg_stat_archiver` que cada nodo archiva WAL en su propio destino. Hacer la prueba de restauración lógica en una instancia aislada y verificar una muestra de geometrías, claves y conteos.
2. Para el escenario PITR, escoger un campus con un edificio de control y tomar el respaldo físico. Crear un punto de restauración nombrado después de que termine el respaldo, eliminar el edificio y confirmar el cambio. Forzar el cambio de segmento con `pg_switch_wal()` y comprobar que los segmentos necesarios llegaron al archivo antes de iniciar la recuperación.
3. Restaurar en un volumen separado y arrancar en una red aislada con el WAL archivado y el punto nombrado como objetivo. Consultar el edificio restaurado por identificador y comparar su geometría y atributos con los valores previos a la eliminación. Guardar evidencia del objetivo alcanzado y de la fila recuperada.
4. Para probar la reincorporación, detener el nodo anterior y deshabilitar las suscripciones del nodo restaurado mientras está aislado. Reconciliar los cambios posteriores al punto objetivo. Si se afectaron operaciones 2PC, contrastar el registro de decisiones con los marcadores aplicados, el nombre en el campus y la auditoría central. Resolver las discrepancias y avanzar la secuencia al siguiente valor válido por encima de los identificadores ya emitidos por ese campus.
5. Recrear los slots y sincronizar desde los orígenes autorizados con `copy_data` sobre destinos vacíos. Vaciar únicamente las tablas que contienen las réplicas afectadas. Antes de admitir tráfico normal, verificar que opera una sola instancia por campus, que los nuevos identificadores son únicos y que un cambio nuevo recorre ambos saltos. Comprobar que las copias remotas convergen con los datos del nodo propietario.

## Guion del video

El video debe durar como máximo **10 minutos**, incluyendo títulos y cierre. Usar registros y capturas de la ejecución de respaldo y restauración para mostrar el resultado dentro del tiempo.

| Tiempo | Evidencia a mostrar |
| --- | --- |
| 0:00–0:55 | Topología, nodos activos y ruta de cada salto de replicación. |
| 0:55–3:30 | Inicio de sesión en QGIS, ocho capas, estilos y edición local. Intento de edición ajena rechazado. |
| 3:30–5:30 | Propagación Cartago → central → San Carlos y convergencia después de reiniciar un nodo. |
| 5:30–7:40 | Renombrado 2PC, auditoría central y recuperación del coordinador después de una caída. |
| 7:40–9:40 | Respaldos por nodo, PITR aislado, edificio recuperado y evidencia de reincorporación. |

## Ejecución en la instalación original (16 de noviembre de 2026)

Con el código integrado de `main` en `dc956c9` y el proyecto Compose
`iiiproyectobasesii`, se conservó la instalación de seis volúmenes de datos y
se añadieron seis volúmenes WAL. Los seis servicios quedaron saludables.

| Comprobación | Resultado |
| --- | --- |
| Bootstrap y migración | Diez suscripciones existentes y sus slots reutilizados; ocho vistas con cinco objetos por nodo; ocho estilos predeterminados; cero transacciones preparadas. |
| Archivado y respaldos | Los seis nodos archivaron un segmento legible de 16 MiB sin nuevos fallos. Se crearon y verificaron seis `pg_dump` y seis `pg_basebackup`; seis restauraciones lógicas aisladas coincidieron en tablas, conteos y hashes. |
| Proveedor QGIS 3.44.15 | `db/qgis_smoke.py` pasó con 40 vistas, 40 IDs únicos, EPSG:8908, geometrías válidas, CRUD y rechazo de edición ajena en las ocho capas. |
| Complemento | `qgis/pruebas/test_qgis.py` aprobó siete casos y omitió uno: no se aprovisionó una cuenta sin campus. En Desktop, el perfil `sig_tec_main` cargó el complemento y mostró el diálogo con `127.0.0.1:55430` y `sig_tec`. El ingreso manual, pendiente al finalizar esta ejecución, se comprobó el 27 de noviembre. |
| Estado posterior | `ops/wal.py check-preserved` confirmó filas protegidas y montajes de los volúmenes originales, sin 2PC pendiente. |

Los respaldos, informes, credenciales y el perfil QGIS local no se publican en
Git. El procedimiento y la ubicación privada del manifiesto de respaldo están
en [INTEGRACION.md](../db/INTEGRACION.md). La prueba de PITR ya se había
completado en el proyecto de laboratorio `sig-tec-integracion`; en la
instalación original se verificaron respaldos y restauración lógica aislada.

## Desconexión y convergencia (24 de noviembre de 2026)

En la instalación original se hicieron dos ensayos con edificios temporales de
Cartago, sin modificar las filas de muestra. Con San Carlos detenido, Cartago
confirmó el alta y el central la recibió; al reiniciar San Carlos, los seis
nodos vieron la misma fila. Con el central detenido, una conexión ya abierta a
Cartago confirmó otra alta local; San Carlos no la recibió hasta que volvió el
central. En ambos casos se borró después la fila temporal y la baja convergió
en los seis nodos.

Los seis servicios terminaron saludables, con cinco edificios por nodo, slots
activos y cero transacciones preparadas. `ops/wal.py check-preserved` aprobó la
conservación de las filas protegidas y los montajes originales. El script y el
informe estructurado están en el [PR #7](https://github.com/Pochonski/sig-tec-geodatos-distribuidos/pull/7).
La prueba del central del 24 de noviembre verificó una conexión SQL local. La
comprobación visual del inicio de sesión se realizó el 27 de noviembre, como
se describe a continuación.

## Validación visual de QGIS (27 de noviembre de 2026)

Se utilizó QGIS Desktop **3.44.15**, perfil `sig_tec_main`, con el complemento
y las bases de la instalación original ejecutando `main` en `dc956c9`. Joseph
introdujo las credenciales en los diálogos de autenticación. La edición y la
lectura de los mensajes se hicieron en la interfaz de QGIS; la réplica se
comprobó mediante consultas SQL de solo lectura.

| Comprobación | Resultado observado |
| --- | --- |
| Ingreso y carga | `demo_cartago` inició sesión y cargó el grupo `SIG-TEC · Cartago` con las ocho capas. El proyecto mostró EPSG:8908 y los cinco puntos de interés, uno por campus. La tabla de edificios mostró cinco filas. |
| Edición propia y réplica | Desde la tabla de atributos se cambió temporalmente el nombre del edificio `id=1`, `campus_id=1`, a `Biblioteca ficticia de Cartago - prueba visual 27-11`. El guardado se aplicó en Cartago y el mismo valor se observó en el central y San Carlos. Se restauró el nombre previo, `Biblioteca ficticia de Cartago - editado en QGIS`, y se comprobó en los tres nodos. |
| Rechazo de edición ajena | La misma sesión intentó cambiar el nombre del edificio `id=3`, `campus_id=3`. QGIS informó `Solo puede editar edificios de su campus`, desde `sig.editar_capa()`. La base conservó `Laboratorio ficticio de San Carlos`. Se descartó el intento rechazado y la capa salió del modo de edición. |
| Estilos | Se observaron símbolos y etiquetas de las capas en QGIS. Central, Cartago y San Carlos tenían ocho registros en `public.layer_styles`, todos predeterminados. Esta comprobación no incluyó publicar una nueva versión de un estilo. |
| Guardado con el central detenido | Con la sesión de Cartago abierta se detuvo únicamente el servicio `central`. Desde QGIS se guardó para `id=1` el nombre `Biblioteca Cartago - prueba central detenido 27-11`. Cartago mostró el nuevo valor; los otros cuatro campus conservaron el anterior durante la caída. |
| Nuevo acceso durante la caída | Al intentar iniciar sesión, el complemento mostró `El servidor central no está disponible en 127.0.0.1:55430. Intente de nuevo cuando se restablezca.` Las capas de la sesión anterior permanecieron en el proyecto. |
| Convergencia al recuperar el central | Después de `docker compose -p iiiproyectobasesii up -d --wait central`, el nombre temporal se observó en los seis nodos. Las diez suscripciones y sus diez slots estaban activos, todas las relaciones estaban listas y no había transacciones preparadas. |
| Limpieza | Se restauró el nombre original a través de `sig.edificios` en Cartago por SQL bajo la identidad `demo_cartago`. Se comprobó el nombre original en los seis nodos, junto con cinco objetos en cada una de las ocho capas. |

El reingreso visual después de recuperar el central está pendiente de completar
en el diálogo abierto de QGIS. La convergencia de las bases ya se comprobó;
el mensaje de error conserva el resultado del intento hecho durante la caída
hasta que se pulse de nuevo `Iniciar sesión`.

Esta ejecución visual cubrió la edición de atributos de `edificios` desde
Cartago. El CRUD de las ocho capas y la validez de las geometrías se habían
verificado con las pruebas del proveedor PyQGIS descritas en la ejecución del
16 de noviembre; no se repitieron manualmente en esta sesión.

## Fecha de entrega

Joseph confirmó para el equipo el **lunes 30 de noviembre de 2026 a las
8:00 a. m.**, como indica la portada (p. 1). La fecha de junio de la sección
administrativa (p. 6) contradice esa confirmación; usar noviembre para la
planificación y la entrega.

## Consultas pendientes al profesor

- **Transacciones distribuidas.** Confirmar si el renombrado administrativo en el campus propietario y su auditoría central mediante 2PC satisface el rubro de la p. 6 y qué fallo debe demostrarse.
- **Referencia espacial.** Confirmar si existe un CRS institucional obligatorio para las capas de la p. 3. EPSG:8908 es el valor provisional para desarrollo y pruebas.
