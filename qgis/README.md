# QGIS: complemento, estilos y pruebas

Esta carpeta contiene la parte de QGIS de SIG-TEC:

- el complemento PyQGIS que inicia sesión y carga las ocho capas;
- los estilos QML compartidos;
- la herramienta que publica los estilos en el central;
- un entorno de prueba independiente de la base común.

[Diseño](../docs/diseno.md) · [Validación](../docs/validacion.md) · [Reparto](../docs/reparto.md)

| Ruta | Contenido |
| --- | --- |
| `sig_tec/` | Complemento para QGIS 3.40 o posterior. Valida la cuenta en el central, conecta al campus asignado y carga las vistas `sig`. |
| `sig_tec/estilos/` | Un QML por vista con simbología, etiquetas, alias, e `id` y `campus_id` de solo lectura. Se usan de respaldo si la base no tiene estilo. |
| `herramientas/publicar_estilos.py` | Genera el SQL que deja cada QML como único estilo predeterminado en `public.layer_styles`. |
| `entorno-prueba/` | Proyecto Compose `sig-tec-qgis` con un central simulado y los campus de Cartago, San José y San Carlos. |
| `pruebas/` | Pruebas con Python estándar, pruebas SQL de permisos y pruebas de integración con PyQGIS. `entornos.py` define cómo conectarse al simulador y a la base integrada. |

## Entorno de prueba (simulador)

Requiere Docker. Desde la raíz del repositorio:

```sh
docker compose -f qgis/entorno-prueba/compose.yaml up -d --wait
python qgis/herramientas/publicar_estilos.py | docker compose -f qgis/entorno-prueba/compose.yaml exec -T central psql -q -U postgres -d sig_tec -v ON_ERROR_STOP=1
```

| Nodo | Puerto | Contenido |
| --- | --- | --- |
| Central | `56430` | `auth.mi_campus()`, `public.layer_styles` y la publicación `estilos` |
| Cartago (`1`) | `56431` | Cinco esquemas de campus, ocho vistas `sig` editables y la suscripción a los estilos |
| San José (`2`) | `56432` | Igual que Cartago, con San José como campus local |
| San Carlos (`3`) | `56433` | Igual que Cartago, con San Carlos como campus local |

La semilla carga un objeto por capa y campus en cada nodo, 40 objetos en total, en EPSG:8908. Las cuentas usan la contraseña `sigtec-prueba`. Para cambiar contraseñas o puertos, copiar `entorno-prueba/.env.example` a `entorno-prueba/.env`.

| Cuenta | Central | Campus |
| --- | --- | --- |
| `cartago_prueba` | Asignada a Cartago | Existe en Cartago |
| `san_jose_prueba` | Asignada a San José | Existe en San José |
| `san_carlos_prueba` | Asignada a San Carlos | Existe en San Carlos |
| `sin_campus_prueba` | Sin asignación | No existe en ningún campus |

`docker compose -f qgis/entorno-prueba/compose.yaml down -v` borra los volúmenes, y el siguiente `up` vuelve a crear el entorno desde cero.

El simulador aplica las reglas del diseño, pero no reemplaza la base de Joseph:

- Las vistas hacen `UNION ALL` de los cinco esquemas.
- Un disparador `INSTEAD OF` escribe solo en el esquema local. Lo hace mediante una función `SECURITY DEFINER` cuyo propietario es un rol `NOLOGIN`.
- El `id` sale de la secuencia del campus, que empieza en `campus_id` y avanza de cinco en cinco.
- Las copias de otros campus son datos fijos de la semilla, porque el simulador no replica capas.

## Instalar y usar el complemento

1. Enlazar la carpeta `sig_tec` en el perfil de QGIS, para que los cambios del repositorio se vean al recargar. En Windows, desde la raíz del repositorio en PowerShell:

   ```powershell
   New-Item -ItemType Junction -Path "$env:APPDATA\QGIS\QGIS3\profiles\default\python\plugins\sig_tec" -Target (Resolve-Path qgis\sig_tec)
   ```

   En Linux, el destino es `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/sig_tec`.
2. Abrir QGIS y activar **SIG-TEC** en *Complementos › Administrar e instalar complementos*. El menú *Base de datos › SIG-TEC* ofrece **Iniciar sesión** y **Cerrar sesión**.
3. En el diálogo, abrir **Conexión** y poner el puerto base `56430` para el simulador. La base integrada usa `55430`, que es el valor predeterminado.

Al iniciar sesión, el complemento:

