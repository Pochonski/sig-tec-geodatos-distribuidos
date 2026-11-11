# SIG-TEC

Proyecto de Bases de Datos II del Tecnológico de Costa Rica. SIG-TEC permite consultar en QGIS la información geográfica de Cartago, San José, San Carlos, Alajuela y Limón. Cada campus administra sus propios datos y recibe copias de los otros cuatro para consulta.

## Alcance

- Cinco nodos operativos PostgreSQL con PostGIS y un nodo central de autenticación y coordinación, reproducibles con Docker Compose en una computadora.
- Ocho capas geográficas con datos ficticios georreferenciados, identificadores globales y permisos de edición por campus.
- Replicación lógica en dos niveles, estilos compartidos y un complemento PyQGIS para iniciar sesión y cargar las capas.
- Una operación administrativa de renombre auditado con commit en dos fases, respaldos por nodo y recuperación a un punto en el tiempo.

## Documentación

- [Enunciado del proyecto](Tercer%20Proyecto%20Enunciado.pdf).
- [Diseño y modelo geográfico](docs/diseno.md). Topología, contratos de datos, replicación, acceso y operación administrativa.
- [Pruebas y demostración](docs/validacion.md). Criterios de aceptación, recuperación, guion del video y pendientes del curso.
- [Reparto del trabajo](docs/reparto.md). Responsables, ramas, interfaces y entornos de prueba para empezar en paralelo.
- [Base distribuida](db/README.md). Arranque de los seis nodos, cuentas de prueba y validación de ocho capas en cinco campus.

La base se valida primero por SQL y después con el proveedor PostgreSQL de QGIS. El complemento de Joyce agrega el inicio de sesión y la carga automática de capas y estilos al integrar su pull request.

## Contribución

1. Clona el repositorio y actualiza `main` antes de empezar una tarea.
2. Crea una rama corta por cambio, por ejemplo `feat/replicacion-edificios` o `docs/criterios-pitr`.
3. Abre un pull request hacia `main` con el propósito del cambio, las decisiones afectadas y la evidencia de las pruebas realizadas. Joseph revisa los PR de Joyce y Armando y da el visto bueno para fusionarlos.
4. Actualiza el diseño y la validación en el mismo pull request cuando cambie un contrato entre componentes o un criterio de aceptación.

Usa datos de demostración ficticios. Guarda la configuración local con credenciales, los proyectos locales de QGIS y los respaldos fuera del historial de Git.
