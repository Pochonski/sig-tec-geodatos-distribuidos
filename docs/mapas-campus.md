# Mapas de referencia de las sedes

SIG-TEC 0.2 añade un fondo OpenStreetMap para las cinco sedes y una referencia
vectorial local de Cartago. Las ocho vistas editables de PostgreSQL conservan
los datos ficticios de la demostración. Los datos comunitarios aparecen en un
grupo propio de consulta: **Cartago · referencia OpenStreetMap**.

![Referencia vectorial de Cartago](imagenes/cartago-referencia.png)

La imagen se generó con QGIS a partir de los vectores locales, sin descargar
teselas. La revisión del complemento en QGIS Desktop se registra al final de
este documento.

## Uso en QGIS

Después de instalar o recargar el complemento:

1. Abrir **Database → SIG-TEC → Ver mapa del campus…** y elegir la sede.
2. Cartago muestra edificios, vías, pasos peatonales, parqueos, áreas verdes,
   servicios y el límite según OSM. Las otras cuatro sedes muestran el mapa
   base centrado en su ubicación de referencia.
3. El mapa base requiere Internet. Los vectores de Cartago están incluidos en
   el complemento y se pueden consultar sin Internet. La atribución de OSM
   aparece en la esquina inferior del mapa.
4. Abrir **Ver capas editables de la sesión** para regresar a las ocho vistas
   cargadas con la cuenta de campus. Las acciones de mapa cambian visibilidad
   y extensión, sin guardar ni descartar ediciones pendientes.

El mapa de referencia es público y puede abrirse sin autenticación. Las vistas
de PostgreSQL siguen requiriendo la cuenta correspondiente. Al entrar en una
sesión se añade el fondo debajo de las capas editables. Cargar un mapa varias
veces reutiliza el fondo y la referencia ya existentes.

## Contenido y precisión

La extracción del **27 de noviembre de 2026, hora de Costa Rica**, usa el
límite OSM de Cartago y el área acotada indicada en el manifiesto. Los horarios
de ese manifiesto están en UTC, por lo que figuran como 28 de noviembre.

| Archivo local | Geometría | Elementos | Interpretación |
| --- | --- | ---: | --- |
| `edificios.geojson` | `Polygon` | 155 | Contornos de 151 objetos OSM; los nombres y códigos son los de la fuente. |
| `carreteras.geojson` | `LineString` | 91 | Tramos viales dentro del campus. |
| `aceras.geojson` | `LineString` | 335 | Partes de 332 senderos, pasos peatonales y escaleras; no todos son aceras inspeccionadas. |
| `parqueos.geojson` | `Polygon` | 10 | Polígonos etiquetados como parqueos. |
| `zonas_verdes.geojson` | `Polygon` | 6 | Áreas verdes explícitamente mapeadas; no cubren toda la vegetación. |
| `puntos_interes.geojson` | `Point` | 9 | Servicios en nodos o puntos representativos de polígonos OSM. |
| `accesibilidad.geojson` | `LineString` | 1 | Paso con accesibilidad etiquetada; no certifica una ruta completa. |
| `iluminacion.geojson` | `Point` | 0 | No se encontraron luminarias etiquetadas en esta extracción. |
| `limite.geojson` | `Polygon` | 1 | Límite comunitario del campus, sin carácter catastral. |

Las geometrías con varias partes se separan en geometrías simples para
respetar los tipos del enunciado. `osm_id` conserva el tipo e ID del objeto de
origen; `parte` identifica cada parte y `id_referencia` es único dentro de cada
archivo. El manifiesto distingue elementos resultantes y objetos OSM de origen.
Un objeto también puede aparecer en varias categorías, por ejemplo un edificio
que contiene una biblioteca. Estos identificadores de referencia son distintos
del `id BIGINT` global de SIG-TEC. No se infieren pisos, capacidades, estado,
potencia o ancho que la fuente no aporte.

Los GeoJSON de entrada están en **EPSG:4326**. QGIS los transforma al sistema
del proyecto al representarlos; el proyecto nuevo usa **EPSG:8908**. Antes de
añadir capas se registran en el contexto del proyecto las operaciones de PROJ
disponibles de 4326 y 3857 a 8908, conservando cualquier elección previa del
usuario. La selección automática prefiere el menor error nominal conocido
y desactiva las transformaciones alternativas aproximadas. En QGIS 3.44.15,
las operaciones disponibles seleccionadas indican 1,5 m y pasan por CR05 y
CR-SIRGAS epoch 2014.59; esa cifra no certifica la precisión de los datos OSM.
No se modifican los ajustes globales de transformación de QGIS.

Una futura importación a las tablas geográficas debe transformar la geometría
a 8908, asignar IDs de la secuencia del campus y validar los atributos y los
tipos `Polygon`, `LineString` y `Point`.
Esta versión no importa los vectores a PostGIS ni modifica la semilla.

## Fuentes

