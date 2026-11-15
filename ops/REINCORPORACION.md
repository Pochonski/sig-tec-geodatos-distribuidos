# Preparación de integración y reincorporación

**Actualización PR #4: reincorporación real de laboratorio completada; ver [INTEGRACION.md](INTEGRACION.md) y [evidencia](rejoin-execution-results.json).**

El procedimiento de simulación y la alternativa de recopia siguientes se conservan como guía. No todas esas acciones fueron necesarias en el ensayo: se demostró igualdad con un corte y se crearon canales nuevos con copy_data=false, sin truncar tablas ni borrar los canales anteriores.
No existe opción `apply` en `rejoin.py`. No detiene nodos, ejecuta migraciones,
ajusta secuencias ni crea/elimina suscripciones, slots o tablas. Los pasos que
modifican estado descritos aquí requieren revisión y validación explícitas en
una etapa posterior, primero sobre un laboratorio descartable.

## Referencia revisada

Se hizo fetch, sin merge ni checkout, de `origin/joseph/cinco-campus-ocho-capas`,
commit **`f3e1f91e1e61e2f293fac4ba50de209cc0af65ea`**. Se leyeron directamente
los blobs de `compose.yaml`, `db/schema.sql`, `seed.sql`, `publications.sql`,
`subscriptions.sql`, `slot.sql`, `bootstrap.sh` y su documentación. El contrato
fijado y los hashes SHA-256 de esos archivos están en
[integration-reference.json](integration-reference.json). Si la referencia
remota cambia, el inspector exige revisar el contrato antes de usarla.

