"""El handler de la Lambda y el emulador local de SQS: mismo evento, mismos reintentos."""
import json

import psycopg

from qm import lambda_ingest, local_aws
from qm.physics import FracSet


def mensaje(i, body):
    return {"MessageId": f"m{i}", "ReceiptHandle": f"r{i}", "Body": body, "Attributes": {"ApproximateReceiveCount": "1"}}


def telemetria():
    pumps, _ = FracSet("SET-01").step(5)
    return json.dumps({"v": 1, "set": "SET-01", "ts": "2026-10-21T12:00:00+00:00", "etapa": 12, "pumps": pumps})


def test_lote_bueno_se_inserta_y_no_devuelve_fallas(monkeypatch):
    insertado = []
    monkeypatch.setattr(lambda_ingest, "_db", lambda: "conn")
    monkeypatch.setattr(lambda_ingest, "insert", lambda conn, t, e: insertado.append((len(t), len(e))))
    msgs = [mensaje(0, telemetria()), mensaje(1, json.dumps({"v": 1, "set": "SET-01", "ts": "t", "tipo": "cambio_etapa", "etapa": 13}))]
    result = lambda_ingest.handler(local_aws.to_event(msgs), None)
    assert result == {"batchItemFailures": []}
    assert insertado == [(8, 1)]
    assert len(local_aws.to_delete(msgs, result)) == 2


def test_mensaje_invalido_vuelve_solo_ese(monkeypatch):
    monkeypatch.setattr(lambda_ingest, "_db", lambda: "conn")
    monkeypatch.setattr(lambda_ingest, "insert", lambda *a: None)
    msgs = [mensaje(0, telemetria()), mensaje(1, "{no es json")]
    result = lambda_ingest.handler(local_aws.to_event(msgs), None)
    assert result["batchItemFailures"] == [{"itemIdentifier": "m1"}]
    assert [d["ReceiptHandle"] for d in local_aws.to_delete(msgs, result)] == ["r0"]


def test_base_caida_reintenta_todo_el_lote(monkeypatch):
    def boom(*_):
        raise psycopg.OperationalError("sin conexión")

    monkeypatch.setattr(lambda_ingest, "_db", boom)
    msgs = [mensaje(0, telemetria()), mensaje(1, telemetria())]
    result = lambda_ingest.handler(local_aws.to_event(msgs), None)
    assert {f["itemIdentifier"] for f in result["batchItemFailures"]} == {"m0", "m1"}
    assert local_aws.to_delete(msgs, result) == []


def test_evento_tiene_la_forma_de_sqs():
    ev = local_aws.to_event([mensaje(0, "{}")])
    rec = ev["Records"][0]
    assert rec["eventSource"] == "aws:sqs" and rec["messageId"] == "m0" and rec["body"] == "{}"
