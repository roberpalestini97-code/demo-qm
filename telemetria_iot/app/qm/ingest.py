"""Convierte los mensajes del data van en filas de TimescaleDB.

Lo usan dos entradas con el mismo código:
  ingest_mqtt.py    local, suscripto a Mosquitto
  lambda_ingest.py  AWS, IoT Core → regla → SQS → Lambda
"""
import json

from psycopg.types.json import Jsonb

CAMPOS = {  # clave corta del mensaje → columna
    "fuel": "fuel",
    "p": "pressure_psi",
    "q": "rate_bpm",
    "hhp": "hhp",
    "erpm": "engine_rpm",
    "prpm": "pump_rpm",
    "t": "power_end_temp_c",
    "oil": "lube_oil_psi",
    "vib": "vibration_mm_s",
    "d": "diesel_lph",
    "g": "gas_m3h",
    "sub": "gas_subst_pct",
    "feh": "fluid_end_hours",
}
COLS = ["time", "set_id", "pump_id", "stage", *CAMPOS.values()]
SQL_TELEMETRIA = (
    f"INSERT INTO telemetria ({', '.join(COLS)}) VALUES ({', '.join(['%s'] * len(COLS))}) "
    "ON CONFLICT DO NOTHING"
)
SQL_EVENTO = "INSERT INTO eventos (time, set_id, pump_id, tipo, datos) VALUES (%s, %s, %s, %s, %s)"


def _load(payload):
    if isinstance(payload, (bytes, str)):
        return json.loads(payload)
    return payload


def parse(payload):
    """Devuelve (filas_telemetria, filas_eventos)."""
    msg = _load(payload)
    if "pumps" in msg:
        rows = [
            (msg["ts"], msg["set"], p["id"], msg.get("etapa"), *[p.get(k) for k in CAMPOS])
            for p in msg["pumps"]
        ]
        return rows, []
    if "tipo" in msg:
        datos = {k: v for k, v in msg.items() if k not in ("v", "set", "ts", "tipo")}
        return [], [(msg["ts"], msg["set"], datos.get("bomba"), msg["tipo"], Jsonb(datos))]
    raise ValueError("mensaje sin 'pumps' ni 'tipo'")


def insert(conn, telemetria, eventos):
    with conn.cursor() as cur:
        if telemetria:
            cur.executemany(SQL_TELEMETRIA, telemetria)
        if eventos:
            cur.executemany(SQL_EVENTO, eventos)
    conn.commit()
