"""Genera grafana/dashboards/flota.json. Correr después de cambiar paneles: python grafana/build_dashboard.py"""
import json
from pathlib import Path

DS = {"type": "grafana-postgresql-datasource", "uid": "timescale"}
LAST = "time = (SELECT max(time) FROM telemetria WHERE time > now() - interval '1 minute')"


def target(sql, fmt="time_series"):
    return {"refId": "A", "datasource": DS, "editorMode": "code", "format": fmt, "rawQuery": True, "rawSql": sql}


def stat(i, title, sql, unit, x, decimals=0):
    return {"id": i, "type": "stat", "title": title, "datasource": DS, "gridPos": {"h": 4, "w": 4, "x": x, "y": 0},
            "targets": [target(sql, "table")],
            "fieldConfig": {"defaults": {"unit": unit, "decimals": decimals, "color": {"mode": "fixed", "fixedColor": "text"}},
                            "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "value", "graphMode": "none"}}


def series(i, title, column, unit, x, y, thresholds=None, where=""):
    sql = (f"SELECT time_bucket('$__interval', time) AS time, pump_id AS metric, avg({column}) AS value "
           f"FROM telemetria WHERE $__timeFilter(time) {where} GROUP BY 1, 2 ORDER BY 1")
    defaults = {"unit": unit, "custom": {"lineWidth": 2, "showPoints": "never", "insertNulls": 60000}}
    if thresholds:
        defaults["thresholds"] = {"mode": "absolute", "steps": [{"color": "transparent", "value": None},
                                                                 {"color": "red", "value": thresholds}]}
        defaults["custom"]["thresholdsStyle"] = {"mode": "dashed"}
    return {"id": i, "type": "timeseries", "title": title, "datasource": DS, "interval": "5s",
            "gridPos": {"h": 8, "w": 12, "x": x, "y": y}, "targets": [target(sql)],
            "fieldConfig": {"defaults": defaults, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}}


panels = [
    stat(1, "Presión media", f"SELECT avg(pressure_psi) FROM telemetria WHERE {LAST}", "psi", 0),
    stat(2, "Caudal total", f"SELECT sum(rate_bpm) FROM telemetria WHERE {LAST}", "none", 4, 1),
    stat(3, "HHP total", f"SELECT sum(hhp) FROM telemetria WHERE {LAST}", "none", 8),
    stat(4, "Gasoil (L/h)", f"SELECT sum(diesel_lph) FROM telemetria WHERE {LAST}", "none", 12),
    stat(5, "Gas (m³/h)", f"SELECT sum(gas_m3h) FROM telemetria WHERE {LAST}", "none", 16),
    stat(6, "Órdenes abiertas", "SELECT count(*) FROM ordenes WHERE estado IN ('propuesta','aprobada')", "none", 20),
    series(7, "Presión de descarga por bomba (psi)", "pressure_psi", "psi", 0, 4),
    series(8, "Temperatura del power end (°C)", "power_end_temp_c", "celsius", 12, 4, 92),
    series(9, "Vibración (mm/s)", "vibration_mm_s", "none", 0, 12, 7),
    series(10, "Presión de aceite (psi)", "lube_oil_psi", "psi", 12, 12, 45),
    series(11, "Sustitución de gas, bi-fuel (%)", "gas_subst_pct", "percent", 0, 20, 40, "AND fuel = 'bi-fuel'"),
    series(12, "Caudal por vuelta (bbl)", "rate_bpm / nullif(pump_rpm, 0)", "none", 12, 20),
    {"id": 13, "type": "table", "title": "Órdenes de mantenimiento", "datasource": DS,
     "gridPos": {"h": 9, "w": 24, "x": 0, "y": 28},
     "targets": [target("SELECT id, created_at AS creada, pump_id AS bomba, componente, prioridad, estado, "
                        "creada_por, motivo, accion_recomendada AS accion FROM ordenes ORDER BY created_at DESC LIMIT 50",
                        "table")],
     "fieldConfig": {"defaults": {}, "overrides": [
         {"matcher": {"id": "byName", "options": "motivo"}, "properties": [{"id": "custom.width", "value": 420}]}]},
     "options": {"showHeader": True}},
]

dashboard = {
    "uid": "qm-flota", "title": "QM · Set de fractura", "tags": ["qm", "fractura"], "timezone": "browser",
    "schemaVersion": 39, "version": 1, "refresh": "5s", "time": {"from": "now-30m", "to": "now"},
    "panels": panels,
}
out = Path(__file__).parent / "dashboards" / "flota.json"
out.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
print("escrito", out)
