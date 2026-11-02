# README-prod · Inicialización y despliegue

Guía única para dejar las demos andando: las estáticas se publican solas en **GitHub Pages** y la telemetría completa corre en **AWS**, desplegada con el CDK del repo. El detalle de cada pieza está en [infra/README.md](infra/README.md) y [5_telemetria_iot/README.md](5_telemetria_iot/README.md).

El despliegue de AWS mantiene la forma de la infra de operación de QM: los equipos de campo publican por MQTT con certificado propio, la ingesta es serverless y desacoplada por una cola, los datos viven en una base de series temporales y el tablero se sirve desde la propia red.

## Qué corre dónde

| Pieza | Dónde | URL |
|---|---|---|
| Calculadora, configurador, flota simulada, PDF | GitHub Pages (gratis, estático) | `https://roberpalestini97-code.github.io/demo-qm/` |
| Consola en vivo, Grafana, agente, base | EC2 con Docker (AWS) | `https://<ip>.sslip.io`, la imprime `cdk deploy` |
| Ingesta MQTT → cola → base | IoT Core + SQS + Lambda (AWS) | — (se ve en CloudWatch y en la consola de SQS) |

En Pages, la consola y el tablero muestran un aviso que explica cómo levantarlos: no pueden correr estáticos.

## Arquitectura en AWS

```
 data van (EC2) ─MQTT 8883, X.509─► IoT Core ─regla─► SQS (+ DLQ) ─► Lambda ingest ─► TimescaleDB (EC2)
                                                                      └► detector ─► agente Claude ─► órdenes
 Caddy (80/443, único punto expuesto) ─► consola :8000 · Grafana :3000 · demos estáticas
```

Decisiones que replican cómo opera QM y conviene conservar:

| Decisión | Por qué |
|---|---|
| Ingesta por cola (SQS + DLQ, 5 reintentos) | Si la base se cae, no se pierde telemetría: queda en la cola y vuelve a procesarse |
| Certificado X.509 por equipo, política acotada a `qm/<set>/*` | Cada data van es un thing propio; nadie puede leer topics de otro set |
| Sin SSH, acceso por SSM | Nada de llaves repartidas; el acceso queda auditado en CloudTrail |
| VPC propia, una subred pública, sin NAT Gateway | La Lambda entra a la base por IP privada, sin exponer Postgres ni pagar NAT |
| TimescaleDB en la EC2 | RDS no soporta la extensión; la base queda a un salto de la ingesta y del tablero |
| Un solo entry point (Caddy) con basic auth | Consola y Grafana piden usuario y contraseña; las demos son públicas |

## Inicialización (una sola vez por cuenta)

Requisitos: AWS CLI v2, Node 20 o más, Python 3.12, Docker Desktop solo para [correr en local](5_telemetria_iot/README.md). Para la shell por SSM hace falta el [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html).

```bash
# 1. Usuario con permisos de admin + MFA en IAM, y su access key
aws configure --profile qm                      # región: usar la misma en todos los pasos

# 2. Infra
cd infra
npm install
npx cdk bootstrap --profile qm                  # una sola vez por cuenta y región

# 3. Verificar sin desplegar nada (corre en cualquier máquina, sin credenciales AWS)
npm run check                                   # TypeScript
npx cdk synth                                   # genera el template completo
cd ../5_telemetria_iot/app && python -m pip install -r requirements.txt -q && python -m pytest -q   # 15 tests: física, fallas, buffer, ingesta
```

## Despliegue AWS

```bash
cd infra
npx cdk deploy --profile qm                     # ~3 min de stack + 5 a 10 de instalación en la EC2
npx cdk deploy --profile qm -c alertEmail=vos@mail.com   # agrega presupuesto de US$ 1 con aviso
```

Opciones de contexto (todas opcionales):

