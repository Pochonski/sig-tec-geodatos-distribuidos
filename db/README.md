# Primer corte de la base distribuida

Este corte levanta Cartago, el nodo central y San Carlos con la capa `sig.edificios`. Las tres bases se llaman `sig_tec` y escuchan en `127.0.0.1:55431`, `127.0.0.1:55430` y `127.0.0.1:55433`, respectivamente. Cada nodo conserva su propio volumen. [Diseño completo](../docs/diseno.md)

## Arranque en Windows

1. Copiar `.env.example` a `.env` en la raíz y llenar las cuatro contraseñas con valores alfanuméricos distintos de 24 caracteres o más. El archivo `.env` está excluido de Git.
2. Desde la raíz del repositorio, ejecutar:

   ```powershell
   docker compose up -d --wait
   docker compose run --rm bootstrap
   docker compose run --rm bootstrap /db/smoke.sh
   ```

El bootstrap crea extensiones, tablas, cuentas, vistas, publicaciones, slots y suscripciones. Sincroniza primero las tablas originales en el central y después las copias de consulta en los campus. Se puede repetir después de una interrupción conservando los volúmenes. La semilla se aplica una vez por campus, incluso si un edificio de prueba se borra luego.

Al repetir el bootstrap con volúmenes existentes, conservar las mismas contraseñas en `.env`. Las conexiones de replicación guardan la contraseña usada al crear cada suscripción; cambiarlas requiere actualizar también esas conexiones.

Los dos usuarios de prueba son `demo_cartago` y `demo_san_carlos`. Cada uno usa la contraseña de su variable en `.env`, se autentica en el central mediante `auth.mi_campus()` y edita la vista de su propio nodo. La vista contiene los dos edificios originales. La tabla `public.layer_styles` queda preparada para que Joyce publique los estilos en el central.

## Prueba con QGIS 3.44 LTR

El script usa el proveedor PostgreSQL de la instalación de QGIS y realiza altas, cambios de atributos y geometría, intento de edición ajena y bajas en ambos campus. Desde PowerShell:

```powershell
Get-Content .env | ForEach-Object {
    $name, $value = $_ -split '=', 2
    if ($name -in @('SIGTEC_CARTAGO_PASSWORD', 'SIGTEC_SAN_CARLOS_PASSWORD')) {
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}
& 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat' 'db/qgis_smoke.py'
```

Ajustar la ruta del ejecutable si QGIS 3.44 LTR está instalado en otra carpeta o revisión.

Para inspeccionar las capas en QGIS Desktop, crear una conexión PostgreSQL para cada campus con la base `sig_tec`, el puerto correspondiente y su usuario de prueba. Elegir `sig.edificios`, la columna geométrica `geom` y `id` como clave de la vista. La edición de una fila del otro campus debe producir un error de permisos. [Capas PostgreSQL en QGIS](https://docs.qgis.org/3.44/en/docs/user_manual/managing_data_source/supported_data.html#postgresql-database)

## Comprobaciones y diagnóstico

La prueba SQL abre conexiones TCP con las cuentas reales y verifica autenticación, permisos de las vistas, CRUD en ambos sentidos, `ROLLBACK` y convergencia de los dos saltos. El bootstrap espera hasta 60 segundos por cada suscripción e informa qué nodo sigue sincronizando. Para inspeccionar el estado:

```powershell
docker compose ps
docker compose exec central psql -U postgres -d sig_tec -c 'SELECT subname, subenabled FROM pg_subscription'
docker compose exec central psql -U postgres -d sig_tec -c 'SELECT slot_name, active FROM pg_replication_slots'
```

Para demostrar la recuperación de una desconexión, detener San Carlos, insertar un edificio en la vista de Cartago y arrancar de nuevo San Carlos. El central recibe el cambio durante la desconexión y San Carlos lo recibe al reconectarse. Repetir el bootstrap después de la prueba conserva los datos y las suscripciones.
