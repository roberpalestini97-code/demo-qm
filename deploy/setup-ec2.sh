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
  TOKEN=$(curl -fsS -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
  IP=$(curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
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

echo "== Levantando"
cd "$APP"
sudo docker compose -f docker-compose.yml -f docker-compose.ec2.yml up -d --build
sudo docker compose -f docker-compose.yml -f docker-compose.ec2.yml ps
echo
echo "Listo: $(grep ^PUBLIC_URL "$ENV" | cut -d= -f2)"
echo "Consola y Grafana piden usuario 'qm' y la contraseña de $ENV"
