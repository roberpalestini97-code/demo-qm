"""Ingesta: regla de IoT Core → SQS → esta Lambda → TimescaleDB.

En local la ejecuta qm.local_aws con el mismo formato de evento. Devuelve los mensajes que fallan en
batchItemFailures para que SQS los reintente (ReportBatchItemFailures en el event source mapping) y,
después de 5 intentos, los mande a la cola de mensajes fallidos.
"""
import logging

import psycopg

from . import config
from .ingest import insert, parse

log = logging.getLogger()
_conn = None


def _db():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg.connect(config.DATABASE_URL, connect_timeout=5)
    return _conn


def handler(event, _context):
    global _conn
    tel, ev, ids, failures = [], [], [], []
    for record in event.get("Records", []):
        try:
            t, e = parse(record["body"])
            tel += t
            ev += e
            ids.append(record["messageId"])
        except Exception:
            log.exception("mensaje inválido %s", record.get("messageId"))
            failures.append({"itemIdentifier": record["messageId"]})
    if tel or ev:
        try:
            insert(_db(), tel, ev)
        except psycopg.Error:
            log.exception("error de escritura, se reintenta el lote")
            if _conn is not None:
                _conn.close()
            _conn = None
            failures += [{"itemIdentifier": i} for i in ids]
    return {"batchItemFailures": failures}
