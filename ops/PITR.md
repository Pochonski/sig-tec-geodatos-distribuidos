# PITR real de Cartago hasta un punto nombrado

Esta prueba restaura **una copia nueva** de un respaldo físico PostgreSQL 17.
Los nodos originales permanecen activos. No reincorpora la copia, no configura
replicación y no restaura datos sobre Central o Cartago.

## Ejecutar

Desde la raíz, con las dependencias de `ops/requirements.txt`, Docker y las
credenciales locales existentes en `ops/.env`:

```sh
ops/.venv/bin/python -B ops/wal.py preflight
ops/.venv/bin/python -B ops/test_pitr.py
```

`test_pitr.py` ejecuta primero cuatro pruebas de seguridad sin modificar bases.
Si pasan, ejecuta una prueba real completa. Para ejecutar solo el escenario real:

```sh
ops/.venv/bin/python -B ops/pitr.py run
```

Cada ejecución usa un UUID, edificio, respaldo y directorio nuevos. No ejecutar
ambos comandos seguidos salvo que se quiera hacer dos pruebas independientes.
No reutilizar una copia que ya completó recovery para probar de nuevo PITR.

Trabajar sin otros escritores o coordinadores durante la prueba. El preflight
exige la rama correcta, nodos accesibles, PostgreSQL 17, espacio suficiente,
ningún GID preparado ni operación 2PC incompleta, durabilidad habilitada,
archivado activo y cero fallos del archivador. Verifica los respaldos previos
con `pg_restore --list` y `pg_verifybackup` en modo de lectura. Si alguna
comprobación falla, se detiene antes de insertar el edificio.

## Secuencia implementada

1. Guarda el inventario y hashes de todas las tablas de ambos nodos y el estado
   de sus contenedores y de wger. Registra hashes de los WAL ya archivados.
2. Inserta en Cartago un edificio ficticio con `campus_id=1` y un ID `bigint`
   nuevo de la clase de Cartago (`1 módulo 5`). `ON CONFLICT DO NOTHING` evita
   sobrescribir filas; reintenta con otro ID si hay colisión. Nunca modifica `id=1`.
3. Usa `backup.create(['cartago'], 'physical', publish_summary=False)` para crear
   un respaldo completo nuevo, con `pg_basebackup` y `pg_verifybackup`.
   `backup.py` ahora devuelve su directorio; sus comandos anteriores conservan
   su comportamiento. No se sustituye `backup-results.json` de la etapa previa.
4. Solo después de verificar el respaldo crea el punto único mediante
   `pg_create_restore_point()`. Exige que su LSN sea posterior al fin del respaldo.
5. Elimina exactamente el fixture por ID, campus y nombre y confirma esa única
   eliminación. Guarda el LSN confirmado posterior y ejecuta `pg_switch_wal()`.
6. A partir del manifiesto del respaldo calcula toda la secuencia de segmentos
   necesaria, incluidos cambios de número de log. Espera que estén archivados,
   verifica sus tamaños y SHA-256 y analiza el rango con `pg_waldump`. Se detiene
   si aumenta `failed_count` o faltan segmentos.
7. Copia el PGDATA del respaldo verificado a `ops/pitr-runs/<UUID>/pgdata`.
   Valida que el origen esté en `ops/backups/`, el destino sea nuevo y esté dentro
   del aislamiento, y que no se escriba dentro del respaldo original.
8. Crea `recovery.signal` y agrega configuración **solo a esa copia**:

```text
archive_mode = off
archive_command = ''
listen_addresses = ''
hot_standby = on
max_prepared_transactions = 10
primary_conninfo = ''
primary_slot_name = ''
restore_command = '/bin/cp -- "/wal-archive/%f" "%p"'
recovery_target_name = 'sig_tec_pitr_<UUID>'
recovery_target_timeline = 'current'
recovery_target_action = 'pause'
```

9. Ejecuta la misma imagen del nodo fuente en un contenedor temporal con
   `--network none`, sin puertos, PGDATA como bind de la copia nueva y el volumen
   `sig-tec-ops_cartago_wal` montado **en solo lectura**. No se monta PGDATA de
   ningún nodo original. El clon no recibe credenciales por argumentos ni entorno;
   las consultas de comprobación usan exclusivamente su socket local.
