"""Configuration loader for WPP Telegram Bot."""
import os
import re
from pathlib import Path

# Load from .env if present
env_path = Path(__file__).parent / ".env"
if env_path.is_file():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
    except ImportError:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

# Admin IDs list
raw_admins = os.environ.get("ADMIN_IDS", "").strip()
ADMIN_IDS = set()
if raw_admins:
    for item in raw_admins.split(","):
        item = item.strip()
        if item.isdigit():
            ADMIN_IDS.add(int(item))

# System paths
MANAGER_BIN = Path("/usr/local/sbin/web-proxy-panelctl")
APP_DIR = Path("/opt/tproxy-panel")
USERS_FILE = Path("/etc/web-proxy-panel/users.json")
CONNECTIONS_FILE = Path("/etc/web-proxy-panel/connections.json")
TRAFFIC_FILE = Path("/var/lib/tproxy-panel/traffic.json")
METRICS_FILE = Path("/var/lib/tproxy-panel/metrics.json")
DATA_FILE = Path("/var/lib/tproxy-panel/data.json")
XRAY_PATH_FILE = Path("/etc/web-proxy-panel/xray-path")
PRIMARY_SECRET_FILE = Path("/etc/web-proxy-panel/primary-secret")
MTPROTO_HOST_FILE = Path("/etc/web-proxy-panel/mtproto-host")
PANEL_SERVICE = Path("/etc/systemd/system/tproxy-panel.service")
CADDY_CONF = Path("/etc/systemd/system/caddy.service.d/tproxy.conf")


def detect_domain() -> str:
    """Auto-detect WPP domain from system configuration files."""
    custom = os.environ.get("WPP_DOMAIN", "").strip()
    if custom:
        return custom.lower().strip()

    # Try tproxy-panel.service
    if PANEL_SERVICE.is_file():
        try:
            for line in PANEL_SERVICE.read_text(encoding="utf-8").splitlines():
                if line.startswith("Environment=WEBPROXY_DOMAIN="):
                    dom = line.split("=", 2)[-1].strip()
                    if dom:
                        return dom.lower()
        except OSError:
            pass

    # Try Caddy drop-in
    if CADDY_CONF.is_file():
        try:
            for line in CADDY_CONF.read_text(encoding="utf-8").splitlines():
                if line.startswith("Environment=TPROXY_HOSTNAME="):
                    dom = line.split("=", 2)[-1].strip()
                    if dom:
                        return dom.lower()
        except OSError:
            pass

    # Try data.json or fallback
    return "localhost"


DOMAIN = detect_domain()
