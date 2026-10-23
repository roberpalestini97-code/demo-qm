# QM · Telemetría de flota con IA agéntica

Un set de fractura simulado (8 bombas QEM 3000 con QSK60, 4 diésel y 4 bi-fuel) publica telemetría por MQTT. La ingesta guarda los datos en TimescaleDB y Grafana los muestra. Un agente con Claude revisa la flota y propone órdenes de mantenimiento, que un técnico aprueba desde una consola web. Las mismas herramientas están expuestas como servidor MCP.

Corre entero en Docker. Cada pieza local tiene su reemplazo directo en la capa gratuita de AWS (ver al final).

```
 simulador (data van) ──MQTT──► Mosquitto ──► iot-rule ──► ElasticMQ ──► ingest-lambda ──► TimescaleDB ◄── Grafana :3000
   buffer offline SQLite        (IoT Core)  (regla IoT)    (SQS + DLQ)   (Lambda)            │
        ▲                                                       ├──► detector (reglas SQL) ──► agente Claude ──► órdenes "propuesta"
        └──── comandos: fallas, reparación, corte de enlace ◄── consola :8000 ◄─┘                     │
                                                                 servidor MCP ◄── Claude Desktop ─────┘
```

## Cómo se decide una orden

1. **Reglas SQL baratas** (`app/qm/detector.py`) revisan los últimos 5 minutos de cada bomba y marcan candidatos: sobretemperatura, presión de aceite, ripple y vibración, caudal por vuelta (packing), sustitución de gas y horas de fluid end.
2. Los candidatos que ya tienen orden abierta, o que se descartaron hace menos de 30 minutos, no pasan.
3. **El agente** (`app/qm/agent.py`) recibe solo esos candidatos. Puede consultar la tendencia y el historial de la bomba, y termina cada uno con `crear_orden` o `descartar`.
4. La orden queda en estado **propuesta**. Un técnico la aprueba, la rechaza o la cierra. Al cerrarla, el simulador repara la bomba.
5. La base impide duplicados con un índice único parcial, y cada corrida queda registrada en `corridas_agente` con tokens, costo y acciones.

Sin `ANTHROPIC_API_KEY`, el agente corre en **modo reglas**: crea las mismas órdenes con texto armado, sin costo.

## Correr en local

Requisitos: Docker Desktop (con la virtualización activada en la BIOS) y unos 1,5 GB de RAM libres.

```bash
cp .env.example .env        # opcional: poner ANTHROPIC_API_KEY
docker compose up -d --build
```

- Consola: http://localhost:8000
- Grafana: http://localhost:3000 (anónimo de solo lectura; admin/admin para editar)
- Base: `postgresql://qm:qm@localhost:5432/telemetria`

Para ver qué pasa: `docker compose logs -f simulator iot-rule ingest-lambda agent`. La cola se ve en http://localhost:9325 (consola de ElasticMQ). Para borrar todo, datos incluidos: `docker compose down -v`.

## Guion de demo (5 minutos)

1. Abrir la consola y Grafana lado a lado. En la primera corrida, el agente ya propone el cambio de fluid end de la FP-06, que tiene 1.430 h de 1.500.
2. Inyectar **"Cae la sustitución de gas"** en la FP-07. En 2 o 3 minutos aparece la orden sobre el sistema de gas, con los números que la justifican. Engancha con el acondicionamiento de gas para Dual Fuel.
3. Inyectar **válvula lavada** en la FP-04 y mostrar en Grafana cómo sube la vibración.
4. **Cortar el enlace satelital 60 s.** Grafana muestra el hueco y, al volver, el buffer lo rellena con los timestamps originales.
5. Aprobar una orden y cerrar otra: la bomba vuelve a la normalidad.
6. Ver la corrida del agente con tokens y costo, y **generar el parte del día**.
7. Desde Claude Desktop, preguntar por MCP: "¿qué bomba me preocupa más ahora y por qué?".

## Servidor MCP en Claude Desktop

