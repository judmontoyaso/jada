#!/bin/bash
# deploy.sh — Setup inicial de Jada en Digital Ocean
# Ejecutar: bash deploy.sh
set -e

REPO="https://github.com/judmontoyaso/jada.git"
APP_DIR="/opt/jada"
SERVICE_NAME="jada"

echo "🖤 Desplegando Jada en $(hostname)..."

# 1. Dependencias del sistema
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv git curl

# 2. Clonar o actualizar repo
if [ -d "$APP_DIR/.git" ]; then
    echo "📦 Actualizando repo..."
    cd "$APP_DIR"
    git pull origin main
else
    echo "📦 Clonando repo..."
    git clone "$REPO" "$APP_DIR"
    cd "$APP_DIR"
fi

# 3. Entorno virtual
echo "🐍 Configurando virtualenv..."
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

# 4. Verificar .env
if [ ! -f "$APP_DIR/.env" ]; then
    echo "⚠️  No hay .env — copia .env.example y completa con tus credenciales:"
    echo "    cp $APP_DIR/.env.example $APP_DIR/.env"
    echo "    nano $APP_DIR/.env"
fi

# 5. Crear servicio systemd
cat > /etc/systemd/system/jada.service << EOF
[Unit]
Description=Jada AI Agent — Personal AI by 5panes
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
EnvironmentFile=$APP_DIR/.env

[Install]
WantedBy=multi-user.target
EOF

# 6. Activar y arrancar
systemctl daemon-reload
systemctl enable $SERVICE_NAME

echo ""
echo "✅ Setup completo. Próximos pasos:"
echo "   1. Edita el .env:  nano $APP_DIR/.env"
echo "   2. Inicia Jada:    systemctl start jada"
echo "   3. Ver logs:       journalctl -u jada -f"
echo ""
echo "Estado actual:"
systemctl status $SERVICE_NAME --no-pager 2>/dev/null || echo "(servicio no iniciado aún)"
