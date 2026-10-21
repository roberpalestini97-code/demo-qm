# Infraestructura (AWS CDK, TypeScript)

Levanta todas las demos y la ingesta de telemetría por IoT Core. La EC2, al arrancar, clona este repo, genera el certificado del data van y corre `deploy/setup-ec2.sh`. No hace falta ningún paso a mano dentro del servidor.

```n data van (EC2) ─MQTT 8883, X.509─► IoT Core ─regla─► SQS (+ DLQ) ─► Lambda ingest ─► TimescaleDB (EC2)
```

En local, el mismo camino corre en Docker con Mosquitto, ElasticMQ y el mismo handler de Lambda (ver `5_telemetria_iot/README.md`).

| Recurso | Para qué |
|---|---|
| VPC con una subred pública, sin NAT Gateway | Red propia sin el costo del NAT |
| Security group 80/443, **sin puerto 22** | El acceso es por SSM, no por SSH |
| Rol con `AmazonSSMManagedInstanceCore` | `aws ssm start-session` y `aws ssm send-command` |
| IP elástica | La URL `<ip>.sslip.io` y el certificado no cambian al reiniciar |
| EBS gp3 de 30 GB, cifrado | Lo que entra en la capa gratuita |
| IoT Core: thing `datavan-SET-01` y política acotada a `qm/SET-01/*` | El simulador y la consola publican y reciben comandos |
| Regla de IoT `qm/SET-01/{telemetria,eventos}` → SQS | Igual a `iot-rule` en local |
| SQS `telemetria` + `telemetria-dlq` (5 intentos) | Amortigua si la base no responde |
| Lambda `qm.lambda_ingest.handler` (Python 3.12, en la VPC) | Escribe en TimescaleDB por IP privada; el puerto 5432 solo acepta tráfico de la Lambda |
| Presupuesto de US$ 1 (opcional) | Aviso por mail ante el primer gasto |

## Uso

```bash
npm install
npx cdk bootstrap --profile qm                 # una sola vez por cuenta y región
npx cdk deploy --profile qm                    # unos 3 minutos, más 5 a 10 de instalación dentro de la EC2
npx cdk deploy --profile qm -c alertEmail=vos@mail.com -c instanceType=t3.micro
npx cdk destroy --profile qm                   # borra todo
```

Para entrar al servidor sin SSH (requiere el Session Manager plugin):

```bash
aws ssm start-session --target <InstanceId> --profile qm
```

Para ver cómo va la instalación: `sudo tail -f /var/log/cloud-init-output.log`.

## Costos

- **Instancia y disco:** dentro de la capa gratuita (o de los créditos del plan gratuito) si el tipo figura como *free tier eligible*. Para listar cuáles lo son en tu cuenta: `aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true --query "InstanceTypes[].InstanceType" --profile qm`.
- **IPv4 pública:** AWS cobra unos US$ 3,60 por mes por IPv4 pública. En cuentas nuevas lo cubren la capa gratuita o los créditos.
- **SSM Session Manager:** sin costo.
- **IoT Core:** en el free tier de 12 meses entran 500 mil mensajes y 250 mil disparos de regla por mes. En modo AWS el simulador publica cada 15 s (unos 173 mil por mes).
- **SQS y Lambda:** 1 millón de pedidos por mes cada uno, siempre gratis.

El paquete de la Lambda se arma sin Docker: pip baja psycopg compilado para Linux (`manylinux2014_x86_64`) desde cualquier sistema.
