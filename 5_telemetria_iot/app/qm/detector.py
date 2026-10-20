"""Primera capa: reglas SQL baratas que marcan candidatos. El LLM solo ve lo que pasa este filtro."""
from . import db

VENTANA_MIN = 5
MIN_MUESTRAS = 12  # ≈1 minuto a 5 s

SQL = """
WITH dev AS (
  SELECT pump_id, pressure_psi - avg(pressure_psi) OVER (PARTITION BY set_id, time) AS d
  FROM telemetria WHERE time > now() - make_interval(mins => %(v)s)
), recent AS (
  SELECT set_id, pump_id, max(fuel) AS fuel, count(*) AS n,
         avg(power_end_temp_c) AS temp_avg, max(power_end_temp_c) AS temp_max,
         avg(lube_oil_psi) AS oil_avg, avg(vibration_mm_s) AS vib_avg,
         sum(rate_bpm) / nullif(sum(pump_rpm), 0) AS bbl_vuelta,
         avg(gas_subst_pct) AS sub_avg, max(fluid_end_hours) AS feh
  FROM telemetria WHERE time > now() - make_interval(mins => %(v)s)
  GROUP BY set_id, pump_id
), base AS (
  SELECT pump_id, sum(rate_bpm) / nullif(sum(pump_rpm), 0) AS bbl_vuelta
  FROM telemetria
  WHERE time BETWEEN now() - make_interval(mins => 60 + %(v)s) AND now() - make_interval(mins => %(v)s)
  GROUP BY pump_id HAVING count(*) >= 60
)
SELECT r.*, (SELECT stddev(d) FROM dev WHERE dev.pump_id = r.pump_id) AS p_dev_std,
       b.bbl_vuelta AS bbl_vuelta_base
FROM recent r LEFT JOIN base b USING (pump_id)
ORDER BY r.pump_id
"""

# (componente, regla, prioridad sugerida, condición, umbral legible)
REGLAS = [
    ("power end", "sobretemperatura", "alta",
     lambda r: r["temp_max"] > 92, "temperatura máxima > 92 °C"),
    ("lubricación", "presion_aceite_baja", "alta",
     lambda r: r["oil_avg"] < 45, "presión de aceite media < 45 psi"),
    ("fluid end · válvulas", "ripple_vibracion", "media",
     lambda r: r["vib_avg"] > 7 or (r["p_dev_std"] or 0) > 150,
     "vibración media > 7 mm/s o ripple de presión > 150 psi"),
    ("fluid end · packing", "eficiencia_volumetrica", "media",
     lambda r: r["bbl_vuelta_base"] and r["bbl_vuelta"] < 0.92 * r["bbl_vuelta_base"],
     "caudal por vuelta < 92 % del de la última hora"),
    ("sistema de gas", "sustitucion_baja", "media",
     lambda r: r["fuel"] == "bi-fuel" and r["sub_avg"] < 40, "sustitución de gas media < 40 %"),
    ("fluid end", "horas_fluid_end", "baja",
     lambda r: r["feh"] > 1400, "más de 1.400 h de 1.500 de vida útil"),
]
COMPONENTES = [r[0] for r in REGLAS]


def evaluar(row):
    """Reglas que dispara una fila de resumen por bomba (función pura, testeable sin base)."""
    if row["n"] < MIN_MUESTRAS:
        return []
    out = []
    for componente, regla, prioridad, cond, umbral in REGLAS:
        if cond(row):
            out.append({
                "set_id": row["set_id"], "pump_id": row["pump_id"], "componente": componente,
                "regla": regla, "prioridad_sugerida": prioridad, "umbral": umbral,
                "evidencia": db.jsonable({k: v for k, v in row.items() if k not in ("set_id", "pump_id")}),
            })
    return out


def candidatos(conn):
    """Candidatos nuevos: los que ya tienen una orden abierta no vuelven a pasar por el agente."""
    rows = conn.execute(SQL, {"v": VENTANA_MIN}).fetchall()
    abiertas = {(o["pump_id"], o["componente"]) for o in conn.execute(
        "SELECT pump_id, componente FROM ordenes WHERE estado IN ('propuesta', 'aprobada')")}
    recientes = {(d["pump_id"], d["componente"]) for d in conn.execute(
        "SELECT pump_id, componente FROM descartes WHERE created_at > now() - interval '30 minutes'")}
    return [c for row in rows for c in evaluar(row)
            if (c["pump_id"], c["componente"]) not in abiertas | recientes]