En `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "qm-flota": {
      "command": "docker",
      "args": ["compose", "-f", "<ruta al repo>/telemetria_iot/docker-compose.yml",
               "run", "--rm", "-i", "mcp"]
    }
  }
}
```

Herramientas: `estado_flota`, `telemetria_bomba`, `ordenes` y `proponer_orden`.

## Tests

Corren sin Docker. Cubren la física, las 5 fallas contra sus reglas, el tamaño del mensaje, el parseo, el buffer offline y los comandos.

```bash
cd app && python -m pytest -q
```

## Estructura

| Ruta | Qué hace |
|---|---|
| `app/qm/physics.py` | Modelo del set y de las 5 fallas |
| `app/qm/simulator.py` | Data van: publica, escucha comandos, guarda en buffer cuando no hay enlace |
| `app/qm/ingest.py` | Mensaje → filas |
| `app/qm/lambda_ingest.py` | Handler de la Lambda (SQS → TimescaleDB), con `batchItemFailures` |
| `app/qm/local_aws.py` | Equivalentes locales: la regla de IoT (MQTT → SQS) y el event source mapping (SQS → handler) |
| `sqs/elasticmq.conf` | Colas `telemetria` y `telemetria-dlq`, iguales a las del CDK |
| `app/qm/detector.py` | Reglas SQL |
| `app/qm/agent.py` | Agente con tool use; `handler` para Lambda |
| `app/qm/tools.py` | Herramientas sobre la base (agente, API y MCP) |
| `app/qm/api.py`, `static/index.html` | Consola |
| `app/qm/resumen.py` | Parte del día con Haiku |
| `app/qm/mcp_server.py` | Servidor MCP |
| `db/001_schema.sql` | Hypertable, compresión, retención, agregado continuo, órdenes |
| `grafana/` | Datasource y tablero, que se genera con `build_dashboard.py` |

## Paso a AWS en capa gratuita

| Local | AWS | Capa gratuita |
|---|---|---|
| `mosquitto` | **IoT Core** (thing + certificado X.509 + política) | Cuentas con el free tier de 12 meses: 500 mil mensajes y 250 mil reglas por mes |
| `iot-rule` + `sqs` + `ingest-lambda` | **Regla de IoT → SQS (+ DLQ) → Lambda** `qm.lambda_ingest.handler`, el mismo código | SQS y Lambda: 1 millón por mes, siempre gratis |
| `agent_loop.py` | **EventBridge Scheduler → Lambda** `qm.agent.handler` | Gratis a este volumen |
| TimescaleDB + Grafana + consola | **EC2 t3.micro o t4g.micro** con este mismo compose más `docker-compose.aws.yml`, que apaga los equivalentes locales | 750 h por mes, con 30 GB de EBS |
| Simulador | Mi PC o la misma EC2, apuntando a IoT Core por el puerto 8883 | — |

**Para no salir de la capa gratuita:**
- Con `SAMPLE_SECONDS=5`, el simulador manda 17.280 mensajes por día. Corriendo todo el mes son ~520 mil, por encima del límite de 250 mil disparos de reglas. Prenderlo solo para las demos, o usar `SAMPLE_SECONDS=15` si queda encendido todo el tiempo.
- RDS no admite la extensión TimescaleDB; por eso va en la EC2.
- Lambda conectada a la EC2 por IP privada, en la misma VPC, sin NAT Gateway, que no es gratis.
- La API de Claude no es parte de AWS. Con el modo reglas el costo es cero.
- AWS cambió la capa gratuita en julio de 2025: las cuentas nuevas reciben créditos y un plan gratuito de 6 meses en lugar de los 12 meses. Revisar qué aplica a tu cuenta antes de desplegar.

Todo lo de la tabla, salvo el agente en Lambda, ya está en el CDK de [`../infra`](../infra/README.md). El agente sigue en la EC2 porque necesita salida a internet para la API de Claude, y una Lambda en la VPC no la tiene sin NAT. El certificado del data van se genera dentro de la EC2 al arrancar: la clave privada nunca sale de la instancia.
