# Demo 5 · Telemetría de flota con IA agéntica

**Qué es:** un set de fractura simulado que publica telemetría por MQTT. Los datos entran a AWS IoT Core, se guardan en TimescaleDB y se ven en Grafana. Un agente revisa la flota y propone órdenes de mantenimiento, que una persona aprueba.

**Para qué:** convertir el dashboard actual (`4_dashboard_flota.html`, todo simulado en el navegador) en un proyecto real de punta a punta. Cubre MQTT, IoT Core, series de tiempo, Grafana, Terraform e IA agéntica, y queda en GitHub como proyecto propio para el CV y la entrevista.

**Esfuerzo:** 7 a 8 días de trabajo. **Costo:** US$ 15 a 25 por mes mientras está desplegado, y cero después de `terraform destroy`.

---

## 1. Arquitectura

```
 [Simulador Python]            AWS
  8 bombas + data van   ──MQTT/TLS──►  IoT Core ──Regla──► SQS ──► Lambda ingest ──► TimescaleDB
  buffer offline (SQLite)    (QoS 1, cert X.509)                                         │   (EC2 t4g.small)
                                                                                         │
                                         Grafana ◄───────────────────────────────────────┤
                                                                                         │
       EventBridge (cada 5 min) ──► Lambda detector (reglas SQL) ──► Agente (Claude API) ─┤
                                                                     herramientas:      │
                                                                     - consultar_telemetria
                                                                     - historial_bomba
                                                                     - crear_orden (estado "propuesta")
                                                                                         │
                         Servidor MCP ◄──────────────────────────────────────────────────┘
                 ("¿cómo viene la FP-03?" desde Claude Desktop)
```

**Decisiones de diseño, que también sirven para explicar en la entrevista:**
- **El agente no mira el stream crudo.** Reglas SQL baratas detectan candidatos y el LLM solo razona sobre la evidencia. Así el costo y la latencia quedan acotados y el resultado es auditable.
- **Una persona aprueba la orden.** El agente crea órdenes en estado `propuesta`; un técnico las aprueba o las rechaza. No se manda nada al campo sin control.
- **SQS entre IoT Core y la base.** Hace de amortiguador: si la base se cae, los mensajes esperan en la cola y no se pierden.
- **Funciona sin conexión.** El simulador guarda los mensajes en SQLite cuando "se corta el satelital" y los reenvía al volver, con el timestamp original. Es lo que pasa de verdad en locación.

---

## 2. Datos

**Topics MQTT**
- `qm/{set}/{bomba}/telemetria`: lecturas cada 1 s, agrupadas en lotes de 5 s.
- `qm/{set}/{bomba}/eventos`: arranque, parada y cambio de etapa.
- `qm/{set}/estado`: last will, para saber si el set está online.

**Variables por bomba**, con la física que ya usan el dashboard y el configurador:
- presión (psi), caudal (BPM), HHP y RPM del motor
- temperatura del power end, presión de aceite de lubricación, vibración (mm/s)
- gasoil (L/h), gas (m³/h) y % de sustitución bi-fuel
- horas del fluid end

**TimescaleDB**
- `telemetria`: hypertable con chunks diarios, compresión a los 7 días y retención de 90 días.
- `telemetria_1m`: agregado continuo por minuto, del que leen Grafana y el agente.
- `ordenes`: id, bomba, componente, prioridad, motivo, evidencia (jsonb), estado, quién la creó y quién la aprobó.
- `corridas_agente`: log de cada corrida, con entrada, herramientas usadas, tokens y costo.

**Escenarios de falla del simulador**, para mostrar en vivo:
1. **Válvula lavada:** aparece ripple en la presión y sube la vibración.
2. **Sobretemperatura del power end.**
3. **Caída de presión de aceite.**
4. **Pérdida en el packing del fluid end:** baja el caudal con la misma RPM.
5. **Cae la sustitución de gas en una bi-fuel:** apunta a un problema de acondicionamiento de gas. Conecta directo con la publicación de Nicolás.

---

## 3. Etapas

| # | Etapa | Entregable | Días |
|---|---|---|---|
| 0 | Repo y entorno local | `docker-compose` con Mosquitto, TimescaleDB y Grafana; esqueleto de Terraform; GitHub Actions | 0,5 |
| 1 | Simulador | Python con `awsiotsdk`/`paho-mqtt`, 8 bombas, los 5 escenarios de falla y buffer offline | 1 |
| 2 | Ingesta en AWS | IoT Core (things, certificados, políticas), regla hacia SQS y Lambda que inserta en lotes. Todo en Terraform | 1 |
| 3 | Series de tiempo | Hypertable, agregados continuos, compresión, retención e índices | 0,5 |
| 4 | Grafana | Tablero del set, vista por bomba y alertas | 0,5 a 1 |
| 5 | Agente | Detector por reglas, agente con herramientas, órdenes con aprobación, resumen del pozo al final del día | 1,5 a 2 |
| 6 | Servidor MCP | Las mismas herramientas expuestas para Claude Desktop | 0,5 |
| 7 | Presentación | README con diagrama, video de 3 minutos, scripts para levantar y bajar todo, costos | 1 |
| | **Total** | | **7 a 8** |

Conviene hacer primero las etapas 0 a 3 y 5 en local, con Mosquitto en lugar de IoT Core, y recién después pasar a AWS. Así el costo en la nube se acota a los días de prueba y de demo.

---

## 4. Costos estimados (us-east-1)

| Servicio | Uso | US$/mes |
|---|---|---|
| EC2 t4g.small con TimescaleDB y Grafana | encendida todo el mes | ~12 |
| IoT Core | simulador solo durante demos, lotes de 5 s | < 1 |
| SQS, Lambda, EventBridge | dentro del free tier | 0 |
| Claude API | corridas cada 5 min, solo cuando hay candidatos | 2 a 8 |
| **Total** | | **~15 a 25** |

Si el simulador corre 24/7 con un mensaje por segundo por bomba, son unos 20 millones de mensajes por mes y unos US$ 20 más en IoT Core. Por eso conviene agrupar en lotes y apagarlo fuera de las demos.

---

## 5. Qué suma al CV, una vez hecho

Dentro de proyectos, como proyecto propio:

> **Telemetría de flota de fractura con IA agéntica.** Simulador de 8 bombas que publica por MQTT a AWS IoT Core; ingesta con SQS y Lambda en TimescaleDB (hypertables, agregados continuos); tableros y alertas en Grafana; agente con Claude que propone órdenes de mantenimiento con aprobación humana; servidor MCP; infraestructura en Terraform y CI con GitHub Actions.

Cubre lo que falta hoy: MQTT, IoT Core, series de tiempo, Grafana, Terraform en la práctica y operación con conectividad intermitente.

---

## 6. A definir antes de arrancar

- **Región:** us-east-1 es más barata; sa-east-1 (São Paulo) es más cercana. Recomendación: us-east-1.
- **TimescaleDB:** EC2 propia (más barata, y suma a la infraestructura del CV) o Timescale Cloud (sin mantenimiento, con 30 días gratis). Recomendación: EC2.
- **Repo público en GitHub:** recomendado. Va en el CV y Nicolás lo puede revisar.
- **Modelo del agente:** Claude Sonnet 5.5 para el razonamiento y Haiku 5.5 para el resumen diario.
