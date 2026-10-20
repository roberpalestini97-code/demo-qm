"""Ingesta local: Mosquitto → TimescaleDB, en lotes de 1 segundo. En AWS la reemplaza lambda_ingest.py."""
import logging
import queue
import time

import psycopg

from . import config
from .ingest import insert, parse

log = logging.getLogger("ingesta")


def connect_db():
    while True:
        try:
            return psycopg.connect(config.DATABASE_URL)
        except psycopg.OperationalError as e:
            log.warning("base no disponible (%s), reintento en 3 s", e)
            time.sleep(3)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    inbox = queue.Queue()
    client = config.mqtt_client("ingesta-local")

    def on_connect(c, _u, _f, rc, _p):
        log.info("conectado a MQTT (rc=%s)", rc)
        c.subscribe([("qm/+/telemetria", 1), ("qm/+/eventos", 1)])

    client.on_connect = on_connect
    client.on_message = lambda _c, _u, msg: inbox.put(msg.payload)
    client.connect_async(config.MQTT_HOST, config.MQTT_PORT, keepalive=30)
    client.loop_start()

    conn = connect_db()
    while True:
        tel, ev = [], []
        try:
            payload = inbox.get(timeout=1)
            while True:
                try:
                    t, e = parse(payload)
                    tel += t
                    ev += e
                except Exception:
                    log.exception("mensaje descartado")
                payload = inbox.get_nowait()
        except queue.Empty:
            pass
        if not (tel or ev):
            continue
        try:
            insert(conn, tel, ev)
        except psycopg.Error:
            log.exception("error de escritura, reconecto")
            conn.close()
            conn = connect_db()
            insert(conn, tel, ev)


if __name__ == "__main__":
    main()
