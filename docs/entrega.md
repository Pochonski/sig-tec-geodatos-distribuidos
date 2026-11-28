# Entrega final de SIG-TEC

Equipo: **Joseph, Joyce y Armando**. Fecha de entrega confirmada por Joseph:
**30 de noviembre de 2026, 8:00 a. m., Costa Rica**.

El PR [#8](https://github.com/Pochonski/sig-tec-geodatos-distribuidos/pull/8)
se integró en `main` mediante el commit `2c5a469`. Incluye el fondo de las
cinco sedes, la referencia local de Cartago y su validación con la sesión real.

## Archivos para Moodle

Los archivos generados están en `entrega/`, excluida de Git:

| Archivo | Contenido |
| --- | --- |
| `SIG-TEC-codigo-documentacion.zip` | Fuentes del commit indicado en `ENTREGA.txt`, documentación, estilos, datos de referencia y evidencias de la entrega. |
| `SIG-TEC-demostracion.mp4` | Video de **8:34,905**, 1920 × 1080, H.264 y audio AAC en español; menor que diez minutos. |
| `SIG-TEC-demostracion.srt` | Subtítulos en español; también se incluyeron como pista seleccionable del MP4. |
| `SHA256SUMS.txt` | Hashes del ZIP, MP4 y SRT para comprobar su integridad. |
| `entrega-manifest.json` | Commit exacto del código, tamaños y hashes del paquete final. |

El video usa **narración sintética Microsoft Sabina Desktop, es-MX**. Los
autores del proyecto son Joseph, Joyce y Armando; la voz no corresponde a una
grabación de ellos. Se combinaron capturas auténticas de QGIS Desktop,
consultas actuales y gráficos elaborados a partir de informes reales. Las
pruebas históricas del laboratorio están identificadas por fuente y fecha.

El ZIP excluye contraseñas, archivos `.env` reales, bases de autenticación y
proyectos locales QGIS, respaldos y WAL. Los `.env.example` sí se incluyen.
El video se entrega separado del ZIP para evitar duplicarlo.

## Cobertura del enunciado

El PDF tiene siete páginas y sus imágenes se pudieron revisar. La rúbrica
de las páginas 6–7 suma 100 %. El documento pide fuentes, documentación y un
video de no más de diez minutos por Moodle. No se presenta la evidencia de
laboratorio como una restauración nueva de la instalación original.

| Rubro | Peso | Implementación y evidencia | Video |
| --- | ---: | --- | --- |
| Arquitectura distribuida y modelo geográfico | 15 % | [Diseño](diseno.md), seis instancias, ocho capas, IDs globales, campus y tipos geométricos. | 0:30–1:49 |
| Cinco nodos y estructura PostGIS | 15 % | [Arranque](../db/INTEGRACION.md), consulta de lectura de los seis nodos y 40 objetos ficticios por nodo. | 0:30–1:49 |
| Replicación y vistas distribuidas | 20 % | Publicaciones de dos niveles, vistas `sig`, diez suscripciones listas y cambio de QGIS observado en los seis nodos. | 3:36–5:23 |
| QGIS y complemento PyQGIS | 20 % | Inicio de sesión manual, ocho vistas, estilos compartidos, edición propia y error real de edición ajena. | 1:49–4:45 |
| Transacciones, respaldos y recuperación | 20 % | Nueve casos 2PC, seis respaldos lógicos/físicos verificados, PITR y reincorporación en laboratorio. | 5:23–7:54 |
| Documentación y demostración | 10 % | Instrucciones reproducibles, fuentes, video narrado, subtítulos y manifiestos. | Video completo y paquete ZIP |

Los rangos redondean las marcas exactas de `entrega/video-manifest.json`.
Los mapas comunitarios conservan la atribución OSM y su licencia ODbL. Son
referencias de consulta; las ocho capas editables conservan los objetos
ficticios del sistema.

## Ensayo realizado el 28 de noviembre

- Se comprobaron por lectura los seis nodos saludables, las ocho geometrías
  en SRID 8908, ocho estilos predeterminados por nodo, suscripciones listas,
  slots activos y cero transacciones preparadas.
- En la sesión `demo_cartago` de QGIS Desktop se confirmó mediante PyQGIS
  el nombre temporal `Biblioteca Cartago - demostracion 28-11` para `id=1`.
  Las consultas confirmaron el mismo valor en los seis nodos.
- La misma sesión intentó cambiar `id=3`, de San Carlos. `commitChanges()`
  falló y el proveedor devolvió `Solo puede editar edificios de su campus`.
  Se capturaron tanto la tabla como el error auténtico.
- Se retiró el intento rechazado y se restauró el nombre propio mediante
  QGIS. Las cinco filas de edificios de cada nodo coincidieron con sus
  nombres previos. Las ocho capas quedaron sin ediciones pendientes.
- Para 2PC, respaldos, PITR y reincorporación se leyeron los informes
  existentes. No se sustituyeron nodos ni se repitió una recuperación sobre
  los volúmenes originales para preparar este video.
- Se exportó el MP4, se decodificó completo y se comprobó audio presente,
  resolución, duración, subtítulos y fotogramas de los capítulos principales.
  Los resultados técnicos están en `entrega/video-qc.json`.

La narración del video ya tiene duración medida. El [guion de exposición en
vivo](guion-demostracion.md) mantiene el reparto propuesto entre los tres y
su presupuesto de 9:20 para una exposición adicional.

## Repetir la generación

Desde la raíz, con Docker levantado y el proyecto original
`iiiproyectobasesii`:

```powershell
python herramientas/preparar_entrega.py capturar
python -m pip install -r herramientas/requirements-video.txt
powershell.exe -NoProfile -File herramientas/narrar_video.ps1
python herramientas/video_sig_tec.py --solo-imagenes
python herramientas/video_sig_tec.py
python herramientas/verificar_video.py
```

La captura es de solo lectura. El montaje requiere las capturas PNG de QGIS,
`qgis-replica.json`, `qgis-permisos.json` y los informes históricos. Esos
archivos se conservan en el ZIP dentro de `entrega/evidencias/`; no se deben
sustituir por capturas ficticias. FFmpeg y ffprobe deben estar en `PATH`.
La narración usa una voz española instalada en Windows y no requiere subir
el texto ni las imágenes a un servicio externo.

Después de guardar los cambios en Git y validar el MP4, generar el paquete:

```powershell
python herramientas/preparar_entrega.py empaquetar
```

El comando exige un árbol de Git limpio, empaqueta el commit actual, revisa
las rutas excluidas, verifica el ZIP y contrasta el hash del video. No genera
un paquete a partir de archivos sin guardar en Git.

## Cierre administrativo

El archivo exportado y el ZIP quedan preparados localmente. La publicación
del repositorio y la creación de estos archivos **no equivalen a una entrega
en Moodle**. Registrar el comprobante de la plataforma cuando se complete
la carga del ZIP y el video.

Siguen abiertas las dos consultas al profesor que ya figuran en
[validación](validacion.md): el CRS institucional obligatorio y la aceptación
del renombre auditado como escenario del rubro de transacción distribuida.
Se conserva EPSG:8908 provisionalmente y se explica el alcance del 2PC.

La portada del enunciado indica noviembre y la sección administrativa indica
junio. Se usa la fecha de noviembre confirmada por Joseph. No se cambia la
evidencia ni se afirma confirmación docente para resolver esas discrepancias.
