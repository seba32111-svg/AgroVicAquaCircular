# Nodo ESP32 de referencia

El firmware modela un nodo con sensores de humedad, nivel, caudal y calidad básica. Envía una lectura cada cinco minutos a POST /api/v1/lecturas y mantiene una detención local independiente.

## Preparación

Crear hardware/local_config.h solo en el equipo de desarrollo:

~~~cpp
#pragma once
#define WIFI_NAME "red-local"
#define WIFI_PASSWORD "clave-local"
#define API_URL "http://equipo-local:5000/api/v1/lecturas"
#define DEVICE_ACCESS_TOKEN "valor-generado-al-sembrar"
~~~

El archivo se excluye de Git. Instalar las bibliotecas ArduinoJson y la plataforma ESP32. Ajustar pines, escalas y calibración al hardware disponible antes de una instalación física.

## Límite de la evidencia

El repositorio aporta firmware compilable de referencia y un simulador de protocolo. No se presenta como evidencia de una instalación física en el predio.
