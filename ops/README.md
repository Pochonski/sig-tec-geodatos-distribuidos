# Entorno aislado de operaciones

Dos instancias PostgreSQL 17 con PostGIS 3.6 y base `sig_tec`:

| Nodo | Dirección local | Usuario |
| --- | --- | --- |
| Central | `127.0.0.1:57430` | `postgres` |
| Cartago | `127.0.0.1:57431` | `postgres` |

Requiere Docker con Compose v2. Desde la raíz del repositorio:

```sh
cp ops/.env.example ops/.env
```

Editar `ops/.env` y asignar contraseñas locales distintas a
`OPS_CENTRAL_PASSWORD` y `OPS_CARTAGO_PASSWORD`. No compartir ese archivo.
Las variables vacías impiden iniciar el entorno. Las contraseñas se aplican
al inicializar cada volumen; cambiarlas en `.env` no modifica una base existente.

Iniciar en segundo plano:

```sh
docker compose --env-file ops/.env -f ops/compose.yaml up -d
```

Detener y eliminar los contenedores y la red, conservando los datos:

```sh
docker compose --env-file ops/.env -f ops/compose.yaml down
```

Volver a ejecutar `up -d` reutiliza los volúmenes. No usar `down -v`, porque
elimina los volúmenes de datos.

El nombre de proyecto `sig-tec-ops` aísla los contenedores, la red y los
volúmenes `central_data` y `cartago_data` mediante el prefijo del proyecto.
Mantener ese nombre: no sobrescribirlo con `-p` ni `COMPOSE_PROJECT_NAME`.
Cada nodo configura `max_prepared_transactions=10`.

## Migraciones para el futuro coordinador

Con los dos contenedores ya activos, ejecutar desde la raíz (Python 3,
biblioteca estándar y cliente Docker):

```sh
python3 -B ops/migrate.py
python3 -B ops/verify.py
```

Estos scripts solo usan `docker exec` sobre los servicios del proyecto
`sig-tec-ops`: no arrancan ni recrean contenedores y no eliminan volúmenes.
La migración se aplica en una transacción por nodo, con bloqueo asesor para
serializar aplicaciones concurrentes. Puede repetirse sin borrar datos.
No hay atomicidad entre nodos: ante un fallo, corregir la causa y repetir.

`migrate.py` genera dos contraseñas independientes si faltan o están vacías:
`OPS_CENTRAL_CLI_PASSWORD` y `OPS_CARTAGO_CLI_PASSWORD`, en `ops/.env`
(permisos `0600`, excluido de Git). Las existentes se conservan. No imprime
secretos ni los pasa como argumentos. Envía verificadores SCRAM-SHA-256 a
PostgreSQL por stdin; requiere acceso administrativo local mediante el
socket de los contenedores. No se necesita cambiar Compose ni recrearlo.

| Nodo | Estructura | Permisos de `sig_tec_ops_cli` |
| --- | --- | --- |
| Central | `ops.requests` | Leer e insertar UUID, campus, edificio y nombre nuevo |
| Central | `ops.decisions` | Leer e insertar UUID y decisión `COMMIT`/`ABORT` |
| Central | `ops.audit` | Leer e insertar los datos de una solicitud existente |
| Cartago | `cartago.edificios` | Leer `id`, `campus_id`, `nombre`; actualizar solo `nombre` |
| Cartago | `ops.applied_operations` | Leer e insertar UUID, campus, edificio y nombre nuevo |

El rol tiene `LOGIN`, `CONNECT` y `USAGE` en los esquemas necesarios, sin
atributos administrativos ni membresías. Las tablas pertenecen al administrador.
No recibe permisos para borrar, truncar ni actualizar solicitudes, decisiones,
auditoría o marcadores, ni para fijar sus timestamps. Los UUID son claves
primarias; la auditoría referencia también campus, edificio y nombre de la
solicitud para rechazar discrepancias. La auditoría es el marcador del central;
Cartago guarda su marcador local. No hay claves foráneas entre nodos.