1. Conecta al central con `psycopg2` (incluido en QGIS para Windows y en la imagen `qgis/qgis`) o con `psycopg`, y consulta `auth.mi_campus()`.
2. Comprueba la misma cuenta en el puerto `base + campus_id`.
3. Guarda la contraseña en el gestor de autenticación de QGIS como configuración `authcfg` llamada `SIG-TEC <usuario>`. Si todavía no hay contraseña maestra, QGIS pide crearla.
4. Agrega las capas en el grupo `SIG-TEC · <campus>`, con `id` como clave y `geom` como geometría, y acerca el mapa a los objetos del campus.

Si alguna vista no abre, no agrega ninguna capa.

| Situación | Mensaje |
| --- | --- |
| Contraseña incorrecta o cuenta inexistente | Usuario o contraseña incorrectos |
| Cuenta sin campus en el central | La cuenta no tiene un campus asignado |
| El central no responde | El servidor central no está disponible |
| El campus no responde | El nodo de `<campus>` no está disponible |
| El campus rechaza la cuenta | La cuenta debe existir con la misma contraseña en el central y en su campus |

### Política de sesión

Cada proyecto tiene **una sola sesión de SIG-TEC**. Al iniciar sesión, sea con la misma cuenta, con otra o en otro campus, el complemento retira todas las capas de la sesión anterior antes de agregar las nuevas. **Cerrar sesión** las retira sin agregar otras.

- Las capas y el grupo se reconocen por una propiedad propia del complemento, no por el nombre. Por eso también se retiran si se movieron, se renombraron o se duplicaron.
- Ninguna capa de la cuenta anterior queda en el proyecto, de modo que ninguna sigue editable con esas credenciales.

Si alguna capa de la sesión tiene ediciones sin guardar, el complemento pregunta qué hacer antes de retirarla:

| Respuesta | Resultado |
| --- | --- |
| **Guardar** | Confirma las ediciones y continúa. Si la base rechaza alguna, por ejemplo una edición ajena, no se retira ninguna capa, la edición sigue pendiente y se muestra el error. |
| **Descartar** | Revierte las ediciones y continúa. |
| **Cancelar** | No cambia nada: las capas, los grupos y las ediciones pendientes quedan como estaban. |

La validación de la cuenta y la apertura de las vistas nuevas ocurren antes de la pregunta. Así, una contraseña incorrecta o un nodo caído tampoco cambian el proyecto.

## Estilos

Cada vista usa el estilo `SIG-TEC` predeterminado de `public.layer_styles`. QGIS lo encuentra por base, esquema, vista y columna geométrica (`sig_tec`, `sig`, `<vista>`, `geom`). Si la base no tiene ese estilo, el complemento aplica el QML de `sig_tec/estilos/` y lo indica con un aviso.

Para cambiar un estilo:

1. Ajustar la capa en QGIS y guardarla con *Propiedades › Estilo › Guardar estilo › Como archivo de estilo QGIS* en `qgis/sig_tec/estilos/<vista>.qml`. Incluir las categorías Simbología, Etiquetas, Campos y Formularios.
2. Ejecutar `python -m unittest discover -s qgis/pruebas` para comprobar que el QML sigue el diccionario de capas.
3. Publicar en el central. Sin argumentos se publican las ocho vistas, y también se pueden indicar algunas, por ejemplo `python qgis/herramientas/publicar_estilos.py edificios`.
4. Volver a cargar la capa en cada campus cuando llegue la réplica.

La publicación corre en una transacción y bloquea `layer_styles`, así que dos publicaciones simultáneas no pueden crear la misma fila. Al terminar, cada vista tiene exactamente una fila `SIG-TEC` y es su único estilo predeterminado:

- elimina los `SIG-TEC` duplicados y conserva el de menor `id`;
- deja de marcar como predeterminados los demás estilos de la vista, sin borrarlos.

En la base integrada se publica con la cuenta de administración del central:

```sh
python qgis/herramientas/publicar_estilos.py | docker compose exec -T central psql -q -U postgres -d sig_tec -v ON_ERROR_STOP=1
```

## Pruebas

Las pruebas que se conectan a una base eligen el entorno con `SIG_TEC_ENTORNO`. La configuración de cada entorno está en `pruebas/entornos.py`.

| Entorno | `SIG_TEC_ENTORNO` | Puerto base | Cuentas | Contraseñas |
| --- | --- | --- | --- | --- |
| Simulador | `simulador` (predeterminado) | `56430` | `*_prueba` | `CLAVE_PRUEBA` de `qgis/entorno-prueba/.env`, o `sigtec-prueba` |
| Base integrada | `integracion` | `55430` | `demo_cartago` … `demo_limon` | `SIGTEC_<CAMPUS>_PASSWORD` del `.env` de la raíz |

Las contraseñas de la integración se leen del `.env` o de variables de entorno y no se imprimen. La prueba exige que las cinco sean distintas. Otras variables de entorno:

