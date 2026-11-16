# Base distribuida de SIG-TEC

La instalación local usa seis bases `sig_tec`: un nodo central y los campus Cartago, San José, San Carlos, Alajuela y Limón. Cada campus es dueño de sus ocho tablas físicas. Las vistas `sig` reúnen los datos propios y las copias recibidas por replicación lógica. El central sirve la autenticación y recibe los datos de los cinco campus. [Contrato de datos](../docs/diseno.md) · [Criterios de aceptación](../docs/validacion.md)

| Nodo | Puerto local | Cuenta de demostración | Contraseña en `.env` |
| --- | ---: | --- | --- |
| Central | `55430` | Las cinco cuentas | `SIGTEC_ADMIN_PASSWORD` para administrar |
| Cartago | `55431` | `demo_cartago` | `SIGTEC_CARTAGO_PASSWORD` |
| San José | `55432` | `demo_san_jose` | `SIGTEC_SAN_JOSE_PASSWORD` |
| San Carlos | `55433` | `demo_san_carlos` | `SIGTEC_SAN_CARLOS_PASSWORD` |
| Alajuela | `55434` | `demo_alajuela` | `SIGTEC_ALAJUELA_PASSWORD` |
| Limón | `55435` | `demo_limon` | `SIGTEC_LIMON_PASSWORD` |

## Arranque en Windows

Desde la raíz del repositorio, copiar `.env.example` a `.env` y establecer siete contraseñas locales distintas: la de administración, la de replicación y una por campus. Usar valores alfanuméricos de al menos 24 caracteres. `.env` está excluido de Git.

```powershell
Copy-Item .env.example .env
notepad .env
docker compose up -d --wait
docker compose run --rm bootstrap
docker compose run --rm bootstrap /db/smoke.sh
```

El primer bootstrap crea PostGIS, ocho tablas por campus, cuentas, vistas, publicaciones, slots y suscripciones. Cada campus carga un objeto ficticio por capa; después de la sincronización hay cinco filas en cada vista y 40 IDs globales distintos. El script SQL abre conexiones TCP con las cinco cuentas, verifica geometría, SRID, autenticación, permisos, transacciones y CRUD temporal en las 40 combinaciones campus/capa. Comprueba que cada alta, cambio y baja converge en el central y en los otros cuatro campus. Las pruebas no cambian las filas de muestra. Puede tardar varios minutos.

El bootstrap se puede repetir después de una interrupción. Conservar las mismas contraseñas de `.env`: las suscripciones guardan sus credenciales al crearse. Para verificar la repetición, ejecutar de nuevo los dos últimos comandos. `db/smoke.sh` exige cinco suscripciones activas en el central y una en cada campus, sin duplicados; el inventario final debe seguir en 40 filas. Las secuencias sí avanzan por los IDs temporales utilizados durante la prueba.

## QGIS 3.44 LTR

El script usa el proveedor PostgreSQL de QGIS, lee las contraseñas de `.env` y abre las ocho vistas de cada uno de los cinco campus. Ejecuta altas, cambios de atributos y geometría, intentos de edición ajena y bajas temporales distribuidas entre las ocho capas. Desde PowerShell:

```powershell
& 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat' 'db/qgis_smoke.py'
```

Ajustar la ruta si se instaló otra revisión de QGIS 3.44 LTR. El script prueba las vistas directamente; no depende del complemento de Joyce. La prueba de inicio de sesión, carga automática y estilos desde el complemento se realiza al integrar el PR de Joyce.

Para inspeccionar las capas en QGIS Desktop, crear una conexión PostgreSQL por campus con `127.0.0.1`, la base `sig_tec`, el puerto y la cuenta de la tabla. Abrir las ocho vistas del esquema `sig`, seleccionar `geom` como columna geométrica e `id` como clave única. Cada sesión debe mostrar un objeto de cada campus por capa. La edición de un objeto ajeno debe devolver un error de permisos. [Conexiones PostgreSQL en QGIS](https://docs.qgis.org/3.44/en/docs/user_manual/managing_data_source/supported_data.html#postgresql-database)

## Repetición, desconexión y diagnóstico

Los siguientes comandos muestran el estado de los seis servicios y las suscripciones. Cada campus tiene una suscripción al central que combina cuatro publicaciones de datos remotos y la de estilos. El central tiene una suscripción hacia cada campus.

```powershell
docker compose ps
docker compose exec central psql -U postgres -d sig_tec -c 'SELECT subname, subenabled FROM pg_subscription ORDER BY subname'
docker compose exec central psql -U postgres -d sig_tec -c 'SELECT slot_name, active FROM pg_replication_slots ORDER BY slot_name'
docker compose exec san_carlos psql -U postgres -d sig_tec -c 'SELECT subname, subenabled FROM pg_subscription ORDER BY subname'
```

Para la prueba de convergencia tras desconexión, detener San Carlos, insertar desde la vista de Cartago un edificio temporal y confirmar que aparece en el central. Arrancar San Carlos y sondear `sig.edificios` hasta que vea el mismo ID. Borrar después la fila desde Cartago y comprobar la baja en ambos destinos. Usar `docker compose stop san_carlos` y `docker compose start san_carlos`; detener un nodo no elimina su volumen ni sus slots.

La comprobación de que una **semilla eliminada no reaparece** requiere modificar una fila de muestra. Hacerla en una copia descartable de los volúmenes: guardar una fila propia en una tabla auxiliar, eliminarla de su tabla física, repetir `docker compose run --rm bootstrap` y verificar que sigue ausente en origen y destinos. Restaurar la fila desde la copia auxiliar y esperar la replicación si se desea conservar esa instalación. El marcador `sig.seed_aplicada` impide que el bootstrap vuelva a sembrarla. La repetición habitual de `db/smoke.sh` verifica los conteos y la estabilidad de las suscripciones sin eliminar semillas.
