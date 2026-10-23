"""Equivalentes locales de la ingesta de AWS, para probar el mismo camino sin la nube.

  python -m qm.local_aws iot-rule   Mosquitto → SQS. Hace lo que la regla de IoT Core:
                                    SELECT * FROM 'qm/+/+' WHERE topic(3) IN ('telemetria', 'eventos')
  python -m qm.local_aws lambda     SQS → lambda_ingest.handler, con el mismo evento que arma el event
                                    source mapping. Borra solo los mensajes que no vuelven en batchItemFailures;
                                    los demás reaparecen al vencer el visibility timeout y, tras 5 intentos,
                                    ElasticMQ los mueve a telemetria-dlq.
"""
import logging
import queue
import sys
import time

from . import config

log = logging.getLogger("local-aws")
TOPICOS = [("qm/+/telemetria", 1), ("qm/+/eventos", 1)]


def sqs_client():
    import boto3

    return boto3.client("sqs", endpoint_url=config.SQS_ENDPOINT, region_name=config.AWS_REGION)


def queue_url(sqs):
    while True:
        try:
            return sqs.get_queue_url(QueueName=config.SQS_QUEUE)["QueueUrl"]
        except Exception as e:
            log.warning("cola %s no disponible (%s), reintento en 3 s", config.SQS_QUEUE, e)
            time.sleep(3)


def to_event(messages):
    return {"Records": [{
        "messageId": m["MessageId"], "receiptHandle": m["ReceiptHandle"], "body": m["Body"],
        "attributes": m.get("Attributes", {}), "eventSource": "aws:sqs",
    } for m in messages]}


def to_delete(messages, result):
    failed = {f["itemIdentifier"] for f in result.get("batchItemFailures", [])}
    return [{"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]}
            for i, m in enumerate(messages) if m["MessageId"] not in failed]


def iot_rule():
    sqs = sqs_client()
    url = queue_url(sqs)
    inbox = queue.Queue()
    client = config.mqtt_client("regla-iot-local")

    def on_connect(c, _u, _f, rc, _p):
        log.info("regla conectada a MQTT (rc=%s)", rc)
        c.subscribe(TOPICOS)

    client.on_connect = on_connect
    client.on_message = lambda _c, _u, msg: inbox.put(msg.payload.decode())
    client.connect_async(config.MQTT_HOST, config.MQTT_PORT, keepalive=30)
    client.loop_start()
    while True:
        batch = [inbox.get()]
        while len(batch) < 10:
            try:
                batch.append(inbox.get(timeout=0.2))
            except queue.Empty:
                break
        entries = [{"Id": str(i), "MessageBody": body} for i, body in enumerate(batch)]
        try:
            resp = sqs.send_message_batch(QueueUrl=url, Entries=entries)
            for f in resp.get("Failed", []):
                log.error("SQS rechazó un mensaje: %s", f)
        except Exception:
            log.exception("no se pudo enviar a SQS; se reencolan %d mensajes", len(batch))
            for body in batch:
                inbox.put(body)
            time.sleep(2)


def lambda_runner():
    from .lambda_ingest import handler

    sqs = sqs_client()
    url = queue_url(sqs)
    log.info("lambda local escuchando %s", url)
    while True:
        msgs = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10, WaitTimeSeconds=20,
                                   AttributeNames=["ApproximateReceiveCount"]).get("Messages", [])
        if not msgs:
            continue
        try:
            result = handler(to_event(msgs), None)
        except Exception:
            log.exception("la lambda falló; el lote vuelve a la cola")
            continue
        borrar = to_delete(msgs, result)
        if borrar:
            sqs.delete_message_batch(QueueUrl=url, Entries=borrar)
        if len(borrar) < len(msgs):
            log.warning("%d mensajes para reintento", len(msgs) - len(borrar))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    {"iot-rule": iot_rule, "lambda": lambda_runner}[sys.argv[1]]()


if __name__ == "__main__":
    main()
