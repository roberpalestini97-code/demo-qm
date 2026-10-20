# qm-demos

Prototipos para QM Equipment, hechos por Rober Palestini. Es una demo independiente, no un sitio oficial de QM.

| Demo | Archivo | Qué es |
|---|---|---|
| 1 | `1_calculadora_combustible.html` | Gasoil vs bi-fuel vs gas vs turbina, con fracturas reales por operadora |
| — | `2_canva_propuesta_demos.pdf` | Propuesta resumida |
| 2 | `3_configurador_bomba.html` | Configurador con curva de presión y caudal, ficha en PDF y cotización |
| 3 | `4_dashboard_flota.html` | Flota simulada en el navegador |
| 4 | `5_telemetria_iot/` | MQTT → TimescaleDB → Grafana, más un agente con Claude que propone órdenes de mantenimiento ([README](5_telemetria_iot/README.md)) |

Las demos 1 a 3 son archivos HTML sueltos: se abren directo en el navegador. `index.html` y `nav.js` las enlazan entre sí cuando se sirven juntas.

## Desplegar en una EC2

1. EC2 **Ubuntu 24.04**, tipo micro o small que figure como *Free tier eligible*, con 20 a 30 GB de disco.
2. Security group: 22 solo desde tu IP; 80 y 443 abiertos.
3. En la EC2:

```bash
git clone <url-del-repo> qm-demos && cd qm-demos
bash deploy/setup-ec2.sh
```

El script instala Docker, agrega 2 GB de swap, genera la contraseña de la consola, saca el certificado HTTPS en `<ip>.sslip.io` y levanta todo. Las demos estáticas son públicas; la consola y Grafana piden usuario y contraseña.

Para actualizar: `git pull && bash deploy/setup-ec2.sh`.
