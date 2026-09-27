// Esquema complementario para inspección con mongosh.
// La creación ejecutable de validadores e índices está en database/seed.py.
const nombres = [
  "usuarios",
  "zonas_cultivo",
  "dispositivos",
  "lecturas_sensor",
  "fuentes_agua",
  "reglas_riego",
  "eventos_riego",
  "alertas",
  "auditoria",
  "tokens_recuperacion"
];
print("Colecciones esperadas:");
nombres.forEach((nombre) => print(" - " + nombre));
printjson(db.getCollectionNames().sort());
printjson(db.lecturas_sensor.getIndexes());
