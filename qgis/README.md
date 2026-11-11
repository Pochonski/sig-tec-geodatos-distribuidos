# QGIS: complemento, estilos y pruebas

Esta carpeta contiene la parte de QGIS de SIG-TEC. Incluye el complemento PyQGIS que inicia sesión y carga las ocho capas, los estilos QML compartidos, la herramienta que los publica en el central y un entorno de prueba independiente de la base común. [Diseño](../docs/diseno.md) · [Validación](../docs/validacion.md) · [Reparto](../docs/reparto.md)

| Ruta | Contenido |
| --- | --- |
| `sig_tec/` | Complemento para QGIS 3.40 o posterior. Valida la cuenta en el central, conecta al campus asignado y carga las vistas `sig`. |
| `sig_tec/estilos/` | Un QML por vista con simbología, etiquetas, alias y `id` y `campus_id` de solo lectura. Sirven de respaldo si la base no tiene estilo. |
| `herramientas/publicar_estilos.py` | Genera el SQL que deja cada QML como estilo predeterminado en `public.layer_styles`. |
| `entorno-prueba/` | Proyecto Compose `sig-tec-qgis` con un central y los campus de Cartago y San Carlos simulados. |
| `pruebas/` | Pruebas del contrato con Python estándar, pruebas SQL de permisos y prueba de integración con PyQGIS. |

## Entorno de prueba

Requiere Docker. Desde la raíz del repositorio:

```sh
docker compose -f qgis/entorno-prueba/compose.yaml up -d --wait
python qgis/herramientas/publicar_estilos.py | docker compose -f qgis/entorno-prueba/compose.yaml exec -T central psql -q -U postgres -d sig_tec -v ON_ERROR_STOP=1
```

| Nodo | Puerto | Contenido |
| --- | --- | --- |
| Central | `56430` | `auth.mi_campus()`, `public.layer_styles` y la publicación `estilos` |
| Cartago (`1`) | `56431` | Cinco esquemas de campus, ocho vistas `sig` editables y suscripción a los estilos |
| San Carlos (`3`) | `56433` | Igual que Cartago, con San Carlos como campus local |

La semilla carga un objeto por capa y campus en cada nodo, 40 objetos en total, en EPSG:8908. Las cuentas usan la contraseña `sigtec-prueba`. Para cambiar contraseñas o puertos, copiar `entorno-prueba/.env.example` a `entorno-prueba/.env`.

| Cuenta | Central | Campus |
| --- | --- | --- |
| `cartago_prueba` | Asignada a Cartago | Existe en Cartago |
| `san_carlos_prueba` | Asignada a San Carlos | Existe en San Carlos |
| `sin_campus_prueba` | Sin asignación | No existe en ningún campus |

`docker compose -f qgis/entorno-prueba/compose.yaml down -v` borra los volúmenes. El siguiente `up` vuelve a crear el entorno desde cero.

El campus simulado aplica las reglas del diseño, aunque no reemplaza la base de Joseph. Las vistas hacen `UNION ALL` de los cinco esquemas. Un disparador `INSTEAD OF` con una función `SECURITY DEFINER`, propiedad de un rol `NOLOGIN`, escribe solo en el esquema local. El `id` sale de la secuencia del campus, que empieza en `campus_id` y avanza de cinco en cinco. Las copias de otros campus son datos fijos de la semilla porque el entorno no replica capas.

## Instalar el complemento

1. Enlazar la carpeta `sig_tec` en el perfil de QGIS para que los cambios del repositorio se vean al recargar. En Windows, desde la raíz del repositorio en PowerShell:

   ```powershell
   New-Item -ItemType Junction -Path "$env:APPDATA\QGIS\QGIS3\profiles\default\python\plugins\sig_tec" -Target (Resolve-Path qgis\sig_tec)
   ```

   En Linux, el destino es `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/sig_tec`.
2. Abrir QGIS, activar **SIG-TEC** en *Complementos › Administrar e instalar complementos* y usar el botón de la barra o *Base de datos › SIG-TEC*.
3. En el diálogo, abrir **Conexión** y poner el puerto base `56430` para el entorno de prueba. La integración usa `55430`, que es el valor predeterminado.

El complemento conecta al central con `psycopg2`, incluido en QGIS para Windows, o con `psycopg`. Primero consulta `auth.mi_campus()` y después comprueba la misma cuenta en el puerto `base + campus_id`. La contraseña queda en el gestor de autenticación de QGIS como configuración `authcfg` llamada `SIG-TEC <usuario>`. Si todavía no existe, QGIS pide crear la contraseña maestra. Las capas se agregan en el grupo `SIG-TEC · <campus>` con `id` como clave y `geom` como geometría, y el mapa se acerca a los objetos del campus. Si alguna vista no abre, el complemento no agrega ninguna.

