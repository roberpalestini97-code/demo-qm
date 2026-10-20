"""Segunda capa: Claude revisa los candidatos con herramientas y propone órdenes de mantenimiento.

Sin ANTHROPIC_API_KEY corre en modo 'reglas': crea las órdenes con texto armado, para que la demo
funcione igual sin costo.
"""
import json
import logging
import time

from psycopg.types.json import Jsonb

from . import config, db, tools
from .detector import COMPONENTES, candidatos

log = logging.getLogger("agente")
LOCK_ID = 4242

SYSTEM = f"""Sos el asistente de mantenimiento de un set de fractura hidráulica en Vaca Muerta.
Recibís candidatos que marcaron reglas automáticas sobre la telemetría de las bombas.
Para cada candidato decidí si corresponde abrir una orden de mantenimiento o descartarlo.

Cómo trabajar:
- Si la evidencia no alcanza, mirá la tendencia con consultar_telemetria antes de decidir.
- Revisá historial_ordenes: una falla que se repite en la misma bomba sube la prioridad.
- Abrí la orden con crear_orden o descartá con descartar. Todo candidato termina en una de las dos.
- Las órdenes quedan "propuestas": un técnico las aprueba. No digas que algo ya se reparó.
- Motivo: 1 o 2 oraciones con los números que lo justifican. Acción recomendada: concreta, en el lenguaje de un técnico de campo.
- No inventes datos ni lecturas que no te dieron las herramientas.
- Componentes válidos: {", ".join(COMPONENTES)}.
- Prioridad alta solo si hay riesgo de daño o de parar la etapa en las próximas horas."""

TOOLS = [
    {"name": "consultar_telemetria",
     "description": "Promedios por minuto de una bomba (presión, caudal, temperatura, aceite, vibración, "
                    "caudal por vuelta, sustitución de gas, horas de fluid end). Más reciente primero.",
     "input_schema": {"type": "object", "properties": {
         "pump_id": {"type": "string"}, "minutos": {"type": "integer", "minimum": 5, "maximum": 240}},
         "required": ["pump_id"]}},
    {"name": "historial_ordenes",
     "description": "Últimas 10 órdenes de mantenimiento de una bomba.",
     "input_schema": {"type": "object", "properties": {"pump_id": {"type": "string"}}, "required": ["pump_id"]}},
    {"name": "crear_orden",
     "description": "Abre una orden de mantenimiento en estado 'propuesta' para que la apruebe un técnico.",
     "input_schema": {"type": "object", "properties": {
         "set_id": {"type": "string"}, "pump_id": {"type": "string"},
         "componente": {"type": "string", "enum": COMPONENTES},
         "prioridad": {"type": "string", "enum": ["alta", "media", "baja"]},
         "motivo": {"type": "string"}, "accion_recomendada": {"type": "string"},
         "regla": {"type": "string"}},
         "required": ["set_id", "pump_id", "componente", "prioridad", "motivo", "accion_recomendada"]}},
    {"name": "descartar",
     "description": "Descarta un candidato (por ejemplo, un pico transitorio). No se vuelve a revisar por 30 minutos.",
     "input_schema": {"type": "object", "properties": {
         "pump_id": {"type": "string"}, "componente": {"type": "string", "enum": COMPONENTES},
         "motivo": {"type": "string"}}, "required": ["pump_id", "componente", "motivo"]}},
]

PLANTILLAS = {
    "sobretemperatura": "Revisar enfriamiento y lubricación del power end; bajar caudal si sigue subiendo.",
    "presion_aceite_baja": "Verificar nivel, filtro y bomba de aceite antes de la próxima etapa.",
    "ripple_vibracion": "Inspeccionar válvulas y asientos del fluid end entre etapas.",
    "eficiencia_volumetrica": "Revisar packing y émbolos; buscar pérdidas en el fluid end.",
    "sustitucion_baja": "Revisar presión y acondicionamiento del gas de alimentación del bi-fuel.",
    "horas_fluid_end": "Programar el cambio de fluid end en la próxima ventana de mantenimiento.",
}


