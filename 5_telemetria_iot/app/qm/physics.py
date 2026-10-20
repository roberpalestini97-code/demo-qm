"""Modelo simple de un set de fractura: 8 bombas QEM 3000 (émbolo 4,5", carrera 8") con QSK60.

Las fórmulas son las mismas del dashboard y del configurador:
  HHP = presión · caudal / 40,8
  desplazamiento = 5 · área · carrera / 231 / 42  [bbl por vuelta]
"""
import math
import random
from dataclasses import dataclass

VIDA_FLUID_END = 1500  # h
DISP_BBL_REV = 5 * math.pi * (4.5 / 2) ** 2 * 8 / 231 / 42  # ≈ 0,0656 bbl/vuelta
LPH_POR_HHP = 0.24  # L/h de gasoil equivalente por HHP (mismo supuesto que el dashboard)
M3_GAS_POR_L = 36 / 37.3  # equivalencia energética gasoil → gas natural

FALLAS = {
    "sobretemperatura": "Sube la temperatura del power end",
    "aceite": "Cae la presión de aceite de lubricación",
    "valvula": "Válvula lavada: ripple de presión y vibración",
    "packing": "Pérdida en el packing: baja el caudal con las mismas RPM",
    "gas": "Cae la sustitución de gas (bi-fuel)",
}


def _toward(value, target, rate, noise):
    return value + (target - value) * rate + random.gauss(0, noise)


@dataclass
class Pump:
    pump_id: str
    fuel: str  # "diesel" | "bi-fuel"
    hours: float
    q_cmd: float = 10.0
    temp: float = 75.0
    oil: float = 65.0
    vib: float = 3.5
    vol_eff: float = 0.97
    subst: float = 0.0
    fault: str | None = None
    fault_t: float = 0.0

    def __post_init__(self):
        if self.fuel == "bi-fuel" and not self.subst:
            self.subst = 60.0

    def set_fault(self, kind):
        if kind is not None and kind not in FALLAS:
            raise ValueError(f"falla desconocida: {kind}")
        self.fault, self.fault_t = kind, 0.0

    def repair(self, componente=None):
        self.fault, self.fault_t = None, 0.0
        if componente and componente.startswith("fluid end"):
            self.hours = 0.0

    def step(self, set_pressure, dt):
        f, ft = self.fault, self.fault_t
        if f:
            self.fault_t += dt

        self.q_cmd = min(11.5, max(8.5, self.q_cmd + random.gauss(0, 0.15)))
        self.hours += dt / 3600

        temp_target = 75 + 5 * (self.q_cmd - 10) + (min(30, ft * 0.1) if f == "sobretemperatura" else 0)
        oil_target = 65 - (min(35, ft * 0.15) if f == "aceite" else 0)
        vib_target = 3.5 + (min(6, ft * 0.03) if f == "valvula" else 0)
        eff_target = max(0.80, 0.97 - ft * 0.001) if f == "packing" else 0.97
        ripple = min(600, ft * 3) if f == "valvula" else 0
        self.temp = _toward(self.temp, temp_target, 0.15, 0.3)
        self.oil = _toward(self.oil, oil_target, 0.2, 0.4)
        self.vib = max(0.5, _toward(self.vib, vib_target, 0.2, 0.15))
        self.vol_eff = _toward(self.vol_eff, eff_target, 0.3, 0.002)
        if self.fuel == "bi-fuel":
            sub_target = max(15, 60 - ft * 0.25) if f == "gas" else 60
            self.subst = min(70, max(0, _toward(self.subst, sub_target, 0.2, 0.8)))

        pressure = set_pressure + random.gauss(0, 40) + ripple * math.sin(random.uniform(0, 2 * math.pi))
        q = self.q_cmd * self.vol_eff / 0.97
        pump_rpm = self.q_cmd / (DISP_BBL_REV * 0.97)
        hhp = pressure * q / 40.8
        eq_lph = hhp * LPH_POR_HHP
        diesel = eq_lph * (1 - self.subst / 100)
        gas = eq_lph * self.subst / 100 * M3_GAS_POR_L
        return {
            "id": self.pump_id,
            "fuel": self.fuel,
            "p": round(pressure, 1),
            "q": round(q, 2),
            "hhp": round(hhp),
            "erpm": round(1850 + 40 * (self.q_cmd - 10) + random.gauss(0, 5)),
            "prpm": round(pump_rpm, 1),
            "t": round(self.temp, 1),
            "oil": round(self.oil, 1),
            "vib": round(self.vib, 2),
            "d": round(diesel, 1),
            "g": round(gas, 1),
            "sub": round(self.subst, 1),
            "feh": round(self.hours, 3),
        }


class FracSet:
    def __init__(self, set_id, seed=7):
        rnd = random.Random(seed)
        self.set_id = set_id
        self.pressure = 9200.0
        self.stage = 12
        self.stage_t = 0.0
        self.pumps = [
            Pump(f"FP-{i + 1:02d}", "diesel" if i < 4 else "bi-fuel", hours=rnd.uniform(300, 1300))
            for i in range(8)
        ]
        self.pumps[5].hours = 1430  # FP-06 cerca del fin de vida: dispara una orden preventiva

    def pump(self, pump_id):
        for p in self.pumps:
            if p.pump_id == pump_id:
                return p
        raise KeyError(pump_id)

    def step(self, dt, stage_seconds=900):
        self.pressure = min(10500, max(8000, self.pressure + random.gauss(0, 60)))
        self.stage_t += dt
        changed = self.stage_t >= stage_seconds
        if changed:
            self.stage, self.stage_t = self.stage + 1, 0.0
        return [p.step(self.pressure, dt) for p in self.pumps], changed
