"""Consola de la demo: estado de la flota, órdenes con aprobación, inyección de fallas y corridas del agente."""
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import agent, config, db, resumen, tools
from .physics import FALLAS

app = FastAPI(title="QM · Telemetría de flota")
_mqtt = None


def publish_cmd(body):
    global _mqtt
    if _mqtt is None:
        _mqtt = config.mqtt_client("consola-api")
        _mqtt.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=30)
        _mqtt.loop_start()
    _mqtt.publish(config.topic("cmd"), json.dumps(body), qos=1).wait_for_publish(5)


class Falla(BaseModel):
    bomba: str
    tipo: str | None = None  # None repara la bomba


class Enlace(BaseModel):
    segundos: int = 60


class Revision(BaseModel):
    usuario: str = "técnico demo"


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/config")
def get_config():
    return {"set": config.SET_ID, "grafana": config.GRAFANA_URL, "fallas": FALLAS,
            "modo": "llm" if config.ANTHROPIC_API_KEY else "reglas", "modelo": config.AGENT_MODEL}


@app.get("/api/flota")
def flota():
    with db.connect() as conn:
        return tools.estado_flota(conn)


@app.get("/api/ordenes")
def ordenes(estado: str | None = None):
    with db.connect() as conn:
        return tools.listar_ordenes(conn, estado)


@app.post("/api/ordenes/{orden_id}/{accion}")
def revisar(orden_id: int, accion: str, body: Revision):
    if accion not in ("aprobar", "rechazar", "cerrar"):
        raise HTTPException(400, "acción inválida")
    with db.connect() as conn:
        row = tools.revisar_orden(conn, orden_id, accion, body.usuario)
    if not row:
        raise HTTPException(409, "la orden no está en un estado que permita esa acción")
    if accion == "cerrar":  # trabajo hecho: el simulador repara la bomba
        publish_cmd({"accion": "reparar", "bomba": row["pump_id"], "componente": row["componente"]})
    return row


@app.post("/api/fallas")
def falla(body: Falla):
    if body.tipo and body.tipo not in FALLAS:
        raise HTTPException(400, "falla desconocida")
    cmd = {"accion": "falla", "bomba": body.bomba, "tipo": body.tipo} if body.tipo \
        else {"accion": "reparar", "bomba": body.bomba}
    publish_cmd(cmd)
    return {"ok": True}


@app.post("/api/enlace")
def enlace(body: Enlace):
    publish_cmd({"accion": "enlace", "segundos": body.segundos})
    return {"ok": True}


@app.post("/api/agente")
def correr_agente():
    return agent.run_once()


@app.get("/api/corridas")
def corridas():
    with db.connect() as conn:
        return db.jsonable(conn.execute(
            "SELECT * FROM corridas_agente ORDER BY started_at DESC LIMIT 10").fetchall())


@app.post("/api/resumen")
def nuevo_resumen(horas: int = 24):
    return resumen.generar(config.SET_ID, max(1, min(horas, 72)))
