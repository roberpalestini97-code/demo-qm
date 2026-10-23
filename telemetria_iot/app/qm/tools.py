"""Herramientas sobre la base. Las usan el agente (tool use de Claude), la API y el servidor MCP."""
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from . import db
from .detector import COMPONENTES


def estado_flota(conn):
    return db.jsonable(conn.execute("""
        SELECT DISTINCT ON (pump_id) time, set_id, pump_id, fuel, stage, pressure_psi, rate_bpm, hhp,
               power_end_temp_c, lube_oil_psi, vibration_mm_s, diesel_lph, gas_m3h, gas_subst_pct, fluid_end_hours
        FROM telemetria WHERE time > now() - interval '2 minutes'
        ORDER BY pump_id, time DESC""").fetchall())


def consultar_telemetria(conn, pump_id, minutos=30):
    minutos = max(5, min(int(minutos), 240))
    return db.jsonable(conn.execute("""
        SELECT bucket, pressure_psi, rate_bpm, temp_avg, temp_max, oil_avg, vib_avg, vib_max,
               bbl_por_vuelta, gas_subst_pct, fluid_end_hours
        FROM telemetria_1m WHERE pump_id = %s AND bucket > now() - make_interval(mins => %s)
        ORDER BY bucket DESC LIMIT 60""", (pump_id, minutos)).fetchall())


def historial_ordenes(conn, pump_id):
    return db.jsonable(conn.execute("""
        SELECT id, created_at, componente, prioridad, motivo, estado, revisada_at
        FROM ordenes WHERE pump_id = %s ORDER BY created_at DESC LIMIT 10""", (pump_id,)).fetchall())


def listar_ordenes(conn, estado=None):
    q = "SELECT * FROM ordenes"
    args = ()
    if estado:
        q += " WHERE estado = %s"
        args = (estado,)
    return db.jsonable(conn.execute(q + " ORDER BY created_at DESC LIMIT 100", args).fetchall())


def crear_orden(conn, set_id, pump_id, componente, prioridad, motivo, accion_recomendada,
                evidencia=None, regla=None, creada_por="agente"):
    if componente not in COMPONENTES:
        return {"ok": False, "error": f"componente inválido; usar uno de {COMPONENTES}"}
    if prioridad not in ("alta", "media", "baja"):
        return {"ok": False, "error": "prioridad debe ser alta, media o baja"}
    try:
        row = conn.execute("""
            INSERT INTO ordenes (set_id, pump_id, componente, prioridad, motivo, accion_recomendada,
                                 evidencia, regla, creada_por)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (set_id, pump_id, componente, prioridad, motivo, accion_recomendada,
             Jsonb(evidencia or {}), regla, creada_por)).fetchone()
        return {"ok": True, "orden_id": row["id"], "estado": "propuesta"}
    except UniqueViolation:
        return {"ok": False, "error": "ya hay una orden abierta para esa bomba y componente"}


def descartar(conn, pump_id, componente, motivo):
    conn.execute("INSERT INTO descartes (pump_id, componente, motivo) VALUES (%s, %s, %s)",
                 (pump_id, componente, motivo))
    return {"ok": True}


def revisar_orden(conn, orden_id, accion, usuario):
    nuevo = {"aprobar": "aprobada", "rechazar": "rechazada", "cerrar": "cerrada"}[accion]
    previo = {"aprobar": ("propuesta",), "rechazar": ("propuesta",), "cerrar": ("propuesta", "aprobada")}[accion]
    row = conn.execute("""
        UPDATE ordenes SET estado = %s, revisada_por = %s, revisada_at = now()
        WHERE id = %s AND estado = ANY(%s) RETURNING *""", (nuevo, usuario, orden_id, list(previo))).fetchone()
    return db.jsonable(row) if row else None