| Situación | Mensaje |
| --- | --- |
| Contraseña incorrecta o cuenta inexistente | Usuario o contraseña incorrectos |
| Cuenta sin campus en el central | La cuenta no tiene un campus asignado |
| El central no responde | El servidor central no está disponible |
| El campus no responde | El nodo de `<campus>` no está disponible |
| El campus rechaza la cuenta | La cuenta debe existir con la misma contraseña en el central y en su campus |

## Estilos

Cada vista usa el estilo `SIG-TEC` predeterminado de `public.layer_styles`. QGIS lo encuentra por base, esquema, vista y columna geométrica (`sig_tec`, `sig`, `<vista>`, `geom`). Si la base no tiene ese estilo, el complemento aplica el QML de `sig_tec/estilos/` y lo indica con un aviso.

Para cambiar un estilo:

1. Ajustar la capa en QGIS y guardarla con *Propiedades › Estilo › Guardar estilo › Como archivo de estilo QGIS* en `qgis/sig_tec/estilos/<vista>.qml`. Incluir las categorías Simbología, Etiquetas, Campos y Formularios.
2. Ejecutar `python -m unittest discover -s qgis/pruebas` para comprobar que el QML sigue el diccionario de capas.
3. Publicar en el central. Sin argumentos se publican las ocho vistas. También se pueden indicar algunas, por ejemplo `python qgis/herramientas/publicar_estilos.py edificios`. La herramienta reemplaza el estilo `SIG-TEC` existente y deja de marcar como predeterminados los demás estilos de la vista.
4. Volver a cargar la capa en cada campus cuando llegue la réplica.

En la integración se publica con la cuenta administrativa del central:

```sh
python qgis/herramientas/publicar_estilos.py --salida estilos.sql
psql -h 127.0.0.1 -p 55430 -U <cuenta-administrativa> -d sig_tec -v ON_ERROR_STOP=1 -f estilos.sql
```

## Pruebas

| Prueba | Comando | Cubre |
| --- | --- | --- |
| Contrato | `python -m unittest discover -s qgis/pruebas -v` | Puertos, clasificación de errores, diccionario de capas, QML y SQL de publicación. La prueba de QGIS se omite sin PyQGIS. |
| Campus | `docker compose -f qgis/entorno-prueba/compose.yaml exec -T -e PGPASSWORD=sigtec-prueba cartago psql -h 127.0.0.1 -U cartago_prueba -d sig_tec -q -f /pruebas/campus.sql` | Inventario de 8 × 5 objetos, CRUD local y rechazo de edición ajena, cambio de `campus_id`, escritura directa y escritura en `layer_styles`. Se revierte al terminar. |
| Central | `docker compose -f qgis/entorno-prueba/compose.yaml exec -T -e PGPASSWORD=sigtec-prueba central psql -h 127.0.0.1 -U cartago_prueba -d sig_tec -q -v campus_esperado=1 -f /pruebas/central.sql` | `auth.mi_campus()` devuelve el campus de la cuenta y el registro de asignaciones queda oculto. Con `sin_campus_prueba`, usar `-v campus_esperado=`. |
| QGIS | `python-qgis-ltr qgis/pruebas/test_qgis.py` desde la consola de OSGeo4W | Inicio de sesión correcto e incorrecto, central caído, ocho capas válidas con estilo compartido en Cartago y San Carlos, CRUD desde QGIS y rechazo de edición ajena. |

Para San Carlos, cambiar `cartago` por `san-carlos` y `cartago_prueba` por `san_carlos_prueba`. La prueba de QGIS usa una base de autenticación temporal. Requiere el entorno levantado y los estilos publicados. Con `SIG_TEC_PUERTO_BASE=55430` se ejecuta contra la integración.

En la demostración de [validación](../docs/validacion.md) faltan las capturas manuales del inicio de sesión, la edición y el cambio de estilo visto desde los dos campus.

## Contrato con la base común

El complemento espera esto de cada instalación:

- Base `sig_tec` en todos los nodos, con el central en el puerto base y cada campus en `base + campus_id`.
- En el central, `auth.mi_campus()` sin argumentos devuelve el `smallint` del `session_user`, o `NULL` si la cuenta no tiene campus. Las cuentas del complemento pueden ejecutarla.
- La misma cuenta y contraseña en el central y en su campus.
- En cada campus, las ocho vistas `sig.<capa>` con `id`, `campus_id`, los atributos del diccionario y `geom` tipada con SRID 8908, más permiso de lectura y edición para las cuentas del campus.
- `public.layer_styles` con la estructura de QGIS, replicada desde el central y de solo lectura en los campus. Si un campus guarda estilos localmente, sus filas chocan con las replicadas y la suscripción se detiene.
