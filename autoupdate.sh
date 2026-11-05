#!/usr/bin/env bash
# Pulls the git checkout this script lives in (e.g. /opt/wpp-telegram-bot-src) and,
# when there is a new commit, re-runs install.sh which copies files into /opt/wpp-telegram-bot.
# Example cron (every 15 minutes):
#   */15 * * * * root /opt/wpp-telegram-bot-src/autoupdate.sh
set -Eeuo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/var/log/wpp-bot-autoupdate.log"
BRANCH="${WPP_BOT_BRANCH:-main}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }

# Never run two updates at once (cron + manual run)
exec 9>/run/wpp-bot-autoupdate.lock
flock -n 9 || exit 0

if [ ! -d "$SRC_DIR/.git" ]; then
    log "Ошибка: $SRC_DIR не является git-репозиторием (склонируйте репозиторий и запускайте autoupdate.sh оттуда)."
    exit 1
fi

cd "$SRC_DIR"

if ! git fetch origin "$BRANCH" -q 2>> "$LOG_FILE"; then
    log "Ошибка git fetch (нет сети или доступа к репозиторию)."
    exit 0
fi

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")
[ "$LOCAL" = "$REMOTE" ] && exit 0

log "🚀 Обнаружено обновление: $LOCAL -> $REMOTE"

# Fast-forward only: local edits or a rewritten remote history stop the update instead of being silently discarded
if ! git merge --ff-only "origin/$BRANCH" -q >> "$LOG_FILE" 2>&1; then
    log "❌ Не удалось обновиться fast-forward (локальные изменения или переписанная история). Обновите вручную."
    exit 1
fi

# install.sh is non-interactive when /opt/wpp-telegram-bot/.env already exists
if bash "$SRC_DIR/install.sh" >> "$LOG_FILE" 2>&1; then
    log "✅ Бот успешно обновлен и перезапущен!"
else
    log "❌ install.sh завершился с ошибкой, подробности выше."
    exit 1
fi
