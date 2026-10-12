# AgroVic AquaCircular

[![Validar y empaquetar entrega](https://github.com/seba32111-svg/agrovic-aquacircular/actions/workflows/validate-and-package.yml/badge.svg)](https://github.com/seba32111-svg/agrovic-aquacircular/actions/workflows/validate-and-package.yml)

**Pruebas del sistema:** 16 casos funcionales CP01–CP16 y 6 pruebas adicionales que cubren los tres CRUD administrativos; el repositorio cuenta también con pruebas auxiliares. El estado actualizado se verifica en GitHub Actions.

Sistema web para monitorear riego, reutilización controlada de agua y seguridad operacional en un piloto agrícola de dos zonas. Proyecto académico de título de **Sebastián Tapia Véliz**, carrera Técnico en Informática.

## Alcance verificable

- Aplicación Flask responsive con perfiles Administrador y Operador.
- MongoDB con 10 colecciones, 500 lecturas deterministas y 14 ciclos de riego.
- Administración con tres CRUD de usuarios, zonas y dispositivos ESP32, además de reglas y operaciones de riego.
- API para simulador ESP32, validación, idempotencia, auditoría y bloqueo de seguridad.
- 16 casos automatizados con evidencias generadas desde la ejecución.
- Informe final, presentación institucional de 15 diapositivas y guion de defensa.
- Paquete ZIP publicable en Releases.

El prototipo electrónico se valida con firmware y simulador reproducible. La instalación física en terreno queda fuera del alcance académico y se declara expresamente en el informe.

## Inicio rápido con Docker

~~~bash
git clone https://github.com/seba32111-svg/agrovic-aquacircular.git
cd agrovic-aquacircular
docker compose up --build
~~~

Abrir http://localhost:5000. En el primer inicio se crea artifacts/CREDENCIALES_DEMO.txt con usuarios locales generados para esa instalación. Son datos exclusivamente demostrativos.

## Ejecución local sin Docker

Requiere Python 3.11+ y MongoDB 7.

~~~bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r backend/requirements.txt
# Opcional: archivo .env (no se versiona) con MONGO_URI, MONGO_DB_NAME y SECRET_KEY
python -m database.doctor --seed
python -m backend.run
~~~

### Diagnóstico de MongoDB

~~~bash
python -m database.doctor          # valida URI, conexión y las 10 colecciones
python -m database.doctor --init   # crea colecciones e índices faltantes, sin datos
python -m database.doctor --seed   # carga datos demo solo si la base está vacía
~~~

La configuración se lee desde .env o desde variables de entorno. Sin ellas se usa mongodb://localhost:27017.

### Credenciales demo

Por defecto el seed genera contraseñas aleatorias y las escribe en artifacts/CREDENCIALES_DEMO.txt. Para elegirlas, definir en .env (mínimo 10 caracteres, mayúscula, minúscula, número y símbolo):

~~~text
SEED_ADMIN_EMAIL=admin@agrovic.demo
SEED_ADMIN_PASSWORD=...
SEED_OPERATOR_EMAIL=operador@agrovic.demo
SEED_OPERATOR_PASSWORD=...
~~~

Para aplicarlas a una base ya sembrada, sin borrar datos: python -m database.create_local_access

## Despliegue en Render (gratuito)

El archivo render.yaml define el servicio web. La base de datos se aloja en MongoDB Atlas M0.

1. En MongoDB Atlas crear un cluster M0 (proveedor AWS, región N. Virginia), un usuario de base de datos y, en Network Access, permitir 0.0.0.0/0. Copiar la cadena mongodb+srv.
2. Sembrar Atlas una sola vez desde el equipo local, con MONGO_URI de Atlas en .env (las credenciales demo quedan en artifacts/ local, no en el servidor). --seed no borra una base que ya tiene datos:

~~~bash
python -m database.doctor --seed
~~~

   MONGO_DB_NAME debe ser el mismo valor en .env y en Render (agrovic_aquacircular).

3. En Render: New → Blueprint → seleccionar este repositorio. Ingresar MONGO_URI cuando se solicite. SECRET_KEY se genera automáticamente.
4. Verificar https://<servicio>.onrender.com/health → {"status": "ok"}.

El plan gratuito suspende el servicio tras 15 minutos sin tráfico; la primera visita posterior tarda cerca de un minuto.

## Pruebas

~~~bash
pytest -q tests
~~~

Los casos CP01–CP16 cubren autenticación, permisos, recuperación, CRUD, API de sensores, reglas de reutilización, control manual, alertas, balance hídrico y watchdog. GitHub Actions vuelve a sembrar una base limpia, ejecuta las pruebas, captura evidencias y publica el ZIP final.

## Estructura

~~~text
backend/      aplicación y API
frontend/     plantillas y estilos responsive
database/     esquema, siembra y exportaciones
hardware/     firmware de referencia ESP32
simulator/    emulador reproducible
tests/        casos CP01–CP16, pruebas CRUD y pruebas auxiliares
scripts/      evidencias, documentos y empaquetado
docs/         fuentes y documentación de entrega
~~~

## Seguridad

Contraseñas con bcrypt, autorización por rol, token de dispositivo almacenado como SHA-256, validación de servidor, CSRF en formularios, cabeceras defensivas, recuperación de un solo uso y auditoría. En producción se exige HTTPS mediante proxy inverso y secretos fuera del repositorio.

## Contexto

Uso académico. La referencia a Agrícola Vicuña García Huidobro – AgroVic corresponde al caso de estudio; este repositorio no representa una implementación oficial de la organización.

## Gestión CRUD administrativa

En **Administración** el perfil administrador puede crear, consultar, editar y desactivar usuarios, zonas y dispositivos. La opción **Eliminar / desactivar** realiza una baja lógica; los registros permanecen para auditoría y se reactivan desde **Modificar**.

- Usuarios: cambio de nombre, correo, rol, permiso de control manual, estado y contraseña opcional; se protege la cuenta del administrador que está conectado.
- Zonas: cambios de nombre, cultivo y ubicación; se prohíbe desactivar una zona si hay un ciclo de riego activo. La desactivación de la zona también desactiva sus dispositivos.
- Dispositivos: alta, consulta, cambios de zona/modelo/nombre/intervalo y desactivación. El token generado al registrar un nuevo equipo se muestra solo una vez.
- Operaciones restringidas a administradores, protegidas mediante CSRF en formularios y registradas en la colección de auditoría.

### Comprobación de cambios

```bash
python -m pytest -q tests
```

Las pruebas deben ejecutarse contra una base **de prueba aislada**, nunca contra Atlas de producción. La siembra de demostración puede borrar por completo la base indicada en la configuración. El despliegue debe realizarse solamente tras comprobar las pruebas y disponer de un respaldo actualizado.
