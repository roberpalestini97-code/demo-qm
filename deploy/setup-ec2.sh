#!/usr/bin/env bash
# Prepara una EC2 (Ubuntu 24.04 o Amazon Linux 2023) y levanta todas las demos.
# Uso, desde la carpeta del repo ya clonado:  bash deploy/setup-ec2.sh
# Es idempotente: se puede volver a correr después de un git pull.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
APP=$ROOT/5_telemetria_iot

echo "== Docker"
if ! command -v docker >/dev/null; then
  if command -v apt-get >/dev/null; then
    sudo apt-get update -y
    sudo apt-get install -y docker.io docker-compose-v2
  else
    sudo dnf install -y docker
    sudo mkdir -p /usr/local/lib/docker/cli-plugins
    sudo curl -fsSL -o /usr/local/lib/docker/cli-plugins/docker-compose \
      "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-$(uname -m)"
    sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  fi
  sudo systemctl enable --now docker
  sudo usermod -aG docker "$USER"
fi

echo "== Swap de 2 GB (la micro tiene 1 GB de RAM)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "== Configuración (.env)"
ENV=$APP/.env
if [ ! -f "$ENV" ]; then
  if [ -z "${PUBLIC_IP:-}" ]; then
  TOKEN=$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
  PUBLIC_IP=$(curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
  fi
  IP=$PUBLIC_IP
  HOST="${IP//./-}.sslip.io"
  PASS=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-16)
  HASH=$(sudo docker run --rm caddy:2.8.4-alpine caddy hash-password --plaintext "$PASS")
  cat > "$ENV" <<EOF
SITE_ADDRESS=$HOST
PUBLIC_URL=https://$HOST
DEMO_USER=qm
DEMO_PASSWORD=$PASS
DEMO_PASSWORD_HASH='$HASH'
ANTHROPIC_API_KEY=
AGENT_INTERVAL=120
SAMPLE_SECONDS=5
EOF
  chmod 600 "$ENV"
  echo "Creado $ENV (usuario y contraseña de la consola adentro)"
fi

FILES="-f docker-compose.yml -f docker-compose.ec2.yml"

# Modo AWS: el CDK pasa IOT_THING e IOT_POLICY. La clave privada se genera acá y nunca sale de la EC2;
# el rol de la instancia firma el certificado en IoT Core a partir del CSR.
if [ -n "${IOT_THING:-}" ]; then
  echo "== IoT Core ($IOT_THING)"
  export AWS_DEFAULT_REGION=${AWS_REGION:-us-east-1}
  command -v aws >/dev/null || sudo snap install aws-cli --classic
  CERTS=$APP/certs
  if [ ! -f "$CERTS/device.pem.crt" ]; then
    mkdir -p "$CERTS"
    openssl req -new -newkey rsa:2048 -nodes -subj "/CN=$IOT_THING" \
      -keyout "$CERTS/private.pem.key" -out "$CERTS/device.csr"
    ARN=$(aws iot create-certificate-from-csr --set-as-active \
      --certificate-signing-request "file://$CERTS/device.csr" \
      --certificate-pem-outfile "$CERTS/device.pem.crt" --query certificateArn --output text)
    aws iot attach-policy --policy-name "$IOT_POLICY" --target "$ARN"
    aws iot attach-thing-principal --thing-name "$IOT_THING" --principal "$ARN"
    curl -fsS -o "$CERTS/AmazonRootCA1.pem" https://www.amazontrust.com/repository/AmazonRootCA1.pem
    chmod 644 "$CERTS"/*   # los contenedores corren con otro usuario; la EC2 es de un solo uso
  fi
  if ! grep -q '^MQTT_HOST=' "$ENV"; then
    ENDPOINT=$(aws iot describe-endpoint --endpoint-type iot:Data-ATS --query endpointAddress --output text)
    sed -i 's/^SAMPLE_SECONDS=.*/SAMPLE_SECONDS=15/' "$ENV"   # dentro de los 250 mil mensajes de regla por mes
    cat >> "$ENV" <<EOF
MQTT_HOST=$ENDPOINT
MQTT_PORT=8883
MQTT_CA=/certs/AmazonRootCA1.pem
MQTT_CERT=/certs/device.pem.crt
MQTT_KEY=/certs/private.pem.key
AWS_REGION=$AWS_DEFAULT_REGION
EOF
  fi
  FILES="$FILES -f docker-compose.aws.yml"
fi

echo "== Levantando"
cd "$APP"
sudo docker compose $FILES up -d --build --remove-orphans
sudo docker compose $FILES ps
echo
echo "Listo: $(grep ^PUBLIC_URL "$ENV" | cut -d= -f2)"
echo "Consola y Grafana piden usuario 'qm' y la contraseña de $ENV"