- [OpenStreetMap: límite de Cartago, way/40819609](https://www.openstreetmap.org/way/40819609).
- [San José, way/199579277](https://www.openstreetmap.org/way/199579277).
- [San Carlos, node/9210148464](https://www.openstreetmap.org/node/9210148464).
- [Alajuela, node/14250954024](https://www.openstreetmap.org/node/14250954024).
- [Limón, way/665308676](https://www.openstreetmap.org/way/665308676).
- [Plano institucional de Cartago, versión de febrero de 2023](https://www.tec.ac.cr/mapa-campus).
  Sirvió para contrastar la biblioteca José Figueres Ferrer, código C-3,
  registrada como C3 en OSM. No se digitalizaron geometrías del PDF ni se
  verificaron todos los nombres del conjunto contra ese plano.

Las cajas de `sedes.json` definen encuadres de navegación. Para las sedes cuya
referencia es un nodo, no representan el lindero del inmueble.

Los datos derivados de OSM se distribuyen bajo **ODbL 1.0**, con atribución a
sus colaboradores. La licencia y los SHA-256 están en
[fuentes.json](../qgis/sig_tec/datos/cartago/fuentes.json). Al exportar mapas
desde QGIS se debe incluir el crédito y el enlace de licencia en la composición;
el crédito del mapa interactivo no sustituye al del archivo exportado.
[Licencia y atribución](https://www.openstreetmap.org/copyright).

## Actualizar y validar

Desde la raíz, con el Python de QGIS 3.44 LTR en Windows:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat' qgis/herramientas/actualizar_cartago_osm.py
& 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat' qgis/pruebas/test_mapas.py
& 'C:\Program Files\QGIS 3.44.15\bin\python-qgis-ltr.bat' qgis/herramientas/exportar_cartago.py docs/imagenes/cartago-referencia.png
```

El extractor también acepta `--osm RUTA` para procesar un archivo local. El
manifiesto registra la fecha de extracción, el hash de ese archivo y los de
los GeoJSON. El archivo OSM bruto es temporal y no se publica en Git. Revisar
los cambios de conteos y geometrías antes de actualizar el complemento.

El fondo usa el servicio XYZ nativo de QGIS y su caché. No se generan paquetes
de teselas, descargas anticipadas ni mapas offline de ese servidor público.
[Política del servicio](https://operations.osmfoundation.org/policies/tiles/).

## Comprobaciones

Las siete pruebas del módulo verifican hashes, geometrías válidas y trazables,
encuadres de las cinco sedes en 8908, referencia de solo lectura, reutilización
sin duplicados y conservación de una edición pendiente al alternar vistas.
También comprueban que recargar el complemento repone la atribución y no
duplica sus acciones, que un proyecto nuevo conserva 8908 aunque QGIS adopte
el CRS de la primera capa y que se registran las operaciones sin reemplazar
una elección previa. Corren con Qt `offscreen`, sin controlar el escritorio ni
renderizar teselas del servicio OSM. Resultado del 28 de noviembre: **7/7**.

En **QGIS Desktop 3.44.15**, perfil de prueba `sig_tec_mapas_20261127`, el
28 de noviembre de 2026 se comprobaron visualmente los cinco encuadres, el
fondo OSM y la atribución visible. Cartago muestra la referencia local con
etiquetas de edificios y servicios; las otras cuatro sedes ocultan ese grupo.
Se comprobó además desde PyQGIS en Desktop que los ocho conjuntos locales no
vacíos son de solo lectura y tienen los tipos simples indicados en la tabla.

La comprobación de la sesión real **`demo_cartago`** también pasó el 28 de
noviembre, después del inicio de sesión manual:

| Paso | Resultado observado en QGIS Desktop |
| --- | --- |
| Cargar la sesión | Ocho vistas válidas, cinco objetos por vista, campus 1 y SRID 8908. |
| Cambiar temporalmente el nombre de un edificio propio, sin guardar | El cambio quedó pendiente en el búfer de edición de QGIS. |
| Abrir el mapa de Cartago | Se mostró la referencia y se ocultó el grupo editable; el cambio pendiente se conservó. |
| Volver a las capas editables | Se restauró el grupo de Cartago, se ocultó la referencia y el cambio seguía pendiente. Los mismos 17 IDs de capa permanecieron cargados. |
| Terminar la prueba | Se deshizo únicamente el cambio temporal y se cerró su edición limpia. El nombre original quedó intacto y ninguna capa tenía modificaciones pendientes. |
| Recargar el complemento | Se conservaron las capas, sus fuentes y las cuatro acciones; se repuso el crédito. |
| Usar Database → SIG-TEC → Ver mapa del campus… | Se abrió el selector, tomó Cartago de la sesión y cargó el mapa al aceptar. |

La prueba de alternancia usó las funciones del complemento desde la consola
PyQGIS de Desktop y verificaciones sobre la sesión real; el acceso al selector
también se comprobó mediante el menú de la interfaz. El cambio temporal no se
confirmó en PostgreSQL. Los tipos finales fueron `Polygon` para edificios,
parqueos y zonas verdes; `LineString` para carreteras, aceras y accesibilidad;
y `Point` para puntos de interés e iluminación.

Se guardó en el equipo de Joseph el proyecto local
`qgis/SIG-TEC-mapas-local.qgz`, con las 17 capas y el mapa de Cartago visible.
Sus fuentes PostgreSQL usan referencias `authcfg`, sin contraseñas en las URI.
El archivo está excluido de Git y se abre desde el mismo perfil de QGIS donde
se inició la sesión. Cada compañero puede guardar su propio proyecto local.

La ventana del perfil anterior `sig_tec_main` dejó de responder al intentar
activarla; se conservó abierta y se continuó en el perfil de prueba. No se
guardaron ni descartaron sus ediciones.

La consulta SQL de `geometry_columns` del central confirmó que las ocho
vistas `sig` conservan `Polygon`, `LineString` y `Point`, todas con SRID 8908.
Los seis servicios originales estaban saludables y no había transacciones
preparadas pendientes. Estas comprobaciones no sustituyen las pruebas de
permisos de edición y replicación ya documentadas en el proyecto.
