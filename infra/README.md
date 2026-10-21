# Infraestructura (AWS CDK, TypeScript)

Levanta una EC2 Ubuntu 24.04 que, al arrancar, clona este repo y corre `deploy/setup-ec2.sh`. No hace falta ningún paso a mano dentro del servidor.

| Recurso | Para qué |
|---|---|
| VPC con una subred pública, sin NAT Gateway | Red propia sin el costo del NAT |
| Security group 80/443, **sin puerto 22** | El acceso es por SSM, no por SSH |
| Rol con `AmazonSSMManagedInstanceCore` | `aws ssm start-session` y `aws ssm send-command` |
| IP elástica | La URL `<ip>.sslip.io` y el certificado no cambian al reiniciar |
| EBS gp3 de 30 GB, cifrado | Lo que entra en la capa gratuita |
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
