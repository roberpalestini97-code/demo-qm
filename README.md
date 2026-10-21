# demo-qm

Prototipos para QM Equipment, hechos por Rober Palestini. Es una demo independiente, no un sitio oficial de QM.

| Demo | Archivo | Qué es |
|---|---|---|
| 1 | `1_calculadora_combustible.html` | Gasoil vs bi-fuel vs gas vs turbina, con fracturas reales por operadora |
| — | `2_canva_propuesta_demos.pdf` | Propuesta resumida |
| 2 | `3_configurador_bomba.html` | Configurador con curva de presión y caudal, ficha en PDF y cotización |
| 3 | `4_dashboard_flota.html` | Flota simulada en el navegador |
| 4 | `5_telemetria_iot/` | MQTT → TimescaleDB → Grafana, más un agente con Claude que propone órdenes de mantenimiento ([README](5_telemetria_iot/README.md)) |

Las demos 1 a 3 son archivos HTML sueltos: se abren directo en el navegador. `index.html` y `nav.js` las enlazan entre sí cuando se sirven juntas.

## Desplegar en AWS

Con CDK: ver [infra/README.md](infra/README.md). Crea la EC2, la red y el acceso por SSM, y la instancia se instala sola al arrancar.

A mano, en cualquier Ubuntu 24.04 con los puertos 80 y 443 abiertos:

```bash
git clone https://github.com/roberpalestini97-code/demo-qm.git && cd demo-qm
bash deploy/setup-ec2.sh
```

El script instala Docker, agrega 2 GB de swap, genera la contraseña de la consola, saca el certificado HTTPS en `<ip>.sslip.io` y levanta todo. Las demos estáticas son públicas; la consola y Grafana piden usuario y contraseña. Para actualizar: `git pull && bash deploy/setup-ec2.sh`.
