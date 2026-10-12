# Plan de pruebas y evidencias — AgroVic AquaCircular

## Propósito

Comprobar el funcionamiento del piloto y demostrar los tres módulos CRUD completos en un entorno de prueba reproducible. Se distingue entre pruebas funcionales, capturas automáticas y verificación manual del despliegue publicado. Las capturas generadas en CI se realizan únicamente contra una base MongoDB **aislada**, nunca contra MongoDB Atlas de producción.

## Matriz original CP01–CP16

| Caso | Propósito | Evidencia |
|---|---|---|
| CP01 | Inicio de sesión válido y auditoría | EV01 |
| CP02 | Rechazo y límite de intentos | EV02 |
| CP03 | Permisos Administrador/Operador | EV03 |
| CP04 | Recuperación de un solo uso | EV04 |
| CP05 | Altas de usuarios, zonas, reglas, fuentes y dispositivos | EV05 |
| CP06 | Lectura válida e idempotencia | EV06 |
| CP07 | Rechazo de lectura inválida | EV07 |
| CP08 | Panel responsive y p95 | EV08 |
| CP09 | Prioridad de agua recuperada apta | EV09 |
| CP10 | Bloqueo por calidad | EV10 |
| CP11 | Respaldo por nivel bajo | EV11 |
| CP12 | Riego manual autorizado y auditado | EV12 |
| CP13 | Rechazo de orden no autorizada o en conflicto | EV13 |
| CP14 | Confirmación y cierre crítico | EV14 |
| CP15 | Lecturas, balance y exportación | EV15 |
| CP16 | Watchdog y desconexión | EV16 |

**Criterio de aceptación original:** 15 de 16 casos aprobados como mínimo (93,75 %), incluidos los críticos de seguridad. El archivo \`artifacts/test_results.json\` conserva los resultados de esta matriz, sin incorporar pruebas adicionales artificialmente.

## Pruebas específicas de los tres CRUD

El archivo \`tests/test_admin_crud.py\` añade seis pruebas independientes, verificando:

| Caso | Módulo | Resultado esperado |
|---|---|---|
| CRUD-U | Usuarios y operadores | Crear, mostrar, editar, desactivar y reactivar |
| CRUD-Z | Zonas de cultivo | Crear, mostrar, editar, desactivar y reactivar |
| CRUD-D | Dispositivos ESP32 | Crear, mostrar, editar, desactivar y reactivar; credencial individual |
| SEG-R | Control de acceso | El operador recibe HTTP 403 al intentar gestionar registros |
| SEG-O | Seguridad operacional | No se desactiva la propia cuenta administradora ni una zona con riego activo |
| HIS-Z | Preservación histórica | Una baja lógica desactiva dispositivos asociados sin borrar las lecturas |
| VAL-D | Validaciones | Los datos inválidos son rechazados y los identificadores mal formados responden con HTTP 404 |

**Nota:** el archivo contiene las comprobaciones agrupadas en seis funciones, dentro de las cuales se cubren las siete filas de criterios anteriores. La integración con las demás pruebas del repositorio suma 33 tests de pytest verificados en GitHub Actions al momento de introducir los CRUD.

## Evidencias visuales generadas automáticamente

El script \`scripts/capture_evidence.py\` inicia sesión con una cuenta de demostración y utiliza formularios reales de Flask para crear registros temporales, consultarlos, modificarlos y desactivarlos. Las capturas se almacenan en \`artifacts/evidence/\`.

| Archivos | Acción demostrada |
|---|---|
| UI06–UI08 | Usuarios: alta/consulta, formulario de edición, baja lógica |
| UI09–UI11 | Zonas: alta/consulta, formulario de edición, baja lógica |
| UI12–UI14 | Dispositivos: alta/consulta, formulario de edición, baja lógica |

La modificación y la desactivación se comprueban después de que el servidor haya persistido los cambios. El token de aprovisionamiento de dispositivos **nunca** aparece en las capturas ni en el paquete público.

Además se preservan las vistas UI01–UI05 y las tarjetas EV01–EV16. Las capturas son evidencia automatizada del entorno CI, no deben presentarse como operaciones realizadas en el servidor productivo.

## Pasos para comprobar en el sitio publicado

1. Iniciar sesión como administrador en el entorno Render.
2. Crear un usuario y una zona exclusivamente de demostración, sin modificar las cuentas ni las parcelas originales.
3. Confirmar que los registros aparecen al volver a Administración.
4. Modificar cada registro y recargar la página para comprobar persistencia.
5. Desactivar y comprobar que aparece «Inactivo/Inactiva»; si se requiere, reactivar desde «Modificar».
6. Registrar un ESP32 ficticio en una zona activa, conservar el token **fuera de capturas**, modificar y desactivar el equipo.
7. Iniciar sesión como operador y verificar que no puede acceder al panel de administración.
8. Conservar capturas individuales sin contraseñas, tokens, cookies, URI de conexión o datos sensibles.

**Advertencia:** si se desactiva una zona original, los dispositivos vinculados también quedan inactivos. Al reactivarla es necesario revisar y reactivar cada dispositivo por separado. Nunca ejecutar \`seed_database\` sin garantías de aislamiento: la siembra de demostración puede borrar la base indicada.

## Ejecución reproducible

\`\`\`bash
python -m pytest -q tests
\`\`\`

El flujo de GitHub Actions usa MongoDB 7 en un contenedor de ejecución efímera, valida la matriz original y genera las capturas y los entregables. MongoDB Atlas productivo no participa en estas pruebas.
