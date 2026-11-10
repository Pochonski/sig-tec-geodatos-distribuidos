# Diseño de SIG-TEC

SIG-TEC permitirá consultar la información geográfica de los cinco campus del Tecnológico de Costa Rica desde QGIS. Cada campus será el único que pueda modificar sus datos originales. El nodo central autenticará a los usuarios, recibirá los datos de todos los campus y distribuirá las copias de consulta y la simbología institucional. Este documento describe el diseño acordado para implementar el enunciado.

## Arquitectura de la demostración

Docker Compose ejecutará seis instancias PostgreSQL 17 con PostGIS 3.6 en una sola computadora x86_64. Cada instancia tendrá un volumen de datos independiente y una base llamada `sig_tec`. QGIS 3.44 LTR se ejecutará en la computadora anfitriona. La replicación se comunicará por la red interna de Compose y los clientes del anfitrión usarán los puertos publicados en `127.0.0.1`. [Publicación de puertos de Docker](https://docs.docker.com/engine/network/port-publishing/)

| Nodo | `campus_id` | Esquema geográfico de origen | Puerto en el anfitrión |
| --- | --- | --- | --- |
| Central | — | — | `55430` |
| Cartago | `1` | `cartago` | `55431` |
| San José | `2` | `san_jose` | `55432` |
| San Carlos | `3` | `san_carlos` | `55433` |
| Alajuela | `4` | `alajuela` | `55434` |
| Limón | `5` | `limon` | `55435` |

Los cinco esquemas de origen existirán en las seis instancias. En el campus correspondiente, las tablas del esquema serán las originales. En el nodo central y los otros cuatro campus, esas mismas tablas contendrán copias de consulta.

## Modelo geográfico

Las ocho capas tendrán `id` (`bigint`, clave primaria en cada tabla física), `campus_id` (`smallint`, obligatorio y restringido al campus del esquema) y `geom` (geometría PostGIS 2D del tipo indicado). Cada campus asignará el `id` desde una sola secuencia compartida entre sus ocho tablas, iniciada en su `campus_id` y con incremento de cinco. Así, cada identificador será único entre campus y capas sin coordinar la inserción con otro nodo. `id` y `campus_id` se mantendrán fijos durante la edición.

| Capa | Tabla y vista | Geometría | Atributos propios |
| --- | --- | --- | --- |
| Edificios | `edificios` | `Polygon` | `nombre` y `codigo` (texto), `area` (m²), `pisos` (entero) |
| Carreteras | `carreteras` | `LineString` | `nombre`, `tipo` y `superficie` (texto) |
| Aceras | `aceras` | `LineString` | `material` y `condicion` (texto), `ancho` (m) |
| Parqueos | `parqueos` | `Polygon` | `capacidad` (entero), `tipo` (texto), `disponibilidad` (booleano) |
| Zonas verdes | `zonas_verdes` | `Polygon` | `area` (m²), `tipo_vegetacion` (texto) |
| Puntos de interés | `puntos_interes` | `Point` | `nombre` y `tipo` (texto) |
| Iluminación | `iluminacion` | `Point` | `codigo` y `estado` (texto), `potencia` (W) |
| Accesibilidad | `accesibilidad` | `LineString` | `tipo` (texto) |

Se usará provisionalmente EPSG:8908 (CR-SIRGAS / CRTM05) hasta confirmar el sistema institucional. Cada tabla declarará el tipo y el SRID en `geom`, por ejemplo `geometry(Polygon, 8908)`. Las geometrías importadas en otro sistema se transformarán desde su SRID de origen con `ST_Transform`. Los datos de la demostración serán sintéticos, con un objeto por capa y campus, para un total de 40 objetos. [Perfil de metadatos geográficos del IGN](https://www.snitcr.go.cr/pdfs/normativa_tecnica/NTIG_CR04_10_2020_PERFIL_OFICIAL_DE_METADATOS_GEOGRAFICOS_DE_COSTA_RICA_ISO_19115-1_2014_NOV__19_2020_V2.pdf) · [Transformación de coordenadas en PostGIS](https://postgis.net/docs/ST_Transform.html)

## Replicación y vistas

1. **Campus a central.** Cada campus publicará solo las ocho tablas de su esquema de origen. El nodo central tendrá una suscripción por campus. Las tablas de destino se crearán antes de suscribirse porque PostgreSQL empareja las tablas por esquema y nombre y la replicación lógica no crea el esquema en el destino. [Suscripciones lógicas de PostgreSQL 17](https://www.postgresql.org/docs/17/logical-replication-subscription.html)
2. **Central a campus.** El nodo central volverá a publicar los cinco esquemas por separado y publicará `public.layer_styles`. Cada campus tendrá una suscripción a las cuatro publicaciones geográficas de los demás campus y a la de estilos. `origin=any` permite reenviar al campus los cambios que el central recibió por replicación. Excluir el esquema propio evita que una modificación vuelva a la tabla original. [Parámetros de `CREATE SUBSCRIPTION`](https://www.postgresql.org/docs/17/sql-createsubscription.html)
3. **Inicialización y seguimiento.** Se crearán primero las tablas, los roles y las publicaciones. Se habilitará la copia inicial contra destinos vacíos y se esperará a que las tablas estén sincronizadas en el central antes de iniciar las suscripciones de los campus. Se revisará el estado de las suscripciones y el WAL retenido por los slots. Tras una desconexión temporal, las suscripciones existentes retomarán la replicación al restablecerse la conexión. [Configuración de la replicación lógica](https://www.postgresql.org/docs/17/logical-replication-config.html) · [Seguimiento de la replicación lógica](https://www.postgresql.org/docs/17/logical-replication-monitoring.html)

Cada nodo ofrecerá una vista por capa en el esquema `sig`. Cada vista hará `UNION ALL` de la tabla equivalente de los cinco esquemas y expondrá `id`, `campus_id`, los atributos y la geometría tipada. Los cambios locales estarán disponibles al confirmar la escritura. Los cambios de otros campus llegarán de forma asíncrona a través del central.

El primer hito probará este recorrido con `sig.edificios` en Cartago y San Carlos antes de extenderlo a las demás capas y campus.

## Inicio de sesión, edición y estilos

El complemento PyQGIS solicitará usuario y contraseña. Cada persona tendrá una cuenta PostgreSQL individual con el mismo usuario y contraseña en el nodo central y en su campus. En el central, la función de consulta `auth.mi_campus()` devolverá únicamente el `campus_id` asignado al `session_user` autenticado. Las cuentas del complemento tendrán permiso para ejecutar la función y el registro de asignaciones quedará reservado a la administración. El complemento conectará al puerto del campus y añadirá las ocho vistas `sig` con el proveedor PostgreSQL, `geom` como columna geométrica e `id` como clave de la capa. Las conexiones usarán referencias `authcfg` al sistema de autenticación de QGIS para guardar las credenciales localmente. [Carga de capas con PyQGIS](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/loadlayer.html) · [Autenticación en PyQGIS](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/authentication.html)

Los usuarios del campus tendrán permisos de lectura y edición sobre las vistas. En cada vista operativa, un disparador `INSTEAD OF` por fila ejecutará una función `SECURITY DEFINER`. Su propietario será un rol `NOLOGIN` con acceso de escritura limitado a las tablas originales del campus y uso de su secuencia. La función usará nombres de esquema explícitos y un `search_path` fijo que solo incluya esquemas de confianza, con `pg_temp` al final. Aplicará estas reglas en PostgreSQL. [Funciones de disparador de PostgreSQL 17](https://www.postgresql.org/docs/17/plpgsql-trigger.html) · [Permisos y configuración de funciones](https://www.postgresql.org/docs/17/sql-createfunction.html)

| Operación | Comportamiento |
| --- | --- |
| `INSERT` | Rechaza un `campus_id` explícito de otro campus. Si se omite o coincide con el local, fija el `campus_id` local, genera el `id` e inserta en la tabla de origen. Devuelve la fila con su identificador generado. |
| `UPDATE` | Comprueba el `campus_id` de la fila existente, rechaza cambios de `id` o de campus y actualiza la tabla local. Devuelve la fila guardada. |
| `DELETE` | Comprueba el `campus_id` de la fila existente, elimina de la tabla local y devuelve la fila eliminada. |

Una operación que intente modificar una fila remota fallará con un mensaje explícito, incluso si se ejecuta directamente por SQL sobre la vista. Las vistas centrales serán de consulta.

Un administrador definirá en el central los estilos predeterminados de las ocho vistas en `public.layer_styles`. Los campus recibirán esos estilos por replicación y el complemento cargará el estilo de base de datos al abrir cada capa. Los seis nodos compartirán el nombre de base, esquema, vista y columna geométrica porque QGIS usa esos campos para localizar el estilo. [Búsqueda de estilos en el proveedor PostgreSQL de QGIS 3.44](https://github.com/qgis/QGIS/blob/release-3_44/src/providers/postgres/qgspostgresprovider.cpp#L5025-L5057)

## Transacción distribuida de demostración

Una CLI administrativa en Python con Psycopg implementará el renombrado de un edificio en el nodo de su campus y el registro de ese cambio en la bitácora del central. La CLI recibirá un UUID de operación, `campus_id`, `id` del edificio y el nombre nuevo. Cada nodo participante habilitará las transacciones preparadas y la CLI usará roles administrativos dedicados. [Transacciones preparadas en PostgreSQL](https://www.postgresql.org/docs/17/sql-prepare-transaction.html) · [Transacciones de dos fases con Psycopg](https://www.psycopg.org/psycopg3/docs/basic/transactions.html#two-phase-commit-protocol-support)

1. El coordinador registrará la solicitud en el central y serializará los intentos para el mismo UUID. Reutilizar el UUID con otro campus, edificio o nombre se tratará como error.
2. En la primera fase, la transacción del campus verificará y renombrará el edificio y guardará un marcador con el UUID. La transacción del central insertará la entrada de auditoría con el mismo UUID, que servirá de marcador central. Las dos ramas se prepararán con identificadores distintos derivados del UUID.
3. Cuando las dos ramas estén preparadas, el coordinador persistirá `COMMIT` en una transacción central independiente de la auditoría. Después de confirmar esa decisión, ejecutará `COMMIT PREPARED` en ambos nodos. La operación se reportará como completada cuando se comprueben los dos marcadores.
4. Un reintento con el mismo UUID consultará primero la decisión central y los marcadores de ambas ramas. Con `COMMIT` duradero, confirmará solo las ramas que sigan preparadas. Si puede verificar que no existe un `COMMIT` duradero, registrará `ABORT` y revertirá las ramas preparadas. Si el central no está disponible o el resultado de guardar la decisión es incierto, dejará la operación pendiente hasta poder leer la decisión. Si hay decisión `COMMIT` y falta tanto la transacción preparada como el marcador de un participante, el coordinador reportará la operación pendiente para reconciliación. [Confirmación de una transacción preparada](https://www.postgresql.org/docs/17/sql-commit-prepared.html) · [Reversión de una transacción preparada](https://www.postgresql.org/docs/17/sql-rollback-prepared.html)

La demostración simulará una caída antes de persistir la decisión y otra después de persistirla, con al menos una rama sin confirmar. Al reintentar se verificará respectivamente la reversión en ambos nodos o la aplicación completa sin entradas de auditoría duplicadas. La edición cotidiana de capas seguirá el flujo local de las vistas, con distribución posterior mediante replicación lógica.
