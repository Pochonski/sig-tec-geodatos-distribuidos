# Reparto del trabajo

Las tres ramas parten del mismo commit de `main`. Cada integrante trabaja en las rutas que tiene a cargo y prueba su parte en un entorno propio. La primera integración reúne central, Cartago y San Carlos con la capa `edificios`. [Diseño acordado](diseno.md) · [Pruebas de aceptación](validacion.md)

## Responsables y ramas

| Integrante | Rama | Rutas | Entregables |
| --- | --- | --- | --- |
| Joseph | `joseph/base-distribuida` | `compose.yaml`, `.env.example`, `db/` | Instancias y volúmenes, modelo PostGIS, datos ficticios, cuentas y permisos, vistas editables y replicación en dos saltos. Prepara `public.layer_styles` para distribuir estilos e incorpora las migraciones y la configuración de operaciones en Compose. |
| Joyce | `joyce/qgis` | `qgis/` | Complemento PyQGIS para autenticación, selección del nodo y carga de capas. Estilos QML de las ocho capas, procedimiento para publicarlos en el central y pruebas de edición desde QGIS. |
| Armando | `armando/operaciones` | `ops/` | CLI del renombrado auditado con commit en dos fases, migraciones de auditoría, decisiones y marcadores. Scripts y procedimientos de respaldo, WAL, PITR y reincorporación de un nodo. |

## Primer entregable de Joseph

1. Levantar `central`, `cartago` y `san-carlos` con PostgreSQL 17 y PostGIS 3.6, cada uno con su volumen y la base `sig_tec`. Publicar en `127.0.0.1` los puertos `55430`, `55431` y `55433`, respectivamente. Documentar el arranque y los parámetros de prueba en `db/` y dejar valores de ejemplo en `.env.example`.
2. Crear primero la capa `edificios` y sus datos de prueba. Exponer `sig.edificios` con `id`, `campus_id`, `nombre`, `codigo`, `area`, `pisos` y `geom` de tipo `Polygon` en SRID `8908`. Preparar `auth.mi_campus()` en el central y una cuenta de prueba por campus para verificar acceso y edición.
3. Probar que un cambio local recorre campus → central → otro campus y que los disparadores rechazan editar filas ajenas. Entregar ese corte en el primer PR de la base. Después, extender la misma estructura a los otros tres campus y las siete capas restantes.

## Cómo empezar en paralelo

### Joyce

- Preparar en `qgis/` un entorno de prueba independiente con PostGIS. Empezar con una instancia central y una de Cartago. El central expone `auth.mi_campus()` sin argumentos y devuelve el `campus_id` de la cuenta autenticada. La cuenta también existe en Cartago. El nodo de Cartago expone `sig.edificios`, con un edificio propio y otro de San Carlos para probar permisos.
- Cargar la vista con `id` como clave y `geom` como geometría. Probar inicio de sesión correcto e incorrecto, CRUD local y rechazo de escritura ajena. Agregar después las otras siete vistas según el diccionario del diseño. Preparar los QML en `qgis/` y probar con un estilo predeterminado en `public.layer_styles`.
- Usar el proyecto Compose `sig-tec-qgis` y base de puertos `56430`, con el campus en `56430 + campus_id`. Hacer configurable esa base de puertos en el complemento para usar `55430` en la integración.

### Armando

- Preparar en `ops/` dos instancias PostgreSQL de prueba, central y Cartago, con la base `sig_tec` y transacciones preparadas habilitadas. La tabla original `cartago.edificios` necesita para esta prueba `id bigint`, `campus_id smallint` y `nombre text`. La CLI recibe un UUID, el campus propietario, el ID y el nuevo nombre. El rol de la CLI puede leer esos campos y actualizar únicamente `nombre` en la tabla original.
- Mantener las tablas de coordinación, auditoría y marcadores en el esquema `ops`. Guardar sus migraciones en `ops/` para que Joseph las ejecute en la integración. Probar en las dos instancias el commit, el aborto, la caída antes y después de guardar la decisión, y el reintento con el mismo UUID.
- Usar el proyecto Compose `sig-tec-ops` con puertos locales `57430` y `57431`. Mantener el script de archivado WAL en `ops/` y probar el respaldo y PITR en un volumen aislado. Para integrar, Joseph conecta ese script, el destino WAL por nodo y los parámetros `archive_mode` y `max_prepared_transactions` en Compose. Armando verifica la reincorporación con replicación en la base común.

## Pull requests e integración

1. Cada integrante sube sus commits a su rama y abre el PR hacia `main`. Joyce y Armando solicitan revisión a Joseph. Si todavía no tienen permiso de escritura en el repositorio, pueden usar una rama con el mismo nombre en su fork y abrir el PR desde ahí.
2. El PR indica qué se probó de forma aislada y cómo reproducirlo. Si hace falta cambiar una interfaz o un archivo compartido, acordar el cambio con Joseph en el PR antes de incorporarlo a la base común.
3. Joseph revisa los cambios y deja feedback en el PR. Cada autor responde con commits en su misma rama. Tras el visto bueno se fusiona el PR y los demás incorporan `main` a su rama antes de la prueba conjunta.
4. Integrar primero el corte de `edificios`. Probar desde QGIS y ejecutar la operación 2PC sobre esa misma base. Cada integrante aporta evidencia de su parte para la demostración final.
