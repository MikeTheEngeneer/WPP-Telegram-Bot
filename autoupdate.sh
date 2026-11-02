#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_DIR="/opt/wpp-telegram-bot"
LOG_FILE="/var/log/wpp-bot-autoupdate.log"

if [ ! -d "$TARGET_DIR/.git" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Ошибка: $TARGET_DIR не является git-репозиторием." | tee -a "$LOG_FILE"
    exit 1
fi

cd "$TARGET_DIR"

# Fetch remote updates
if ! git fetch origin main -q 2>> "$LOG_FILE"; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Ошибка git fetch (проверьте доступ SSH Deploy Key к приватному репозиторию)." >> "$LOG_FILE"
    exit 0
fi

LOCAL=$(git rev-parse HEAD 2>/dev/null || echo "")
REMOTE=$(git rev-parse origin/main 2>/dev/null || echo "")

if [ -n "$LOCAL" ] && [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🚀 Обнаружено обновление! Накатываем коммит: $REMOTE" | tee -a "$LOG_FILE"
    
    # Update files to latest commit (keeping local .env untouched)
    git reset --hard origin/main >> "$LOG_FILE" 2>&1
    
    # Update python dependencies
    "$TARGET_DIR/venv/bin/pip" install -r "$TARGET_DIR/requirements.txt" -q >> "$LOG_FILE" 2>&1
    
    # Restart bot service
    systemctl restart wpp-telegram-bot
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Бот успешно обновлен и перезапущен!" | tee -a "$LOG_FILE"
fi