Fuente: [rama de Joseph](https://github.com/Pochonski/sig-tec-geodatos-distribuidos/tree/f3e1f91e1e61e2f293fac4ba50de209cc0af65ea).

| Aspecto | Entorno ops actual | Implementación de Joseph / adaptación necesaria |
| --- | --- | --- |
| Instancias | Central y Cartago; proyecto `sig-tec-ops` | Central y cinco campus; mantener proyecto y volúmenes independientes |
| Puertos del anfitrión | `57430`, `57431` | `55430`–`55435`: central, cartago, san_jose, san_carlos, alajuela, limon |
| Nombres de servicios | Dos nodos | Usa guiones bajos en `san_jose` y `san_carlos`, no guiones medios |
| Imagen | Tag `17-3.6` | Mismo contenido usado localmente, fijado por digest en la referencia |
| WAL | `replica`, archivo habilitado | `logical`, slots/senders/workers ajustados; no incluye todavía archivo WAL |
| 2PC | Esquema `ops`, rol CLI y recuperación administrativa | `max_prepared_transactions=10`, pero no contiene nuestras migraciones/CLI |
| Edificios | `id bigint`, `campus_id smallint`, `nombre text` | Añade `codigo text`, `area double precision`, `pisos integer`, `geom geometry(Polygon,8908) NOT NULL`; campus tiene default propio |
| Geografía | Una tabla mínima, sin geometría | Cinco esquemas físicos por nodo, ocho tablas por esquema y ocho vistas `sig.*` |
| IDs | Fixtures explícitos; no hay secuencia | Una secuencia `<campus>.sigtec_ids` por propietario, incremento 5, compartida entre ocho capas |
| Escritura ordinaria | Solo CLI administrativa mínima | Vistas editables con trigger `SECURITY DEFINER`, rol `sigtec_editor_owner`, cuentas `demo_<campus>` |
| Autenticación | Rol `sig_tec_ops_cli` con contraseña por nodo | Administración `SIGTEC_ADMIN_PASSWORD`, demos por campus y `SIGTEC_REPLICATION_PASSWORD`; rol `sigtec_repl` |
| Replicación | Ninguna | Campus → central → otros cuatro campus; `origin=any`, estilos desde central |

### Compatibilidad de nuestros componentes

- **Migraciones SQL:** aplicar `001_common.sql` y `002_central.sql` al central,
  `001_common.sql` y `003_cartago.sql` a Cartago **después** de crear el modelo
  de Joseph. `CREATE TABLE IF NOT EXISTS` no elimina columnas, pero tampoco
  amplía una tabla mínima existente: no sirve para convertir nuestro PGDATA
  mínimo en el modelo completo. Los grants por columnas siguen siendo adecuados
  para renombrar sin cambiar geometría. La migración común concede CONNECT,
  necesario porque Joseph lo revoca a PUBLIC.
- **No ejecutar `migrate.py` íntegro en integración:** siempre aplica el fixture
  mínimo. `fixtures/cartago.sql` no aporta `geom` y puede fallar o colisionar
  con la semilla real. Tampoco importar nuestro respaldo mínimo sobre seis nodos.
- **CLI y recuperación:** el UPDATE de `nombre` sobre la tabla original es
  compatible con las columnas reales y conserva la geometría. Falta hacer
  configurables endpoints/proyecto/credenciales: `rename.py` solo registra
  Cartago en `57431` y central en `57430`; `recover.py` reutiliza ese registro.
  Dar permisos equivalentes para otros propietarios requiere migraciones
  revisadas por campus. No usar `demo_*` ni `sigtec_repl` como coordinador.
- **Backups:** las herramientas PostgreSQL sirven para el modelo completo,
  pero `backup.py` descubre `sig-tec-ops`, usa dos endpoints y claves OPS. Falta
  un adaptador explícito para el proyecto de seis nodos. Los hashes de filas
  pueden comparar geometrías reales, aún no probadas en esta integración.
- **WAL/PITR:** se necesitan montajes y destinos por nodo conservando `logical`.
  No sustituir la lista `command` de Joseph por la del Compose mínimo, porque
  perdería sus parámetros de replicación. `wal.py` tiene preflight específico
  de dos nodos. `pitr.py` crea un edificio sin `geom` y también debe adaptarse.
  Para un fixture real, insertar por `sig.edificios` con la cuenta propietaria,
  geometría válida EPSG:8908 y atributos completos, dejando que el trigger
  asigne el ID. Registrar ese ID emitido aunque después se borre.
- **Arranque del recuperado:** un respaldo real incluye catálogos de
  suscripciones y sus credenciales. Arrancar sin red ni puertos y con
  `max_logical_replication_workers=0`, sin `primary_conninfo` y sin archivar
  desde la copia. Antes de darle red, deshabilitar las suscripciones de la copia
  con aprobación explícita y comprobar que no tenga workers ni GID desconocidos.
  El script PITR mínimo probado no realiza esta preparación completa para seis nodos.

## Topología concreta de Cartago

| Suscriptor | Suscripción | Publicador / slot alojado allí | Contenido |
| --- | --- | --- | --- |
| Central | `sub_central_cartago` | Cartago / `slot_central_cartago` | Las ocho tablas `cartago.*`, publicación `pub_cartago_edificios` |
| Cartago | `sub_cartago_central` | Central / `slot_cartago_central` | Cuatro esquemas ajenos (32 tablas) y `public.layer_styles` |
| Cada otro campus X | `sub_X_central` | Central / `slot_X_central` | Sus 33 copias remotas; entre ellas las ocho de Cartago |

`pub_cartago_edificios` y `pub_san_carlos_edificios` conservan nombres antiguos,
pero **publican ocho capas**, no solo edificios. Los otros nombres son
`pub_san_jose_capas`, `pub_alajuela_capas`, `pub_limon_capas` y `pub_layer_styles`.
El central tiene cinco suscripciones de ocho tablas y cinco slots para salida.
Cada campus tiene una suscripción de 33 tablas y un slot para el central.

## Comprobaciones implementadas (solo lectura)

```sh
ops/.venv/bin/python -B ops/rejoin.py compare --output ops/integration-reference.json
ops/.venv/bin/python -B ops/rejoin.py dry-run
ops/.venv/bin/python -B ops/test_rejoin.py
ops/.venv/bin/python -B ops/check_rejoin_lab.py
```

El perfil predeterminado `ops` consulta únicamente los dos endpoints actuales.
`--profile integration` usa los seis puertos `55430`–`55435` y requiere
`SIGTEC_ADMIN_PASSWORD`. Para el laboratorio usar:

```sh
ops/.venv/bin/python -B ops/rejoin.py dry-run \
  --config ops/rejoin-nodes.example.json --env-file ops/rejoin-lab/.env \
  --output ops/rejoin-lab-results.json
```

No poner contraseñas en el JSON: solo nombres de variables mediante `password_env`.
Solo se aceptan endpoints loopback. El archivo de entorno se lee, nunca se genera
ni modifica. La inspección TCP utiliza una transacción `REPEATABLE READ READ ONLY`,
`default_transaction_read_only=on`, timeouts y rollback al terminar.

Se consultan tablas, columnas, tipos/SRID declarados, restricciones, hashes,
conteos, IDs fuera de clase y duplicados entre capas; metadatos y posición de
secuencias **sin consumir valores**; publicaciones, slots, relaciones y workers
de suscripción, origins, roles y permisos del coordinador. Comprueba las tablas
exactas de las publicaciones/suscripciones, no solo sus cantidades. Detecta GID
pendientes y contradicciones actuales entre solicitudes, decisiones y marcadores.
No interpreta un hash distinto como prueba de cuál copia es la correcta.

Para inspeccionar una copia **ya arrancada y aislada**, se puede agregar:

```text
--restored-container NOMBRE_DE_COPIA --campus-id 1
```

Debe llevar `sig-tec-ops-purpose=pitr-test`, sin red ni puertos. El inspector
no la inicia. Usa `docker exec` con transacciones READ ONLY por consulta; no es
un snapshot global, por lo que la copia debe estar congelada para revisión.
Compara sus marcadores con decisiones del central actual. No lee ni serializa
`pg_subscription.subconninfo`, contraseñas de roles, payloads de solicitudes,
nombres de edificios ni geometrías; los payloads 2PC solo se comparan en memoria.

El JSON de simulación incluye bloqueos, topología y propuesta numérica de
secuencia. Código de salida 0 significa **inspección completada**, no autorización:
`execution_supported=false` y `ready_for_real_rejoin=false` siempre. Un error de
dependencia/consulta se informa sin DSN ni secretos. No hay comandos destructivos
generados ni función que ejecute el plan.

## Procedimiento de reincorporación (pendiente de aprobación y ensayo)

### 1. Congelar, inventariar y detener al propietario anterior

Definir ventana de mantenimiento, responsable y criterio de pérdida de cambios.
Suspender nuevas ediciones y coordinadores, drenar cambios aplicables y registrar
una barrera de comparación. Capturar inventario, backup reciente, system ID,
timeline, LSN, slots, origins, estado `r` por tabla, decisiones y todos los IDs
emitidos/reservados. No publicar credenciales guardadas en las suscripciones.

**Antes de activar el reemplazo**, detener y aislar al Cartago anterior y
comprobar fencing real: proceso detenido, clientes desconectados, endpoint/DNS
retirado y ningún segundo propietario escribiendo. Un timeout TCP no acredita
fencing. Conservar su volumen sin modificarlo para diagnóstico. Estos actos
no se ejecutaron ni están disponibles como opción de nuestros scripts actuales.

### 2. Revisar el restaurado sin red

Crear una copia nueva de un respaldo real posterior a habilitar WAL lógico y
archivado; recuperar a un punto nombrado con WAL montado en solo lectura.
Mantener la copia sin red y sin puertos, con workers lógicos desactivados desde
el primer arranque. Comprobar objetivo, nuevo timeline, modelo/roles, geometrías,
suscripciones copiadas y GID. Deshabilitar las suscripciones de esa copia con
validación explícita antes de permitir cualquier conexión a publicadores.
No permitir todavía conexiones de QGIS ni de la CLI al reemplazo.

### 3. Reconciliar cambios posteriores al objetivo

Para **las ocho capas propias**, comparar snapshots, registros de cambios,
fuentes supervivientes y resultados distribuidos posteriores a PITR. Resolver
altas, modificaciones y borrados con un registro de decisiones de negocio
aprobado. La ausencia en una réplica no distingue un borrado de una copia inicial
incompleta; un simple UPSERT de filas presentes tampoco propaga borrados.
Una réplica superviviente no es automáticamente la fuente autorizada del campus.
Las ediciones QGIS no tienen nuestra auditoría 2PC: sin historia suficiente o
aceptación explícita de pérdida, el procedimiento queda bloqueado.

Para cada UUID, consultar la **decisión central vigente**, auditoría y marcador
de campus y GID deterministas. Con COMMIT, solo confirmar ramas aún preparadas;
si faltan tanto GID como marcador, abrir reconciliación, no inventar un renombrado
o auditoría. Sin COMMIT verificable, aplicar la regla duradera de ABORT únicamente
después de revalidar el coordinador y sus bloqueos. Central inaccesible implica
pendiente. Un marcador prueba una operación histórica, no que `nombre` siga igual
tras operaciones posteriores. No mezclar el 2PC administrativo con activar
`two_phase` de replicación lógica; no hace falta habilitar esto último.

### 4. Validar y avanzar la secuencia compartida

Con escritores detenidos, inventariar `<campus>.sigtec_ids`: start, incremento 5,
sin CYCLE, límite bigint, `last_value`, `is_called` y reserva de caché. Obtener
MAX(id) de **todas las ocho capas**, en restaurado y copias supervivientes, pero
también el máximo histórico aprobado de IDs emitidos, incluso filas borradas,
transacciones abortadas y valores reservados en caché. PostgreSQL no replica las
secuencias y MAX(id) solo no evita reutilizar identificadores emitidos tras PITR.

`--issued-high-water NUMERO` habilita únicamente un cálculo de simulación:
propone el menor valor superior a todos esos límites y congruente con campus_id
módulo 5. Si faltan historia, secuencia o espacio bigint, bloquea la propuesta.
No llama `nextval`, `setval` ni `ALTER SEQUENCE`. Tras aprobación, un operador
podrá fijar la propuesta como próximo valor (`is_called=false`), nunca retroceder,
y verificar que el siguiente alta por vista use la clase correcta sin colisión
entre las ocho capas. Esta escritura y esa alta quedan pendientes del laboratorio.

### 5. Reconstruir solo canales y copias afectados

No reutilizar a ciegas slots/origins/LSN de antes de PITR: el restaurado puede
estar detrás de lo ya confirmado por sus suscriptores. No copiar manualmente un
`confirmed_flush_lsn` para saltar conflictos. Guardar estado y decidir por canal
si la continuidad está probada o requiere una sincronización inicial nueva.
No ejecutar `db/bootstrap.sh` como reparación general: su REFRESH solo añade
tablas no conocidas, no vuelve a copiar tablas ya suscritas aunque estén vacías.

Plan de reconstrucción para Cartago, **sin ejecutar aquí**:

1. **Salida Cartago → central:** revisar `sub_central_cartago` y el slot
   `slot_central_cartago` del publicador restaurado. Bajo aprobación, separar
   explícitamente el canal viejo y preparar su reemplazo con estado/slot nuevos
   si no hay continuidad demostrada. Las únicas tablas centrales candidatas a
   reinicializar son las ocho `cartago.*`; nunca los otros esquemas ni `ops`.
2. **Evitar propagación accidental del vaciado:** las publicaciones de Joseph
   publican TRUNCATE por defecto. Detener una suscripción solo pospone la
   aplicación: podría consumir el TRUNCATE al volver. Antes de vaciar en central,
   se debe aislar y retirar temporalmente la publicación de Cartago de los
   cuatro canales descendentes afectados, actualizar su inventario de relaciones
   y confirmar que ningún consumidor pueda aplicar ese vaciado. La secuencia
   exacta de ALTER/DROP/REFRESH requiere ensayo y autorización; no está automatizada.
3. **Entrada central → Cartago restaurado:** sus 33 tablas son copias remotas
   (32 de los otros campus y estilos). Validar el estado del slot
   `slot_cartago_central` en el central y de `sub_cartago_central` en la copia.
   Si requiere recopia, solo se podrán vaciar esas 33 copias en el restaurado,
   nunca sus ocho originales `cartago.*`, secuencia, `ops`, roles o auditorías.
4. **Central → otros cuatro campus:** no borrar sus suscripciones completas
   por defecto. Cada una comparte un slot para 33 tablas. El candidato selectivo
   es retirar únicamente `pub_cartago_edificios`, refrescar para retirar sus
   ocho relaciones, preservar las otras 25, y después de aprobar su vaciado
   local selectivo, agregar nuevamente esa publicación con copia inicial.
   PostgreSQL solo recopia tablas consideradas nuevas por la suscripción.
   Conservar `origin=any` y la exclusión del esquema propietario de cada campus.
5. Si el **slot compartido** de un campus está inválido o perdido, no afirmar
   que reemplazarlo solo afecta ocho tablas: afecta las cinco publicaciones de
   ese canal. Detenerse y aprobar un plan adicional (resincronización de las 33
   copias correspondientes o separación revisada de canales). Nunca vaciar
   las tablas originales de ese campus por comodidad.
6. Cada retirada/creación de slot y suscripción requiere validar propietario,
   publicador, actividad, credenciales locales, retención WAL y ausencia de GID.
   Preferir nombres nuevos de ensayo y preservar evidencia del canal anterior.
   No dejar que DROP SUBSCRIPTION elimine un slot remoto sin haberlo identificado
   y aprobado. No usar TRUNCATE CASCADE ni limpiar esquemas completos.

### 6. Validar convergencia y liberar al único propietario

Primero esperar las ocho relaciones del central en `r` y comparar conteos,
claves, atributos, geometría/SRID e índices. Después esperar 33 relaciones `r`
por campus y comparar las ocho copias de Cartago en los otros cuatro campus.
Verificar que las otras 25 copias y cada esquema propio conservan sus hashes.
`r` no demuestra por sí solo que todos los cambios posteriores hayan convergido:
comparar contenido y sondear un cambio identificable con tiempo límite.

Con autorización en el laboratorio: alta temporal por vista, cambio y baja
Cartago → central → los otros cuatro campus; comprobar rechazo de edición ajena,
estilos, una operación 2PC nueva y su reintento sin duplicados. Probar un flujo de
otro campus hacia el restaurado para verificar su canal entrante. Auditar origins,
workers, errores y WAL retenido. Liberar QGIS/CLI únicamente al reemplazo tras
confirmar que el propietario antiguo sigue detenido. No reincorporar ambos.

## Laboratorio de seis nodos: preparación reproducible, no desplegada

`check_rejoin_lab.py` valida en memoria la combinación del Compose de Joseph y
`rejoin-lab.override.yaml`: proyecto **`sig-tec-rejoin-lab`**, puertos
`58430`–`58435`, red interna y volúmenes con ese prefijo. Usa valores efímeros
solo para interpolar; no los imprime ni inicia servicios. Requiere Compose
>=2.24.4 por `!override`. Resultado en [rejoin-lab-check.json](rejoin-lab-check.json).

Para un ensayo futuro **tras validar explícitamente el despliegue nuevo**:

```sh
mkdir -p ops/rejoin-lab/source
git archive f3e1f91e1e61e2f293fac4ba50de209cc0af65ea compose.yaml db .env.example \
  | tar -x -C ops/rejoin-lab/source
```

Esto copia la fuente fijada a `ops/`, sin cambiar rama ni archivos de Joseph.
Crear después `ops/rejoin-lab/.env` con modo `0600` y las siete variables de su
`.env.example`, con valores aleatorios distintos, **alfanuméricos** de al menos
24 caracteres (su bootstrap rechaza `_` y `-`). No reutilizar las contraseñas
de los nodos actuales. El directorio completo está excluido de Git.

Antes de autorizar el arranque, comprobar que el proyecto no tiene recursos
previos, los puertos están libres, la red no es externa, los volúmenes no son
externos y ninguno referencia `sig-tec-ops`, otro entorno o wger. Comprobar
también la ruta bind `db/` y no imprimir `compose config` con valores resueltos:

```sh
docker compose -p sig-tec-rejoin-lab --env-file ops/rejoin-lab/.env \
  -f ops/rejoin-lab/source/compose.yaml -f ops/rejoin-lab.override.yaml config --quiet
```

Solo entonces un operador podrá iniciar **ese proyecto nuevo** y ejecutar el
bootstrap de Joseph en sus bases vacías, con las mismas opciones `-p`, `--env-file`
y `-f`. No se ejecutó este arranque en esta etapa. El override preparado cambia
solo puertos/red: faltan overlay de archivo WAL conservando `wal_level=logical`,
migraciones ops sin fixture mínimo y adaptación de endpoints/fixture geométrico
de backup/PITR/CLI. No usar directamente nuestros comandos de dos nodos para
completar esos pasos.

Con seis nodos sincronizados y operaciones de ensayo registradas, tomar un
respaldo físico de su Cartago, generar cambios posteriores conocidos (incluidos
borrados y 2PC), restaurar en una copia sin red y ejecutar la inspección con el
inventario de laboratorio. La sustitución y resincronización se ensayan solo
allí, después de aprobación de las tablas/canales concretos, deteniendo únicamente
el propietario **de laboratorio**. Mantener intactos todos los entornos existentes.

## Lo implementado, probado y pendiente

**Implementado:** contrato fijado a Joseph, comparación documentada, inventario
READ ONLY, diagnóstico del 2PC actual/restaurado, cálculo puro de próximo ID,
plan sin ejecutor, ejemplo de conexiones y override de puertos/red, validador
de Compose sin despliegue y pruebas automatizadas.

**Probado:** siete pruebas puras y una inspección real de los dos nodos ops.
Se compararon todos sus datos y GID antes/después y el inventario Docker. Hay
43 solicitudes y decisiones, 31 auditorías y marcadores, 44 edificios, cero GID
preparados y cero contradicciones 2PC actuales. La simulación bloqueó correctamente
el uso del modelo mínimo como sustituto de seis nodos: sin geometría, sin
secuencia compartida, sin replicación y con `wal_level=replica`. El Compose del
laboratorio validó sin crear contenedores ni volúmenes. Evidencia en
[rejoin-results.json](rejoin-results.json) y [rejoin-lab-check.json](rejoin-lab-check.json).

**Dependencias exactas pendientes:** stack nuevo de seis nodos; sus siete valores
locales SIGTEC (no existen en nuestro `.env` OPS); integración de migraciones y
adaptadores descritos; archivo WAL lógico y respaldo real del modelo completo;
copia restaurada accesible solo para revisión; historia aprobada de cambios e
IDs emitidos; fencing y autorización explícita de acciones de sustitución y
resincronización. `rejoin-integration-dependencies.json` registra la falta de
`SIGTEC_ADMIN_PASSWORD` sin intentar otras credenciales. No faltan paquetes
Python para las comprobaciones realizadas: se usa Psycopg 3 ya instalado.

**Actualización de lo probado:** en la copia de seis nodos se probaron geometrías, PITR, fencing del propietario de laboratorio, reconciliación, ajuste de secuencia, canales nuevos y convergencia real. No se conectó a la instalación personal de Joseph, no se truncaron copias ni se eliminaron canales. La recopia selectiva alternativa y la autorización de producción siguen pendientes; ver INTEGRACION.md.

Referencias PostgreSQL 17: [restricciones y secuencias no replicadas](https://www.postgresql.org/docs/17/logical-replication-restrictions.html),
[REFRESH y copia inicial](https://www.postgresql.org/docs/17/sql-altersubscription.html),
[slots y posiciones de consumidores](https://www.postgresql.org/docs/17/logicaldecoding-explanation.html).
