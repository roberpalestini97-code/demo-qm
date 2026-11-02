#!/usr/bin/env python3
"""Arma el sitio estático que se publica en GitHub Pages.

Uso:  python deploy/build-pages.py [--out dist]

Copia las demos estáticas y genera páginas de aviso para la consola y el tablero
de Grafana, que solo existen en el despliegue de AWS (necesitan MQTT, base y
agente). Todo con rutas relativas, así el sitio funciona bajo el subpath
https://<usuario>.github.io/demo-qm/ sin configurar nada.
"""
import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/roberpalestini97-code/demo-qm"

# Lo que se publica tal cual (demos estáticas del repo).
STATIC = [
    "index.html",
    "nav.js",
    "1_calculadora_combustible.html",
    "2_canva_propuesta_demos.pdf",
    "3_configurador_bomba.html",
    "3_configurador_assets",
    "4_dashboard_flota.html",
]

# rutas -> (título, bajada, explicación). El enlace "volver" se calcula según la profundidad.
PLACEHOLDERS = {
    "consola/index.html": (
        "Telemetría en vivo con IA agéntica",
        "Esta demo corre en el despliegue de AWS, no en el sitio estático.",
        "El data van publica por MQTT contra IoT Core, los datos se guardan en TimescaleDB y un "
        "agente con Claude propone órdenes de mantenimiento que un técnico aprueba desde esta consola. "
        "Todo eso necesita backend, así que se levanta con el CDK del repo en una EC2 (ver README-prod): "
        "el despliegue completo tarda unos minutos y queda en https://&lt;ip&gt;.sslip.io.",
    ),
    "grafana/d/qm-flota/index.html": (
        "Tablero en Grafana",
        "El tablero en vivo se sirve desde Grafana en el despliegue de AWS.",
        "Presión, temperatura, vibración, aceite, sustitución de gas y caudal por vuelta de cada bomba, "
        "en tiempo real sobre TimescaleDB. Grafana corre en la misma EC2 que el resto de la telemetría, "
        "detrás de Caddy con usuario y contraseña. Para verlo, levantar el despliegue con el CDK (ver README-prod).",
    ),
}

PAGE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · QM demos</title>
<style>
:root{{--bg:#0e1116;--card:#171b22;--ink:#e8ebf0;--muted:#9aa3b2;--line:#2a303a;--acc:#38bdf8}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,"Segoe UI",sans-serif}}
main{{max-width:720px;margin:auto;padding:48px 16px}}
h1{{font-size:26px;margin:0 0 8px}}
.lead{{color:var(--muted);margin:0 0 20px}}
p{{margin:0 0 16px}}
a.btn{{display:inline-block;margin:4px 8px 4px 0;background:var(--card);border:1px solid var(--line);
border-radius:9px;padding:9px 14px;color:var(--ink);text-decoration:none;font-size:14px}}
a.btn:hover{{border-color:var(--acc)}}
</style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <p class="lead">{lead}</p>
  <p>{body}</p>
  <p>
    <a class="btn" href="{volver}">&larr; Volver a las demos</a>
    <a class="btn" href="{repo}/blob/main/README-prod.md">Cómo levantarla · README-prod</a>
    <a class="btn" href="{repo}/tree/main/5_telemetria_iot">Código de la demo</a>
  </p>
</main>
<script src="{volver}nav.js" defer></script>
</body>
</html>
"""


def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for name in STATIC:
        src = ROOT / name
        dest = out / name
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)

    for rel, (title, lead, body) in PLACEHOLDERS.items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        volver = "../" * (len(dest.parent.parts) - len(out.parts))
        dest.write_text(
            PAGE.format(title=title, lead=lead, body=body, volver=volver, repo=REPO),
            encoding="utf-8",
        )

    # Por si algún día el sitio se sirve desde una branch con Jekyll.
    (out / ".nojekyll").write_text("", encoding="utf-8")

    archivos = sum(1 for p in out.rglob("*") if p.is_file())
    print(f"Sitio listo en {out} ({archivos} archivos): "
          + ", ".join(sorted(p.name for p in out.iterdir())))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="dist", type=Path, help="carpeta de salida (default: dist)")
    args = parser.parse_args()
    build(args.out if args.out.is_absolute() else (ROOT / args.out))