10. Espera `pg_is_in_recovery()=true` y estado de reproducción `paused`. Exige que
    los logs indiquen `recovery stopping at restore point` con el nombre exacto
    y la lectura desde el archivo del segmento que contiene ese punto.
    Comprueba que `LSN_punto ≤ LSN_reproducido < LSN_eliminación_confirmada`.
11. Comprueba los atributos del edificio en la copia pausada. Solo entonces
    ejecuta `pg_wal_replay_resume()`, que permite terminar la recuperación en
    el objetivo, y espera `pg_is_in_recovery()=false`. No usa `pg_promote()` para
    eludir un objetivo que no se haya alcanzado.
12. Verifica la retirada de `recovery.signal`, el nuevo timeline de la copia y
    los hashes de todas sus tablas frente al estado posterior a insertar el
    fixture. En los originales exige los mismos hashes que antes de la prueba:
    el edificio sigue eliminado y todas las filas anteriores permanecen iguales.
13. Comprueba de nuevo el respaldo físico, los WAL anteriores y el inventario
    de los contenedores. Detiene y retira **solo el contenedor temporal nuevo**,
    conservando su PGDATA y logs para inspección. No elimina volúmenes.

La copia restaurada contiene el edificio; el Cartago original no. Esta diferencia
es el resultado esperado. El timeline nuevo existe únicamente en la copia
aislada; no se publica WAL desde ella ni se conecta al resto del proyecto.

## Artefactos, evidencia y fallos

- `ops/pitr-results.json`: informe sin contraseñas, punto/LSN, edificio ficticio,
  respaldo usado, segmentos y hashes, líneas de log relevantes y comprobaciones.
- `ops/backups/<ejecución>/cartago/physical/`: nuevo respaldo y manifiesto
  verificados; el script nunca escribe encima de ellos para iniciar PostgreSQL.
- `ops/pitr-runs/<UUID>/`: copia nueva, `report.json` y `postgres.log` privados.
  Está excluido de Git. El entrypoint de PostgreSQL asigna la copia a su UID;
  puede requerir inspección mediante Docker para leer PGDATA desde el anfitrión.

Si la restauración falla, se conservan respaldo, copia y logs; el contenedor de
diagnóstico se deja detenido y su ID aparece en el informe. No se elimina ni
reinserta el fixture en una rama de manejo de errores ni se intenta reparar
ninguna base original. Si el fallo ocurre antes de la eliminación prevista,
el fixture propio puede permanecer en Cartago; el informe identifica la etapa.
No repetir la recuperación sobre esa copia parcialmente usada: conservarla
para diagnóstico. Un fallo de preflight no inicia el escenario ni crea fixtures.

El código CLI devuelve `0` si termina correctamente y `1` si no puede completar
la prueba. Las herramientas no imprimen contraseñas ni DSN. El respaldo físico
y los logs privados no deben publicarse: el respaldo contiene datos globales
del clúster y verificadores de contraseñas de los roles.

## Validación actualizada en seis nodos

La evidencia vigente en [pitr-results.json](pitr-results.json) corresponde al
modelo geográfico completo de Joseph y a la reincorporación de laboratorio
explicada en [INTEGRACION.md](INTEGRACION.md). Se comprobaron atributos y EWKB,
la pausa exacta por SQL/logs, lectura del archivo WAL y finalización en un nuevo
timeline. La copia conserva los límites de workers/conexiones del primario y
mantiene los workers lógicos desactivados durante la revisión aislada.

En perfil integrado el fixture se crea por sig.edificios con geometría válida
y la secuencia real; no se utiliza el INSERT mínimo sin geom. --keep-copy deja
la copia aislada para el paso posterior explícito. La copia aprobada se convirtió
en el reemplazo de laboratorio, mientras el respaldo y los WAL originales
permanecen sin modificaciones. Los logs y el primer intento fallido por límites
de workers se conservaron como diagnóstico. Windows real sigue pendiente.

Referencias PostgreSQL 17: [objetivos de recuperación](https://www.postgresql.org/docs/17/runtime-config-wal.html#RUNTIME-CONFIG-WAL-RECOVERY-TARGET),
[funciones de administración](https://www.postgresql.org/docs/17/functions-admin.html) y
[archivado continuo](https://www.postgresql.org/docs/17/continuous-archiving.html).
