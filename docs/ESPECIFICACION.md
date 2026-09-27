# Especificación consolidada

## Objetivo general

Diseñar e implementar un sistema web inteligente para monitorear el riego y apoyar la reutilización controlada de agua mediante un piloto con ESP32, sensores y trazabilidad operacional.

## Objetivos específicos

- **OE1.** Documentar problema, actores, 15 requisitos funcionales y 10 no funcionales.
- **OE2.** Definir arquitectura, diagramas y modelo NoSQL con al menos ocho colecciones.
- **OE3.** Integrar ESP32 y sensores con lecturas cada cinco minutos o menos.
- **OE4.** Implementar web responsive con dos perfiles, cuatro formularios, panel, balance y control manual.
- **OE5.** Aplicar hash de contraseñas, roles, validación, HTTPS en despliegue, token de dispositivo, recuperación y auditoría.
- **OE6.** Analizar al menos 500 lecturas y 10 ciclos de reúso con indicadores.
- **OE7.** Ejecutar al menos 16 casos, aprobar 90% o más y publicar una versión reproducible.

## Requisitos funcionales

| ID | Requisito |
|---|---|
| RF01 | Inicio de sesión y recuperación de acceso. |
| RF02 | Autorización diferenciada por rol y acción. |
| RF03 | Administración de usuarios. |
| RF04 | Administración de al menos dos zonas. |
| RF05 | Administración de fuentes, dispositivos y sensores. |
| RF06 | Recepción de humedad, lluvia, nivel, caudal y calidad cada cinco minutos o menos. |
| RF07 | Registro de volumen capturado o recuperado. |
| RF08 | Prioridad de agua recuperada solo cuando nivel y calidad son aptos. |
| RF09 | Detención o bloqueo por nivel, calidad, sensor, timeout o desconexión. |
| RF10 | Riego manual autorizado con fuente, motivo, volumen y duración. |
| RF11 | Umbrales, horario, duración, fuente y calidad configurables. |
| RF12 | Panel de métricas, dispositivos y alertas. |
| RF13 | Alertas por humedad, saturación, calidad, nivel, desconexión y falla. |
| RF14 | Historial, filtros y exportación. |
| RF15 | Auditoría de accesos, cambios y acciones. |

## Requisitos no funcionales

| ID | Requisito |
|---|---|
| RNF01 | Contraseñas protegidas con bcrypt. |
| RNF02 | HTTPS y token de dispositivo protegido en un despliegue productivo. |
| RNF03 | Autorización de servidor por rol. |
| RNF04 | Validación, rangos e idempotencia. |
| RNF05 | Tiempo p95 del panel menor a tres segundos en el piloto. |
| RNF06 | Meta de disponibilidad de 99% y detención local ante falla. |
| RNF07 | Uso desde 360 px de ancho. |
| RNF08 | Compatibilidad con versiones vigentes de Chrome, Edge y Firefox. |
| RNF09 | Modelo escalable por zona y dispositivo. |
| RNF10 | Respaldo, exportación, modularidad y documentación. |

## Perfiles

Administrador y Operador pueden consultar panel, lecturas, balance y alertas; ejecutar control manual si están autorizados; confirmar alertas y exportar reportes. Solo el Administrador gestiona usuarios, zonas, fuentes, dispositivos, reglas, prioridades y cierres críticos.
