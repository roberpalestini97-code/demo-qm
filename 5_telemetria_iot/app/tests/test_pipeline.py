"""Tests sin infraestructura: física → mensaje → filas → reglas, y el buffer offline."""
import json
import random
import statistics

import pytest

from qm import agent, ingest, simulator
from qm.buffer import Outbox
from qm.detector import evaluar
from qm.physics import FracSet

DT = 5


def correr(frac, segundos):
    out = []
    for _ in range(int(segundos / DT)):
        pumps, _ = frac.step(DT)
        out.append(pumps)
    return out


def resumen(muestras, pump_id, base=None):
    """Replica en Python lo que calcula detector.SQL para una bomba."""
    filas = [next(p for p in m if p["id"] == pump_id) for m in muestras]
    dev = [next(p for p in m if p["id"] == pump_id)["p"] - statistics.mean(p["p"] for p in m) for m in muestras]
    return {
        "set_id": "SET-01", "pump_id": pump_id, "fuel": filas[0]["fuel"], "n": len(filas),
        "temp_avg": statistics.mean(f["t"] for f in filas), "temp_max": max(f["t"] for f in filas),
        "oil_avg": statistics.mean(f["oil"] for f in filas), "vib_avg": statistics.mean(f["vib"] for f in filas),
        "bbl_vuelta": sum(f["q"] for f in filas) / sum(f["prpm"] for f in filas),
        "sub_avg": statistics.mean(f["sub"] for f in filas), "feh": max(f["feh"] for f in filas),
        "p_dev_std": statistics.stdev(dev), "bbl_vuelta_base": base,
    }


def reglas(frac, pump_id, falla, minutos=8):
    random.seed(1)
    previo = correr(frac, 3600)
    base = resumen(previo, pump_id)["bbl_vuelta"]
    frac.pump(pump_id).set_fault(falla)
    muestras = correr(frac, minutos * 60)[-60:]  # últimos 5 minutos
    return {c["regla"] for c in evaluar(resumen(muestras, pump_id, base))}


def test_sin_fallas_solo_dispara_la_preventiva_de_fp06():
    random.seed(3)
    frac = FracSet("SET-01")
    muestras = correr(frac, 3600)[-60:]
    disparos = {p.pump_id: {c["regla"] for c in evaluar(resumen(muestras, p.pump_id))} for p in frac.pumps}
    assert disparos.pop("FP-06") == {"horas_fluid_end"}
    assert all(not r for r in disparos.values()), disparos


@pytest.mark.parametrize("bomba,falla,regla", [
    ("FP-02", "sobretemperatura", "sobretemperatura"),
    ("FP-03", "aceite", "presion_aceite_baja"),
    ("FP-04", "valvula", "ripple_vibracion"),
    ("FP-01", "packing", "eficiencia_volumetrica"),
    ("FP-07", "gas", "sustitucion_baja"),
])
def test_cada_falla_dispara_su_regla(bomba, falla, regla):
    assert regla in reglas(FracSet("SET-01"), bomba, falla)


def test_mensaje_entra_en_5kb_y_se_parsea():
    frac = FracSet("SET-01")
    pumps, _ = frac.step(DT)
    payload = json.dumps({"v": 1, "set": "SET-01", "ts": "2026-10-20T12:00:00+00:00", "etapa": 12, "pumps": pumps},
                         separators=(",", ":"))
    assert len(payload.encode()) < 5 * 1024  # IoT Core factura de a 5 KB
    tel, ev = ingest.parse(payload)
    assert len(tel) == 8 and not ev
    assert len(tel[0]) == len(ingest.COLS)
    assert tel[0][:4] == ("2026-10-20T12:00:00+00:00", "SET-01", "FP-01", 12)


def test_evento_se_parsea():
    tel, ev = ingest.parse({"v": 1, "set": "SET-01", "ts": "t", "tipo": "falla_inyectada", "bomba": "FP-03", "falla": "gas"})
    assert not tel and ev[0][2] == "FP-03" and ev[0][3] == "falla_inyectada"


class FakeClient:
    def __init__(self):
        self.connected, self.sent = True, []

    def is_connected(self):
        return self.connected

    def publish(self, topic, payload, qos=0):
        self.sent.append((topic, payload))
        return type("Info", (), {"rc": 0})()


def test_corte_de_enlace_guarda_y_reenvia_en_orden(monkeypatch):
    client = FakeClient()
    van = simulator.DataVan(FracSet("SET-01"), Outbox(":memory:"), client)
    van.tick(DT)
    client.connected = False
    for _ in range(4):
        van.tick(DT)
    assert len(client.sent) == 1 and len(van.outbox) == 4
    client.connected = True
    van.tick(DT)
    assert len(van.outbox) == 0 and len(client.sent) == 6
    stamps = [json.loads(p)["ts"] for _, p in client.sent]
    assert stamps == sorted(stamps)


def test_comando_de_falla_y_reparacion():
    van = simulator.DataVan(FracSet("SET-01"), Outbox(":memory:"), FakeClient())
    msg = type("M", (), {"payload": json.dumps({"accion": "falla", "bomba": "FP-05", "tipo": "gas"})})()
    van.on_command(None, None, msg)
    assert van.set.pump("FP-05").fault == "gas"
    msg.payload = json.dumps({"accion": "reparar", "bomba": "FP-06", "componente": "fluid end"})
    van.on_command(None, None, msg)
    assert van.set.pump("FP-06").hours == 0


def test_modo_reglas_arma_la_orden(monkeypatch):
    creadas = []
    monkeypatch.setattr(agent.tools, "crear_orden", lambda conn, *a, **k: creadas.append((a, k)) or {"ok": True})
    cand = {"set_id": "SET-01", "pump_id": "FP-02", "componente": "power end", "regla": "sobretemperatura",
            "prioridad_sugerida": "alta", "umbral": "x", "evidencia": {"temp_max": 95.1}}
    agent.revisar_con_reglas(None, [cand])
    args, kwargs = creadas[0]
    assert args[1:4] == ("FP-02", "power end", "alta") and kwargs["creada_por"] == "reglas"
    assert "95.1" in args[4]
