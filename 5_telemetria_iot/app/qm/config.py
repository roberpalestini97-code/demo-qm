"""Configuración por variables de entorno. Los mismos nombres sirven en Docker y en AWS."""
import os


def env(key, default=None):
    return os.environ.get(key, default)


SET_ID = env("SET_ID", "SET-01")
DATABASE_URL = env("DATABASE_URL", "postgresql://qm:qm@localhost:5432/telemetria")

# MQTT: Mosquitto en local; AWS IoT Core en la nube (puerto 8883 con certificados X.509).
MQTT_HOST = env("MQTT_HOST", "localhost")
MQTT_PORT = int(env("MQTT_PORT", "1883"))
MQTT_CA = env("MQTT_CA")
MQTT_CERT = env("MQTT_CERT")
MQTT_KEY = env("MQTT_KEY")

# SQS: ElasticMQ en local (SQS_ENDPOINT=http://sqs:9324); en AWS queda vacío y usa el endpoint real.
AWS_REGION = env("AWS_REGION", "us-east-1")
SQS_ENDPOINT = env("SQS_ENDPOINT") or None
SQS_QUEUE = env("SQS_QUEUE", "telemetria")

SAMPLE_SECONDS =float(env("SAMPLE_SECONDS", "5"))
BUFFER_PATH = env("BUFFER_PATH", "/data/outbox.sqlite")

AGENT_INTERVAL = int(env("AGENT_INTERVAL", "120"))
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY") or None
AGENT_MODEL = env("AGENT_MODEL", "claude-sonnet-5-5")
SUMMARY_MODEL = env("SUMMARY_MODEL", "claude-haiku-5-5")
# US$ por millón de tokens; supuesto a validar con la lista de precios vigente.
PRICE_IN_MTOK = float(env("PRICE_IN_MTOK", "3"))
PRICE_OUT_MTOK = float(env("PRICE_OUT_MTOK", "15"))

GRAFANA_URL = env("GRAFANA_URL", "http://localhost:3000")


def topic(kind, set_id=SET_ID):
    return f"qm/{set_id}/{kind}"


def mqtt_client(client_id):
    import paho.mqtt.client as mqtt

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    if MQTT_CERT:
        c.tls_set(ca_certs=MQTT_CA, certfile=MQTT_CERT, keyfile=MQTT_KEY)
    return c
