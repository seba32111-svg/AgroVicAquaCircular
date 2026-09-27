# Plan de pruebas CP01–CP16

Las evidencias no se redactan manualmente: se generan a partir de cada aserción aprobada por pytest. El flujo conserva JSON de resultados, capturas EV01–EV16, capturas de la interfaz y registro del servidor.

| Caso | Propósito | Evidencia |
|---|---|---|
| CP01 | Inicio de sesión válido y auditoría | EV01 |
| CP02 | Rechazo y límite de intentos | EV02 |
| CP03 | Permisos Administrador/Operador | EV03 |
| CP04 | Recuperación de un solo uso | EV04 |
| CP05 | Usuarios, zonas, reglas, fuentes y dispositivos | EV05 |
| CP06 | Lectura válida e idempotencia | EV06 |
| CP07 | Rechazo de lectura inválida | EV07 |
| CP08 | Panel responsive y p95 | EV08 |
| CP09 | Prioridad de agua recuperada apta | EV09 |
| CP10 | Bloqueo por calidad | EV10 |
| CP11 | Respaldo por nivel bajo | EV11 |
| CP12 | Riego manual autorizado y auditado | EV12 |
| CP13 | Rechazo de orden no autorizada o en conflicto | EV13 |
| CP14 | Confirmación y cierre crítico | EV14 |
| CP15 | 500 lecturas, balance y exportación | EV15 |
| CP16 | Watchdog y desconexión | EV16 |

Criterio de aceptación: 15 de 16 casos aprobados como mínimo (93,75%), con todos los casos críticos de seguridad aprobados.
