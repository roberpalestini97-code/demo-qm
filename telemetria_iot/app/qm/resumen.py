"""Resumen del set para el cierre del día: números de la base y redacción con Haiku (o plantilla sin clave)."""
import json

from . import config, db

SQL = """
SELECT pump_id, max(fuel) AS fuel, round(avg(hhp)::numeric) AS hhp_medio,
       round(avg(rate_bpm)::numeric, 1) AS bpm_medio, round(max(temp_max)::numeric, 1) AS temp_max,
       round(min(oil_min)::numeric, 1) AS aceite_min, round(max(vib_max)::numeric, 1) AS vib_max,
       round((sum(diesel_lph) / 60)::numeric) AS gasoil_l, round((sum(gas_m3h) / 60)::numeric) AS gas_m3,
       round(max(fluid_end_hours)::numeric) AS horas_fluid_end, sum(n) AS muestras
FROM telemetria_1m WHERE set_id = %(s)s AND bucket > now() - make_interval(hours => %(h)s)
GROUP BY pump_id ORDER BY pump_id
"""


def datos(conn, set_id, horas):
    return {
        "set": set_id, "horas": horas,
        "bombas": db.jsonable(conn.execute(SQL, {"s": set_id, "h": horas}).fetchall()),
        "etapas": db.jsonable(conn.execute(
            "SELECT min(stage) AS desde, max(stage) AS hasta FROM telemetria "
            "WHERE set_id = %(s)s AND time > now() - make_interval(hours => %(h)s)",
            {"s": set_id, "h": horas}).fetchone()),
        "ordenes": db.jsonable(conn.execute(
            "SELECT pump_id, componente, prioridad, estado FROM ordenes "
            "WHERE set_id = %(s)s AND created_at > now() - make_interval(hours => %(h)s)",
            {"s": set_id, "h": horas}).fetchall()),
    }


def plantilla(d):
    b = d["bombas"]
    gasoil = sum(x["gasoil_l"] or 0 for x in b)
    gas = sum(x["gas_m3"] or 0 for x in b)
    lineas = [f"Set {d['set']} · últimas {d['horas']} h · etapas {d['etapas']['desde']} a {d['etapas']['hasta']}",
              f"Consumo: {gasoil:,.0f} L de gasoil y {gas:,.0f} m³ de gas.",
              f"Órdenes nuevas: {len(d['ordenes'])}."]
    lineas += [f"- {o['pump_id']} · {o['componente']} ({o['prioridad']}, {o['estado']})" for o in d["ordenes"]]
    return "\n".join(lineas)


def generar(set_id=config.SET_ID, horas=24):
    with db.connect() as conn:
        d = datos(conn, set_id, horas)
        if config.ANTHROPIC_API_KEY:
            import anthropic

            resp = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY).messages.create(
                model=config.SUMMARY_MODEL, max_tokens=700,
                system="Redactá el parte de cierre de un set de fractura para el jefe de campo: "
                       "máximo 8 líneas, en español, con números concretos, primero lo que requiere acción. "
                       "Usá solo los datos recibidos.",
                messages=[{"role": "user", "content": json.dumps(d, ensure_ascii=False)}])
            texto, modo = resp.content[0].text, "llm"
        else:
            texto, modo = plantilla(d), "reglas"
        row = conn.execute("INSERT INTO resumenes (set_id, horas, texto, modo) VALUES (%s, %s, %s, %s) RETURNING *",
                           (set_id, horas, texto, modo)).fetchone()
        return db.jsonable(row)