def _run_tool(conn, name, args, evidencias):
    if name == "consultar_telemetria":
        return tools.consultar_telemetria(conn, args["pump_id"], args.get("minutos", 30))
    if name == "historial_ordenes":
        return tools.historial_ordenes(conn, args["pump_id"])
    if name == "crear_orden":
        ev = evidencias.get((args["pump_id"], args["componente"]), {})
        return tools.crear_orden(conn, args["set_id"], args["pump_id"], args["componente"], args["prioridad"],
                                 args["motivo"], args["accion_recomendada"], ev.get("evidencia"),
                                 args.get("regla") or ev.get("regla"))
    if name == "descartar":
        return tools.descartar(conn, args["pump_id"], args["componente"], args["motivo"])
    return {"error": f"herramienta desconocida {name}"}


def revisar_con_llm(conn, cands, max_turnos=10):
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    evidencias = {(c["pump_id"], c["componente"]): c for c in cands}
    messages = [{"role": "user", "content": "Candidatos:\n" + json.dumps(cands, ensure_ascii=False)}]
    acciones, tin, tout = [], 0, 0
    for _ in range(max_turnos):
        resp = client.messages.create(model=config.AGENT_MODEL, max_tokens=2000, system=SYSTEM,
                                      tools=TOOLS, messages=messages)
        tin += resp.usage.input_tokens
        tout += resp.usage.output_tokens
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            break
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                out = _run_tool(conn, block.name, block.input, evidencias)
                acciones.append({"herramienta": block.name, "entrada": block.input, "resultado": out})
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(out, ensure_ascii=False)})
        messages.append({"role": "user", "content": results})
    return acciones, tin, tout


def revisar_con_reglas(conn, cands):
    acciones = []
    for c in cands:
        e = c["evidencia"]
        motivo = (f"Regla {c['regla']}: {c['umbral']}. Últimos 5 min: temp. máx. {e.get('temp_max')} °C, "
                  f"aceite {e.get('oil_avg')} psi, vibración {e.get('vib_avg')} mm/s, horas fluid end {e.get('feh')}.")
        out = tools.crear_orden(conn, c["set_id"], c["pump_id"], c["componente"], c["prioridad_sugerida"],
                                motivo, PLANTILLAS[c["regla"]], e, c["regla"], creada_por="reglas")
        acciones.append({"herramienta": "crear_orden", "entrada": c["pump_id"], "resultado": out})
    return acciones


def run_once():
    """Una corrida completa. Devuelve el registro guardado en corridas_agente."""
    t0 = time.monotonic()
    with db.connect() as conn:
        if not conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (LOCK_ID,)).fetchone()["ok"]:
            return {"omitida": "hay otra corrida en curso"}
        try:
            cands = candidatos(conn)
            modo = "llm" if config.ANTHROPIC_API_KEY else "reglas"
            acciones, tin, tout, error = [], 0, 0, None
            if cands:
                try:
                    if modo == "llm":
                        acciones, tin, tout = revisar_con_llm(conn, cands)
                    else:
                        acciones = revisar_con_reglas(conn, cands)
                except Exception as e:
                    log.exception("falló la corrida")
                    error = str(e)
            costo = (tin * config.PRICE_IN_MTOK + tout * config.PRICE_OUT_MTOK) / 1e6
            row = conn.execute("""
                INSERT INTO corridas_agente (modo, modelo, candidatos, acciones, input_tokens, output_tokens,
                                             costo_usd, duracion_ms, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                (modo, config.AGENT_MODEL if modo == "llm" else None, Jsonb(cands),
                 Jsonb(db.jsonable(acciones)), tin, tout, costo,
                 int((time.monotonic() - t0) * 1000), error)).fetchone()
            log.info("corrida %s: %d candidatos, %d acciones, US$ %.4f", row["id"], len(cands), len(acciones), costo)
            return db.jsonable(row)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))


def handler(_event, _context):
    """Entrada para AWS Lambda con EventBridge Scheduler."""
    return run_once()