| Clave | Default | Para qué |
|---|---|---|
| `region` | `us-east-1` | Usar la región donde QM ya opera: baja latencia y deja los datos cerca |
| `instanceType` | `t3.small` | Que figure como *free tier eligible* en la cuenta (ver [costos](#costos)) |
| `alertEmail` | — | Presupuesto de US$ 1 con aviso por mail |
| `setId` | `SET-01` | Set simulado: define el thing de IoT y los topics `qm/<set>/*` |
| `repoUrl`, `branch` | este repo, `main` | Si algún día se forkea a la cuenta de QM |

La EC2 se instala sola al arrancar (user-data): clona el repo, genera el `.env` con la contraseña de la consola, firma el certificado del data van contra IoT Core (la clave privada nunca sale de la instancia) y levanta el compose con Caddy, que saca el HTTPS de `<ip>.sslip.io` solo.

**Verificar que quedó bien:**

```bash
aws ssm start-session --target <InstanceId> --profile qm    # el ID lo imprime cdk deploy
sudo tail -f /var/log/cloud-init-output.log                 # progreso de la instalación
sudo docker compose -f docker-compose.yml -f docker-compose.ec2.yml -f docker-compose.aws.yml ps
grep DEMO_PASSWORD 5_telemetria_iot/.env                   # usuario 'qm' + esta contraseña
```

Fuera de la instancia: abrir la URL impresa por `cdk deploy` (consola y Grafana piden la contraseña de arriba; las demos son públicas) y mirar `Telemetria` / `TelemetriaDlq` en la consola de SQS para confirmar que la regla de IoT está derivando mensajes.

**Actualizar:**

- Cambio de código (app, demos, Caddyfile): por SSM, `cd ~/demo-qm && git pull && bash deploy/setup-ec2.sh`. El script es idempotente y conserva el `.env`.
- Cambio de infra (stack, tipos, red): `cdk deploy` de nuevo.

**Dar de baja:** `npx cdk destroy --profile qm`. Ojo: borra la instancia, el EBS (los datos de telemetría se pierden; snapshot antes si importan) y libera la IP elástica.

## GitHub Pages (demos estáticas)

1. Una sola vez: Settings → Pages → Source: **GitHub Actions** (el workflow suele habilitarlo solo).
2. Cada push a `main` reconstruye y publica ([.github/workflows/pages.yml](.github/workflows/pages.yml)).

El sitio lo arma `deploy/build-pages.py`: copia las demos estáticas y genera los avisos de consola y Grafana, todo con rutas relativas para funcionar bajo el subpath `/demo-qm/`. Para probarlo igual que queda publicado:

```bash
python deploy/build-pages.py --out dist
python -m http.server 8080   # desde la raíz del repo; abrir http://localhost:8080/dist/
```

## De demo a producción en QM

Lo anterior es el despliegue recomendado para la demo y un piloto. Para un ambiente productivo en la cuenta de QM, el mismo diseño con estos cambios:

| Tema | En la demo | Recomendado en producción |
|---|---|---|
| Dominio y HTTPS | `<ip>.sslip.io` (Let's Encrypt automático por Caddy) | Dominio propio en Route53 y `SITE_ADDRESS=<dominio>` en el `.env`: Caddy renueva con DNS-01, o ACM + CloudFront si se quiere CDN y WAF |
| Credenciales | `.env` plano en la EC2 | Secrets Manager o SSM Parameter Store (SecureString); el user-data las baja al arrancar y nada queda en el disco |
| API de Claude (agente) | `ANTHROPIC_API_KEY` en el `.env` | En Secrets Manager, acceso por rol de la instancia; o modo reglas (costo cero) si no se aprueba el uso |
| Backups | Ninguno | Snapshots de EBS diarios con Data Lifecycle Manager (7–30 días de retención); la base ya comprime por hipertabla |
| Observabilidad | Logs de Docker + presupuesto de US$ 1 | Alarmas de CloudWatch: mensajes en la DLQ > 0, errores de la Lambda, CPU/disco de la EC2, y una alarma por "bombas sin telemetría reciente" (detecta data vans caídos) |
| Acceso a consola/Grafana | basic auth de Caddy | SSO corporativo delante (ALB + Cognito o CloudFront Access); basic auth alcanza si es interno y acotado |
| CI/CD | `cdk deploy` desde la máquina | GitHub Actions con OIDC: un rol asumible por el repo, sin claves AWS en GitHub; cada PR corre `cdk synth` + tests, y el merge a main despliega |
| Escalado | 1 set simulado, 1 EC2 | Un thing + política por set (`qm/SET-XX/*`), la Lambda y la base compartidas y particionadas por set; el contrato de mensajes no cambia |
| Instancia | `t3.small`, 30 GB | Right-size según carga (RAM para TimescaleDB) y EBS según retención |
| Simulador | Corre en la EC2 | Se apaga (`docker compose ... stop simulator`): los data vans reales publican en el mismo topic `qm/<set>/telemetria` |

Snippet de CI/CD con OIDC (lo único que hay que agregar a un workflow como el de Pages):

```yaml
permissions: { id-token: write, contents: read }
steps:
  - uses: aws-actions/configure-aws-credentials@v4
    with:
      role-to-assume: arn:aws:iam::<cuenta-qm>:role/github-deploy-qm
      aws-region: us-east-1
  - run: npx cdk deploy --require-approval never
```

…con la trust policy del rol limitada a `repo:<org-qm>/demo-qm:ref:refs/heads/main`.

## Operación diaria

| Tarea | Cómo |
|---|---|
| Entrar al servidor | `aws ssm start-session --target <InstanceId> --profile qm` |
| Ver qué pasa | `sudo docker compose -f docker-compose.yml -f docker-compose.ec2.yml -f docker-compose.aws.yml logs -f simulator agent ingest-lambda` |
| Cola y DLQ | Consola de SQS, o `aws sqs get-queue-attributes --queue-url <url> --attribute-names ApproximateNumberOfMessages` |
| Corridas del agente | Tabla `corridas_agente` en la base: tokens, costo y acciones por corrida |
| Rotar la contraseña | En la EC2: editar `DEMO_PASSWORD`/`DEMO_PASSWORD_HASH` del `.env` (hash con `docker run --rm caddy:2.8.4-alpine caddy hash-password --plaintext '<nueva>'`) y `docker compose ... up -d caddy` |
| Parte del día | Botón en la consola; usa Haiku si hay API key, si no sale del modo reglas |

## Costos

Orden de magnitud en `us-east-1`, sin compromisos:

| Recurso | Demo (layer gratuito) | Producción |
|---|---|---|
| EC2 | 750 h/mes incluidas (t3.small/micro *eligible*), después ~US$ 15/mes | ~US$ 15–60/mes según tipo |
| EBS gp3 30 GB | Incluido | ~US$ 2,40/mes + ~US$ 0,05/GB/mes de snapshots |
| IPv4 pública | ~US$ 3,60/mes (cubierto por créditos en cuentas nuevas) | ~US$ 3,60/mes (o IPv6 solo) |
| IoT Core | 500 mil mensajes + 250 mil reglas/mes (12 meses). Con `SAMPLE_SECONDS=15` son ~173 mil/mes | ~US$ 1/millón de mensajes |
| SQS + Lambda | 1 millón de pedidos/mes, siempre gratis | Gratis a este volumen |
| Secrets Manager | — | US$ 0,40/secreto/mes |
| CloudWatch | Métricas básicas gratis | ~US$ 0,10 por alarma/mes |

El presupuesto de US$ 1 con `-c alertEmail` avisa ante el primer gasto inesperado. En cuentas creadas después de julio de 2025 la capa gratuita cambió a créditos + 6 meses: revisar qué aplica a la cuenta antes de desplegar.

## Checklist completo

```bash
git clone https://github.com/roberpalestini97-code/demo-qm.git && cd demo-qm
aws configure --profile qm
cd infra && npm install && npx cdk bootstrap --profile qm
npx cdk deploy --profile qm -c alertEmail=vos@mail.com     # anotar URL e InstanceId de los outputs
aws ssm start-session --target <InstanceId> --profile qm   # sudo tail -f /var/log/cloud-init-output.log
```

Y Pages: Settings → Pages → Source GitHub Actions, una sola vez. Después, todo se actualiza con push a `main` o `git pull` + `setup-ec2.sh` en la EC2.