La decisión se confirma en una transacción central independiente de la
auditoría. Se configura `synchronous_commit=on` por defecto para el rol y la CLI
lo exige al conectarse. Las migraciones definen las estructuras y permisos;
`rename.py` implementa el protocolo descrito más adelante.

`migrations/001_common.sql` se aplica en ambos nodos; `002_central.sql` solo
en el central y `003_cartago.sql` solo en Cartago. Son SQL para ejecutar como
administrador dentro de una transacción; el script configura después la
contraseña del rol. Joseph puede incorporar esos SQL en la integración.
La tabla mínima no sustituye el modelo geográfico completo: no agrega geometría
ni secuencias y conserva tablas existentes mediante `IF NOT EXISTS`.
`fixtures/cartago.sql` es únicamente una semilla del entorno aislado: crea el
edificio ficticio `id=1`, `campus_id=1`, y conserva cualquier fila con ese ID.
No se debe aplicar esta semilla al modelo completo de integración.

`verify.py` vuelve a aplicar las migraciones y compara todos los datos de esas
tablas. Prueba login TCP con las contraseñas locales, operaciones permitidas,
rechazos por permisos, duplicados y restricciones. Sus escrituras se revierten
con `ROLLBACK`; también compara IDs, tiempos de inicio, estados y montajes de
los contenedores antes y después. No ejecuta transacciones preparadas.

## CLI de renombrado con 2PC

Preparar las dependencias locales sin cambiar los contenedores:

```sh
python3 -m venv ops/.venv
ops/.venv/bin/python -m pip install --no-cache-dir -r ops/requirements.txt
```

Con las migraciones ya aplicadas y las credenciales existentes en `ops/.env`:

```sh
ops/.venv/bin/python -B ops/rename.py \
  8a2f19f0-44e7-47bc-afc3-56b8ce589ffa 1 1 'Edificio de prueba renombrado'
```

Los argumentos son UUID, campus, ID del edificio y nombre nuevo, en ese orden.
Usar un UUID nuevo por solicitud y conservarlo para reintentos. Solo se soporta
Cartago (`campus_id=1`). `CAMPUSES` en `rename.py` concentra el nombre del nodo,
el puerto y el esquema de cada campus para ampliarlo en la integración;
el central y Cartago usan los puertos aislados `57430` y `57431`.
El esquema se obtiene del registro, nunca del argumento del usuario.

La CLI usa únicamente el rol `sig_tec_ops_cli`, con Psycopg 3 y las contraseñas
`OPS_CENTRAL_CLI_PASSWORD` / `OPS_CARTAGO_CLI_PASSWORD`. La configuración se lee
sin modificarla, y no se muestran contraseñas ni diagnósticos SQL con secretos.
Los permisos actuales bastan para preparar y resolver las transacciones propias;
no se necesitan roles administrativos ni migraciones adicionales.

El flujo mantiene un bloqueo asesor de sesión central derivado del UUID durante
toda la operación, registra la solicitud y compara su contenido en los reintentos.
La conexión de control trabaja en autocommit. Otras dos conexiones abren las
transacciones participantes: actualización y marcador en Cartago, auditoría en
el central. Cada una ejecuta `PREPARE TRANSACTION` con el GID determinista
`sig-tec:ops:v1:<UUID>:cartago` o `sig-tec:ops:v1:<UUID>:central`.

Solo tras preparar ambas ramas se inserta la decisión `COMMIT` en la conexión
de control, con confirmación síncrona local. Después se ejecutan los dos
`COMMIT PREPARED` y se comprueban los marcadores y la ausencia de esos GID
antes de responder éxito. La API de conexiones y el tratamiento de transacciones
se basan en la [documentación de Psycopg 3](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).

La salida es JSON y el código de salida indica:

| Código | Estado | Significado |
| --- | --- | --- |
| `0` | `completed` | Ambos marcadores confirmados; `repeated` identifica un reintento |
| `0` | `aborted` | Reintento de una operación recuperada con ABORT y sin ramas pendientes |
| `1` | `error` | Entrada inválida, configuración incompleta o UUID con otros datos |
| `2` | `pending` | Error SQL/conexión, interrupción o solicitud anterior incompleta |