- `SIG_TEC_HOST`: servidor de los nodos (`127.0.0.1` por omisión).
- `SIG_TEC_PROYECTO_COMPOSE`: proyecto Compose de los nodos. Por omisión es `sig-tec-qgis` en el simulador y el nombre de la carpeta del repositorio en la integración.
- `SIG_TEC_ENV`: otro archivo `.env` para la integración.

Cambiar el puerto base no basta para pasar del simulador a la integración, porque las cuentas y las contraseñas son distintas.

| Prueba | Requiere | Cubre |
| --- | --- | --- |
| `test_contrato.py` | Python estándar | Puertos, clasificación de errores, diccionario de capas, QML y SQL de publicación |
| `test_estilos_bd.py` | Python estándar, Docker y el entorno levantado | Crea filas `SIG-TEC` duplicadas y otro estilo predeterminado, vuelve a publicar, y verifica una sola fila `SIG-TEC` predeterminada por vista en el central y en cada campus |
| `test_qgis.py` | Python de QGIS y el entorno levantado | Inicio de sesión correcto e incorrecto, cuenta sin campus, central caído, ocho capas válidas con estilo compartido, CRUD, rechazo de edición ajena, reinicio con edición pendiente (cancelar, guardar con fallo, guardar) y cambio de Cartago a San José descartando la edición |
| `entorno-prueba/pruebas/*.sql` | Simulador | Permisos en SQL: inventario, CRUD local, rechazo de escrituras ajenas o directas, y `auth.mi_campus()` |

Python estándar, desde la raíz del repositorio. Las pruebas que necesitan QGIS o contenedores apagados se omiten:

```sh
python -m unittest discover -s qgis/pruebas -v
SIG_TEC_ENTORNO=integracion python -m unittest discover -s qgis/pruebas -v
```

QGIS 3.44 en Windows, desde la consola de OSGeo4W (`set SIG_TEC_ENTORNO=integracion` para la integración):

```bat
python-qgis-ltr qgis\pruebas\test_qgis.py
```

QGIS 3.44 en Docker, con la imagen oficial y los nodos publicados en el anfitrión:

```sh
docker run --rm -v "$PWD:/repo:ro" -e SIG_TEC_HOST=host.docker.internal -e QT_QPA_PLATFORM=offscreen -e HOME=/tmp \
  -e SIG_TEC_ENTORNO=integracion qgis/qgis:3.44.15 python3 /repo/qgis/pruebas/test_qgis.py
```

Pruebas SQL del simulador (cambiar `cartago` y `cartago_prueba` por el campus deseado):

```sh
docker compose -f qgis/entorno-prueba/compose.yaml exec -T -e PGPASSWORD=sigtec-prueba cartago psql -h 127.0.0.1 -U cartago_prueba -d sig_tec -q -f /pruebas/campus.sql
docker compose -f qgis/entorno-prueba/compose.yaml exec -T -e PGPASSWORD=sigtec-prueba central psql -h 127.0.0.1 -U cartago_prueba -d sig_tec -q -v campus_esperado=1 -f /pruebas/central.sql
```

En Git Bash para Windows, anteponer `MSYS_NO_PATHCONV=1` para que no reescriba las rutas `/pruebas` y `/repo`.

Las pruebas de QGIS usan una base de autenticación temporal y requieren los estilos publicados. Reconocen un rechazo de edición sin leer el texto del error: QGIS no puede confirmar el cambio y la fila sigue igual al leerla con una conexión nueva. Las filas temporales se registran para borrarse con `addCleanup`, de modo que se eliminan aunque falle una aserción después del alta.

En la demostración de [validación](../docs/validacion.md) faltan las capturas manuales del inicio de sesión, la edición y el cambio de estilo visto desde dos campus.

## Contrato con la base común

El complemento espera de cada instalación:

- La base `sig_tec` en todos los nodos, con el central en el puerto base y cada campus en `base + campus_id`.
- En el central, `auth.mi_campus()` sin argumentos, que devuelve el `smallint` del `session_user` o `NULL` si la cuenta no tiene campus. Las cuentas del complemento pueden ejecutarla.
- La misma cuenta y contraseña en el central y en su campus.
- En cada campus, las ocho vistas `sig.<capa>` con `id`, `campus_id`, los atributos del diccionario y `geom` tipada con SRID 8908, con permiso de lectura y edición para las cuentas del campus.
- `public.layer_styles` con la estructura de QGIS, replicada desde el central y de solo lectura en los campus. Si un campus guardara estilos localmente, sus filas chocarían con las replicadas y la suscripción se detendría.

El complemento no depende del texto ni del SQLSTATE de los rechazos de edición. QGIS muestra el error que devuelve la base.
