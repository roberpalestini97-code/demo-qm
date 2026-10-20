"""Data van simulado: publica la telemetría del set por MQTT y escucha comandos.

Topics:
  qm/{set}/telemetria  un mensaje cada SAMPLE_SECONDS con las 8 bombas (≈1,5 KB, entra en 5 KB de IoT Core)
  qm/{set}/eventos     cambio de etapa, fallas inyectadas, cortes de enlace
  qm/{set}/estado      online/offline (last will, retenido)
  qm/{set}/cmd         {"accion":"falla","bomba":"FP-03","tipo":"valvula"}
                       {"accion":"reparar","bomba":"FP-03","componente":"fluid end"}
                       {"accion":"enlace","segundos":60}
"""
import json
import logging
import threading
import time
from datetime import datetime, timezone

from . import config
from .buffer import Outbox
from .physics import FracSet

log = logging.getLogger("simulador")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class DataVan:
    def __init__(self, frac_set, outbox, client):
        self.set = frac_set
        self.outbox = outbox
        self.client = client
        self.link_down_until = 0.0
        self.lock = threading.Lock()

    @property
    def link_up(self):
        return time.time() >= self.link_down_until and self.client.is_connected()

    def send(self, kind, body):
        payload = json.dumps(body, separators=(",", ":"))
        topic = config.topic(kind, self.set.set_id)
        if not self.link_up:
            self.outbox.put(topic, payload)
            return
        self.flush()
        info = self.client.publish(topic, payload, qos=1)
        if info.rc != 0:
            self.outbox.put(topic, payload)

    def flush(self):
        pending = self.outbox.peek(200)
        if not pending:
            return
        sent = []
        for msg_id, topic, payload in pending:
            if self.client.publish(topic, payload, qos=1).rc != 0:
                break
            sent.append(msg_id)
        self.outbox.ack(sent)
        log.info("reenviados %d mensajes del buffer", len(sent))

    def event(self, tipo, **data):
        self.send("eventos", {"v": 1, "set": self.set.set_id, "ts": now_iso(), "tipo": tipo, **data})

    def on_command(self, _client, _userdata, msg):
        try:
            cmd = json.loads(msg.payload)
            with self.lock:
                accion = cmd.get("accion")
                if accion == "falla":
                    self.set.pump(cmd["bomba"]).set_fault(cmd["tipo"])
                    self.event("falla_inyectada", bomba=cmd["bomba"], falla=cmd["tipo"])
                elif accion == "reparar":
                    self.set.pump(cmd["bomba"]).repair(cmd.get("componente"))
                    self.event("reparacion", bomba=cmd["bomba"], componente=cmd.get("componente"))
                elif accion == "enlace":
                    secs = min(600, int(cmd.get("segundos", 60)))
                    self.event("corte_enlace", segundos=secs)
                    self.link_down_until = time.time() + secs
                log.info("comando %s", cmd)
        except Exception:
            log.exception("comando inválido: %r", msg.payload)

    def tick(self, dt):
        with self.lock:
            pumps, stage_changed = self.set.step(dt)
            stage = self.set.stage
        if stage_changed:
            self.event("cambio_etapa", etapa=stage)
        self.send("telemetria", {"v": 1, "set": self.set.set_id, "ts": now_iso(), "etapa": stage, "pumps": pumps})


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    client = config.mqtt_client(f"datavan-{config.SET_ID}")
    estado = config.topic("estado")
    client.will_set(estado, "offline", qos=1, retain=True)
    van = DataVan(FracSet(config.SET_ID), Outbox(config.BUFFER_PATH), client)

    def on_connect(c, _u, _f, rc, _p):
        log.info("conectado a %s:%s (rc=%s)", config.MQTT_HOST, config.MQTT_PORT, rc)
        c.publish(estado, "online", qos=1, retain=True)
        c.subscribe(config.topic("cmd"), qos=1)

    client.on_connect = on_connect
    client.message_callback_add(config.topic("cmd"), van.on_command)
    client.reconnect_delay_set(1, 30)
    client.connect_async(config.MQTT_HOST, config.MQTT_PORT, keepalive=30)
    client.loop_start()

    dt = config.SAMPLE_SECONDS
    nxt = time.monotonic()
    while True:
        van.tick(dt)
        if len(van.outbox):
            log.info("enlace caído, %d mensajes en buffer", len(van.outbox))
        nxt += dt
        time.sleep(max(0, nxt - time.monotonic()))


if __name__ == "__main__":
    main()