Un reintento completado devuelve el resultado registrado y no vuelve a renombrar
el edificio: otra operación posterior podría haber cambiado su nombre.
Los errores no provocan `ROLLBACK PREPARED` ni intentos automáticos de recuperar
ramas. Si falla la escritura de la decisión, su resultado se considera incierto.
Si falla una confirmación después de decidir `COMMIT`, puede haber una rama
aplicada y otra preparada: se informa pendiente y la decisión obliga a completar
la confirmación en una futura recuperación. Las transacciones abiertas sin
preparar se descartan al cerrar la conexión.

Una solicitud existente que no esté completamente confirmada o abortada
se reporta pendiente, incluso si no llegó a preparar ramas (por ejemplo, por un
edificio inexistente). Resolverla con `recover.py`. No se debe usar otro UUID
para eludir una operación pendiente ni resolver ramas manualmente sin reconciliar
la decisión y marcadores.
Los timeouts de conexión, sentencias y bloqueos evitan esperas indefinidas.

## Pruebas de integración de la CLI

```sh
ops/.venv/bin/python -B ops/test_rename.py
```

Las cuatro pruebas ejercitan la CLI como procesos separados contra PostgreSQL:
éxito, repetición idéntica, rechazo de UUID con otro nombre/edificio y concurrencia
con el mismo UUID. La prueba concurrente espera a que ambos procesos estén
bloqueados antes de liberarlos; uno ejecuta y el otro devuelve el resultado previo.
Se comprueban nombre, solicitud, decisión, auditoría, marcador, timestamps sin
cambios en reintentos y ausencia de transacciones preparadas de esos UUID.

Cada prueba crea un edificio sintético propio con ID de Cartago y conserva su
solicitud, decisión y evidencias como resultado de la prueba. No cambia el
edificio semilla `id=1` ni elimina registros anteriores. Usa la credencial
administrativa existente de Cartago solo para insertar esos fixtures; todas
las operaciones de la CLI se ejecutan con el rol limitado. El resumen de la
última ejecución se guarda sin credenciales en `ops/test-results.json`, ignorado
por Git. También se comprueba que los contenedores y sus montajes no cambiaron.

## Recuperación por UUID

Con el mismo entorno y rol limitado, ejecutar desde la raíz:

```sh
ops/.venv/bin/python -B ops/recover.py UUID_DE_LA_OPERACION
```

El comando obtiene el campus y la carga original desde `ops.requests`.
Mantiene el mismo bloqueo asesor de sesión que `rename.py` y consulta
`ops.decisions`, `ops.audit`, `ops.applied_operations` y los GID de
`pg_prepared_xacts` en ambos nodos antes de resolver ramas.

| Evidencia | Acción |
| --- | --- |
| `COMMIT` duradero | Confirmar solo los GID aún preparados; conservar los marcadores existentes |
| Sin decisión y sin marcadores aplicados | Registrar `ABORT` duradero y después revertir los GID preparados |
| `ABORT` duradero | Revertir las ramas que sigan preparadas |
| Central inaccesible o decisión no verificable | Informar `pending`; no inferir una decisión |
| `COMMIT`, pero sin GID ni marcador de un participante | Informar reconciliación pendiente; no generar datos ni auditoría |
| Marcadores incompatibles, ABORT con marcadores o cambios sin decisión | Informar reconciliación pendiente |

Una pérdida de respuesta al escribir `ABORT` también deja la operación pendiente:
se debe volver a leer la decisión antes de revertir. Antes de resolver cada rama
se revalida la decisión en la sesión que mantiene el bloqueo. Una segunda caída
durante la recuperación se resuelve repitiendo el mismo comando. Las decisiones
son inmutables para el rol; no se cambia `COMMIT` por `ABORT` ni a la inversa.

La respuesta JSON incluye `decision`, los participantes efectivamente resueltos
en `resolved` y el estado final de sus marcadores y GID. Código `0` significa
`completed` o `aborted`, código `2` significa `pending` y código `1` indica
configuración inválida. Repetir una recuperación completada devuelve
`resolved: []`. Repetir luego `rename.py` con los mismos argumentos informa
`completed` o `aborted` sin volver a escribir. Un UUID abortado no se reutiliza
para otra solicitud.

