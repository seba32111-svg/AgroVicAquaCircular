/*
  AgroVic AquaCircular — nodo ESP32 de referencia.
  Protección local: la bomba se detiene si falta conectividad,
  expira el tiempo máximo o el nivel recuperado es insuficiente.
*/
#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include "local_config.h"

constexpr uint8_t PIN_HUMEDAD = 34;
constexpr uint8_t PIN_NIVEL_PRINCIPAL = 35;
constexpr uint8_t PIN_NIVEL_RECUPERADA = 32;
constexpr uint8_t PIN_TURBIDEZ = 33;
constexpr uint8_t PIN_CAUDAL = 25;
constexpr uint8_t PIN_BOMBA = 26;
constexpr unsigned long INTERVALO_ENVIO_MS = 300000;
constexpr unsigned long MAX_RIEGO_MS = 720000;
constexpr float NIVEL_RECUPERADA_MIN = 15.0;

unsigned long ultimoEnvio = 0;
unsigned long inicioRiego = 0;
bool bombaActiva = false;

float porcentajeAnalogico(uint8_t pin) {
  return constrain(analogRead(pin) * 100.0 / 4095.0, 0.0, 100.0);
}

float leerTurbidezNtu() {
  const float voltaje = analogRead(PIN_TURBIDEZ) * 3.3 / 4095.0;
  return constrain((3.0 - voltaje) * 2.0, 0.0, 100.0);
}

float leerConductividad() {
  return 700.0;  // Sustituir por curva de calibración del sensor utilizado.
}

float leerCaudal() {
  return digitalRead(PIN_CAUDAL) ? 2.8 : 0.0;  // Referencia; usar interrupciones en terreno.
}

void detenerSeguro(const char* motivo) {
  digitalWrite(PIN_BOMBA, LOW);
  bombaActiva = false;
  Serial.printf("DETENCION_SEGURA: %s\n", motivo);
}

void supervisarSeguridad() {
  if (bombaActiva && millis() - inicioRiego > MAX_RIEGO_MS) {
    detenerSeguro("tiempo_maximo");
  }
  if (bombaActiva && WiFi.status() != WL_CONNECTED) {
    detenerSeguro("sin_conectividad");
  }
  if (bombaActiva && porcentajeAnalogico(PIN_NIVEL_RECUPERADA) < NIVEL_RECUPERADA_MIN) {
    detenerSeguro("nivel_insuficiente");
  }
}

void enviarLectura() {
  if (WiFi.status() != WL_CONNECTED) {
    detenerSeguro("telemetria_no_disponible");
    return;
  }

  StaticJsonDocument<512> body;
  body["timestamp"] = nullptr;
  body["idempotency_key"] = String("esp32-") + String(millis());
  body["humedad_suelo_pct"] = porcentajeAnalogico(PIN_HUMEDAD);
  body["lluvia"] = false;
  body["nivel_principal_pct"] = porcentajeAnalogico(PIN_NIVEL_PRINCIPAL);
  body["nivel_recuperada_pct"] = porcentajeAnalogico(PIN_NIVEL_RECUPERADA);
  body["caudal_l_min"] = leerCaudal();
  body["turbidez_ntu"] = leerTurbidezNtu();
  body["conductividad_us_cm"] = leerConductividad();
  body["volumen_recuperado_l"] = 0.0;

  String payload;
  serializeJson(body, payload);
  HTTPClient http;
  http.begin(API_URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_ACCESS_TOKEN);
  const int status = http.POST(payload);
  Serial.printf("Telemetria HTTP %d\n", status);
  if (status < 200 || status >= 300) {
    detenerSeguro("api_rechaza_lectura");
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BOMBA, OUTPUT);
  pinMode(PIN_CAUDAL, INPUT_PULLUP);
  detenerSeguro("inicio");
  WiFi.begin(WIFI_NAME, WIFI_PASSWORD);
  const unsigned long limite = millis() + 15000;
  while (WiFi.status() != WL_CONNECTED && millis() < limite) {
    delay(250);
  }
  if (WiFi.status() != WL_CONNECTED) {
    detenerSeguro("wifi_no_disponible");
  }
}

void loop() {
  supervisarSeguridad();
  if (millis() - ultimoEnvio >= INTERVALO_ENVIO_MS || ultimoEnvio == 0) {
    ultimoEnvio = millis();
    enviarLectura();
  }
  delay(100);
}
