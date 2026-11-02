#!/usr/bin/env bash
set -Eeuo pipefail

echo "=========================================================="
echo "      Установка / Обновление WPP Telegram Bot             "
echo "=========================================================="

# Check root
if [ "$EUID" -ne 0 ]; then
  echo "❌ Пожалуйста, запустите скрипт с правами root (sudo bash install.sh)"
  exit 1
fi

TARGET_DIR="/opt/wpp-telegram-bot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[1/5] Проверка зависимостей системы..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip qrencode >/dev/null

echo "[2/5] Копирование обновленных файлов бота в $TARGET_DIR..."
mkdir -p "$TARGET_DIR"

# Copy files while preserving existing .env
if [ -f "$TARGET_DIR/.env" ] && [ ! -f "$SCRIPT_DIR/.env" ]; then
  cp "$TARGET_DIR/.env" "$TARGET_DIR/.env.backup"
fi

cp -r "$SCRIPT_DIR"/* "$TARGET_DIR/" 2>/dev/null || true
chmod -R 700 "$TARGET_DIR"

echo "[3/5] Проверка конфигурации .env..."
ENV_FILE="$TARGET_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo ""
  read -r -p "Введите Telegram Bot Token (от @BotFather): " USER_TOKEN
  read -r -p "Введите ваш Telegram User ID (узнать в @userinfobot): " USER_ADMIN_ID

  cat > "$ENV_FILE" <<EOF
BOT_TOKEN=${USER_TOKEN}
ADMIN_IDS=${USER_ADMIN_ID}
EOF
  chmod 600 "$ENV_FILE"
  echo "Файл .env успешно создан."
else
  echo "✅ Файл .env уже существует, ваши настройки токена сохранены."
fi

echo "[4/5] Обновление виртуального окружения Python..."
python3 -m venv "$TARGET_DIR/venv"
"$TARGET_DIR/venv/bin/pip" install --upgrade pip -q
"$TARGET_DIR/venv/bin/pip" install -r "$TARGET_DIR/requirements.txt" -q

echo "[5/5] Перезапуск службы бота..."
SERVICE_FILE="/etc/systemd/system/wpp-telegram-bot.service"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=WPP Telegram Bot for Web-Panel-Proxy
After=network.target tproxy-panel.service

[Service]
Type=simple
User=root
WorkingDirectory=$TARGET_DIR
ExecStart=$TARGET_DIR/venv/bin/python3 $TARGET_DIR/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable wpp-telegram-bot.service
systemctl restart wpp-telegram-bot.service

echo ""
echo "=========================================================="
echo "🎉 WPP Telegram Bot успешно обновлен и перезапущен!"
echo "=========================================================="
echo "Проверить статус:  systemctl status wpp-telegram-bot"
echo "Посмотреть логи:   journalctl -u wpp-telegram-bot -f"
echo ""
echo "👉 Откройте вашего бота в Telegram и отправьте команду /start"
