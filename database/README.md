# Base de datos MongoDB

La siembra crea diez colecciones y datos de prueba reproducibles:

| Colección | Contenido |
|---|---|
| usuarios | perfiles Administrador y Operador con hash bcrypt |
| zonas_cultivo | dos sectores del piloto |
| dispositivos | dos nodos ESP32 con token almacenado como hash |
| lecturas_sensor | 500 mediciones en colección time-series |
| fuentes_agua | red principal y estanque recuperado por zona |
| reglas_riego | umbrales, calidad, duración y prioridad |
| eventos_riego | 14 ciclos; 10 con agua recuperada |
| alertas | estados activa, confirmada y cerrada |
| auditoria | accesos, cambios y decisiones |
| tokens_recuperacion | solicitudes temporales de un solo uso |

## Generar y exportar

~~~bash
python database/seed.py
~~~

Se generan archivos Extended JSON en database/exports, uno por colección. Las cuentas y el token local aparecen en artifacts/CREDENCIALES_DEMO.txt y no se versionan.

## Importar los archivos exportados

Crear una base vacía y ejecutar, por cada archivo:

~~~bash
mongoimport --uri "mongodb://localhost:27017/agrovic_aquacircular" \
  --collection usuarios --file database/exports/usuarios.json --jsonArray
~~~

Repetir cambiando el nombre de la colección. Para conservar la configuración time-series y los índices, se recomienda ejecutar primero database/seed.py y luego reemplazar los documentos cuando corresponda.

No se incluyen datos personales ni credenciales reales.
