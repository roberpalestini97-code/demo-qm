import psycopg
from psycopg.rows import dict_row

from . import config


def connect():
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row, autocommit=True)


def jsonable(value):
    """Redondea floats y pasa fechas a texto para mandar filas al LLM o a la API."""
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, float):
        return round(value, 2)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value.__class__.__name__ == "Decimal":
        return float(value)
    return value