La recuperación usa los permisos existentes: el mismo usuario que preparó
las ramas puede resolverlas desde otra sesión, en autocommit. Véanse
[COMMIT PREPARED](https://www.postgresql.org/docs/17/sql-commit-prepared.html) y
[ROLLBACK PREPARED](https://www.postgresql.org/docs/17/sql-rollback-prepared.html).
No se requieren nuevas migraciones ni privilegios administrativos.

## Pruebas de interrupción y recuperación

```sh
ops/.venv/bin/python -B ops/test_recovery.py
```

Se verifican nueve escenarios:

| Escenario | Resultado esperado |
| --- | --- |
| Interrupción tras preparar Cartago | ABORT y reversión de Cartago |
| Interrupción tras preparar ambas ramas | ABORT y reversión de ambas |
| Interrupción tras guardar COMMIT | Confirmación de ambas ramas |
| Interrupción tras confirmar solo Cartago | Confirmación únicamente del central |
| Central inaccesible sin decisión | Sin cambios; ABORT al restablecer el acceso |
| Central inaccesible con COMMIT | Sin cambios; confirmación al restablecer el acceso |
| Confirmación de ABORT incierta | Ninguna rama resuelta hasta volver a verificar ABORT |
| Lectura de rama y marcador faltantes con COMMIT | Reconciliación pendiente sin inventar registros |
| Dos recuperadores concurrentes | Uno resuelve las ramas; el otro comprueba el resultado |

En cada escenario terminado se comprueban el nombre, la solicitud, la decisión,
la auditoría, el marcador y la ausencia de GID pendientes. Se repiten recuperación
y renombrado para verificar idempotencia, incluidos los timestamps de evidencias.
La prueba compara todos los registros existentes al inicio (también el edificio
semilla) y los IDs, estados, tiempos de inicio y montajes de todos los contenedores.

`fault_worker.py` es exclusivamente un arnés de pruebas. Su subcomando `crash`
termina el proceso con `os._exit(86)` en el checkpoint seleccionado; no ejecuta
limpieza Python. PostgreSQL conserva las ramas preparadas y descarta las abiertas.
Los cuatro checkpoints opcionales de `rename()` no se activan desde la CLI normal.
Para la inaccesibilidad se dirige únicamente el proceso de recuperación a un
puerto local reservado sin listener; no se detiene ni desconecta el central real.
La pérdida de confirmación de ABORT se inyecta después de escribirlo realmente,
y la rama faltante se simula al leer las evidencias para evitar destruir una
transacción con COMMIT duradero. Estas dos inyecciones están identificadas en
el informe y no sustituyen una prueba de corte de red o pérdida física de datos.

Las pruebas usan edificios nuevos y UUID aleatorios y conservan sus resultados,
sin alterar operaciones anteriores. Ante una aserción fallida, intentan recuperar
solo el UUID propio de esa prueba usando la decisión real. El informe reproducible
[recovery-results.json](recovery-results.json) registra comando, versiones,
commit base, métodos de fallo, UUID y resultados sin contraseñas. Se regenera
en cada ejecución y puede versionarse junto con el código.

## Respaldos lógicos y físicos

`backup.py` genera y verifica respaldos de ambos nodos sin recrearlos:

```sh
ops/.venv/bin/python -B ops/backup.py create
ops/.venv/bin/python -B ops/backup.py verify ops/backups/<ID>
ops/.venv/bin/python -B ops/backup.py restore-test ops/backups/<ID>
```

Los archivos quedan separados por nodo dentro de `ops/backups/`, fuera de Git.
La prueba de restauración lógica usa instancias temporales sin red ni puertos.
Ver [BACKUPS.md](BACKUPS.md) para configuración, formatos, comandos de
restauración lógica y física, alcance y resultados de la validación.

No se implementan archivado WAL, PITR ni reincorporación. La recuperación 2PC
no reconstruye ramas perdidas ni ofrece atomicidad de lectura entre nodos
durante la segunda fase.
