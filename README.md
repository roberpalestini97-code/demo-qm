# demo-qm

Prototipos para QM Equipment, hechos por Rober Palestini. Es una demo independiente, no un sitio oficial de QM.

| Demo | Archivo | Qué es |
|---|---|---|
| 1 | `calculadora_combustible.html` | Gasoil vs bi-fuel vs gas vs turbina, con fracturas reales por operadora |
| 2 | `configurador_bomba.html` | Configurador con curva de presión y caudal, ficha en PDF y cotización |
| 3 | `dashboard_flota.html` | Flota simulada en el navegador |
| 4 | `telemetria_iot/` | Data van → IoT Core → SQS → Lambda → TimescaleDB → Grafana, más un agente con Claude que propone órdenes de mantenimiento y un servidor MCP ([README](telemetria_iot/README.md)) |
| — | `infra/` | Infraestructura en AWS CDK ([README](infra/README.md) y [diagrama](infra/arquitectura.html)) |
| — | `propuesta_demos.pdf` | Propuesta resumida |

Las demos 1 a 3 son archivos HTML sueltos: se abren directo en el navegador. `index.html` y `nav.js` las enlazan entre sí cuando se sirven juntas.

## Desplegar en AWS

Con CDK: ver [infra/README.md](infra/README.md). Crea la red, la EC2 con acceso por SSM y la ingesta por IoT Core, SQS y Lambda; la instancia se instala sola al arrancar.

A mano, en cualquier Ubuntu 24.04 con los puertos 80 y 443 abiertos:

```bash
git clone https://github.com/roberpalestini97-code/demo-qm.git && cd demo-qm
bash deploy/setup-ec2.sh
```

El script instala Docker, agrega 2 GB de swap, genera la contraseña de la consola, saca el certificado HTTPS en `<ip>.sslip.io` y levanta todo. Las demos estáticas son públicas; la consola y Grafana piden usuario y contraseña. Para actualizar: `git pull && bash deploy/setup-ec2.sh` (en una EC2 del CDK, como usuario `ubuntu`; el modo AWS queda guardado en `.env`).
