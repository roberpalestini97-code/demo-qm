"""Servidor MCP: las mismas herramientas del agente, para consultar la flota desde Claude Desktop."""
from mcp.server.fastmcp import FastMCP

from . import config, db, tools

mcp = FastMCP("qm-flota")


@mcp.tool()
def estado_flota() -> list[dict]:
    """Última lectura de cada bomba del set (presión, caudal, temperatura, aceite, vibración, combustible)."""
    with db.connect() as conn:
        return tools.estado_flota(conn)


@mcp.tool()
def telemetria_bomba(pump_id: str, minutos: int = 30) -> list[dict]:
    """Promedios por minuto de una bomba, por ejemplo FP-03, en los últimos N minutos (máx. 240)."""
    with db.connect() as conn:
        return tools.consultar_telemetria(conn, pump_id, minutos)


@mcp.tool()
def ordenes(estado: str | None = None) -> list[dict]:
    """Órdenes de mantenimiento. estado: propuesta, aprobada, rechazada o cerrada (vacío = todas)."""
    with db.connect() as conn:
        return tools.listar_ordenes(conn, estado)


@mcp.tool()
def proponer_orden(pump_id: str, componente: str, prioridad: str, motivo: str, accion_recomendada: str) -> dict:
    """Propone una orden de mantenimiento; queda en estado 'propuesta' hasta que un técnico la apruebe."""
    with db.connect() as conn:
        return tools.crear_orden(conn, config.SET_ID, pump_id, componente, prioridad, motivo,
                                 accion_recomendada, creada_por="mcp")


if __name__ == "__main__":
    mcp.run()
