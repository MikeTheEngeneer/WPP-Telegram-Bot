"""Service layer for interacting with web-panel-proxy core, CLI, connections and live traffic."""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.parse import quote, urlencode

from config import (
    APP_DIR,
    CONNECTIONS_FILE,
    DATA_FILE,
    DOMAIN,
    MANAGER_BIN,
    METRICS_FILE,
    MTPROTO_HOST_FILE,
    PRIMARY_SECRET_FILE,
    TRAFFIC_FILE,
    USERS_FILE,
    XRAY_PATH_FILE,
)

# Add APP_DIR to sys.path so we can import wpp_* helpers if present on VPS
if APP_DIR.is_dir() and str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def format_bytes(value: float) -> str:
    """Format bytes to human readable string."""
    if value is None or value <= 0:
        return "0 Б"
    units = ["Б", "КБ", "МБ", "ГБ", "ТБ"]
    v = float(value)
    for u in units:
        if v < 1024 or u == "ТБ":
            return f"{v:.0f} {u}" if u == "Б" else f"{v:.1f} {u}"
        v /= 1024
    return f"{v:.1f} ГБ"


def format_speed(bytes_per_sec: float) -> str:
    """Format speed in bytes/sec to human readable string."""
    if bytes_per_sec < 1024:
        return f"{bytes_per_sec:.0f} Б/с"
    elif bytes_per_sec < 1024 * 1024:
        return f"{bytes_per_sec / 1024:.1f} КБ/с"
    elif bytes_per_sec < 1024 * 1024 * 1024:
        return f"{bytes_per_sec / (1024 * 1024):.1f} МБ/с"
    else:
        return f"{bytes_per_sec / (1024 * 1024 * 1024):.2f} ГБ/с"


def run_ctl(*args: str, input_json: dict = None) -> dict:
    """Execute /usr/local/sbin/web-proxy-panelctl command safely."""
    if not MANAGER_BIN.is_file():
        raise RuntimeError("web-proxy-panelctl не найден. Запустите бота на VPS с установленным WPP.")

    cmd = [str(MANAGER_BIN), *args]
    stdin_data = json.dumps(input_json) if input_json else None

    proc = subprocess.run(
        cmd,
        input=stdin_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )

    if proc.returncode != 0:
        err = proc.stderr.strip() or "Команда завершилась с ошибкой"
        raise RuntimeError(err)

    out = proc.stdout.strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"raw": out}


def run_subscription(payload: dict) -> dict:
    """`panelctl subscription` reports failures as {"ok": false} with exit code 0, so check it explicitly."""
    res = run_ctl("subscription", input_json=payload)
    if isinstance(res, dict) and res.get("ok") is False:
        raise RuntimeError(res.get("message") or "Операция с подпиской не выполнена")
    return res


class LiveTrafficTracker:
    """Real-time 3-second traffic delta sampler directly from Xray, AWG and kernel."""
    def __init__(self):
        self.last_sample_time = 0.0
        self.last_user_bytes = {}  # {uid: {"up": int, "down": int}}
        self.connection_speeds = {}  # {cid: {"speed_total": float, "speed_human": str, "last_active_time": float}}
        # sample() runs both from the background worker thread and from handler threads
        self.lock = threading.Lock()

    def get_live_raw_user_counters(self, users: list[dict]) -> dict:
        result = {}

        # 1. Direct query to Xray API (instant memory counter, ~20ms)
        xray_bin = Path("/opt/web-panel-proxy/xray/xray")
        if xray_bin.is_file():
            try:
                p = subprocess.run(
                    [str(xray_bin), "api", "statsquery", "--server=127.0.0.1:10085"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=3,
                )
                if p.returncode == 0:
                    start = p.stdout.find("{")
                    if start != -1:
                        doc = json.loads(p.stdout[start:])
                        for stat in doc.get("stat", []):
                            m = re.fullmatch(
                                r"user>>>panel:([a-f0-9]+)(?::\d+)?>>>traffic>>>(uplink|downlink)",
                                str(stat.get("name", "")),
                            )
                            if not m:
                                continue
                            uid = m.group(1)
                            direction = "up" if m.group(2) == "uplink" else "down"
                            result.setdefault(uid, {"up": 0, "down": 0})[direction] += int(stat.get("value", 0))
            except Exception:
                pass

        # 2. AmneziaWG counters
        for awg_path in ("/usr/local/bin/awg", "/usr/bin/wg"):
            if Path(awg_path).is_file():
                try:
                    by_key = {u.get("public_key"): u.get("id") for u in users if u.get("public_key")}
                    p = subprocess.run([awg_path, "show", "all", "dump"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
                    if p.returncode == 0:
                        for line in p.stdout.splitlines():
                            cols = line.split("\t")
                            if len(cols) >= 8 and cols[1] in by_key:
                                uid = by_key[cols[1]]
                                result[uid] = {"up": int(cols[6]), "down": int(cols[7])}
                except Exception:
                    pass
                break

        # No traffic.json fallback here: its persisted totals use a different base than the live
        # Xray/AWG counters, so mixing them produced fake multi-GB/s spikes on the next sample.
        return result

    def sample(self, users: list[dict], connections: list[dict]):
        with self.lock:
            self._sample(users, connections)

    def _sample(self, users: list[dict], connections: list[dict]):
        now = time.time()
        current_raw = self.get_live_raw_user_counters(users)

        if not self.last_user_bytes or self.last_sample_time == 0:
            self.last_user_bytes = current_raw
            self.last_sample_time = now
            return

        elapsed = max(0.5, now - self.last_sample_time)
        user_speeds = {}

        for uid, cur in current_raw.items():
            prev = self.last_user_bytes.get(uid)
            if prev is None:
                # First time we see this user: no baseline yet, otherwise the whole counter counts as a delta
                continue
            delta_up = max(0, cur.get("up", 0) - prev.get("up", 0))
            delta_down = max(0, cur.get("down", 0) - prev.get("down", 0))
            user_speeds[uid] = {
                "speed_up": delta_up / elapsed,
                "speed_down": delta_down / elapsed,
                "speed_total": (delta_up + delta_down) / elapsed,
            }

        # Aggregate per connection
        for item in connections:
            cid = str(item.get("id", ""))
            matching_users = [u for u in users if str(u.get("connection_id", "")) == cid]

            c_speed_up = sum(user_speeds.get(str(u.get("id")), {}).get("speed_up", 0.0) for u in matching_users)
            c_speed_down = sum(user_speeds.get(str(u.get("id")), {}).get("speed_down", 0.0) for u in matching_users)
            c_speed_total = c_speed_up + c_speed_down

            entry = self.connection_speeds.setdefault(cid, {
                "speed_up": 0.0,
                "speed_down": 0.0,
                "speed_total": 0.0,
                "speed_human": "0 Б/с",
                "last_active_time": 0.0,
            })

            entry["speed_up"] = c_speed_up
            entry["speed_down"] = c_speed_down
            entry["speed_total"] = c_speed_total
            entry["speed_human"] = format_speed(c_speed_total)

            # More than 512 B/s over the 3-second sample indicates real active traffic (filters out background pings)
            if c_speed_total > 512:
                entry["last_active_time"] = now

        self.last_user_bytes = current_raw
        self.last_sample_time = now


# Global live tracker instance
live_tracker = LiveTrafficTracker()


class WPPService:
    @staticmethod
    def get_domain() -> str:
        return DOMAIN

    @staticmethod
    def get_xray_path() -> str:
        if XRAY_PATH_FILE.is_file():
            try:
                return XRAY_PATH_FILE.read_text(encoding="utf-8").strip()
            except OSError:
                pass
        return "/xhttp"

    @classmethod
    def get_raw_state(cls) -> dict:
        """Read users and subscriptions data."""
        if USERS_FILE.is_file():
            try:
                with open(USERS_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        try:
            return run_ctl("users")
        except Exception:
            return {"users": [], "subscriptions": []}

    @classmethod
    def get_traffic_state(cls) -> dict:
        """Read traffic counters."""
        if TRAFFIC_FILE.is_file():
            try:
                with open(TRAFFIC_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        try:
            return run_ctl("traffic")
        except Exception:
            return {}

    @classmethod
    def sample_live_traffic(cls):
        """Perform one 3-second live traffic sample directly from Xray and network."""
        state = cls.get_raw_state()
        users = state.get("users", [])
        conns_raw = []
        if CONNECTIONS_FILE.is_file():
            try:
                with open(CONNECTIONS_FILE, encoding="utf-8") as f:
                    conns_raw = json.load(f).get("connections", [])
            except Exception:
                pass
        live_tracker.sample(users, conns_raw)

    @classmethod
    def get_connections(cls) -> list[dict]:
        """Return server transport connections with high-precision 3-5 sec live traffic detection."""
        state = cls.get_raw_state()
        traffic = cls.get_traffic_state()
        users = state.get("users", [])
        subs = state.get("subscriptions", [])

        # Trigger sample if never sampled or older than 5s
        if time.time() - live_tracker.last_sample_time > 5:
            cls.sample_live_traffic()

        connections_raw = []
        if CONNECTIONS_FILE.is_file():
            try:
                with open(CONNECTIONS_FILE, encoding="utf-8") as f:
                    doc = json.load(f)
                    connections_raw = doc.get("connections", [])
            except Exception:
                pass

        sub_names = {s.get("id"): s.get("name", "Подписка") for s in subs}
        now = time.time()
        result = []

        for item in connections_raw:
            cid = str(item.get("id", ""))
            protocol = str(item.get("protocol", "")).lower()
            cfg = item.get("config") if isinstance(item.get("config"), dict) else {}
            enabled = bool(item.get("enabled", True))

            route_type = cfg.get("route", "direct")
            provider = str(cfg.get("provider", "")).lower()
            public_host = cfg.get("public_host") or cfg.get("sni") or cls.get_domain()

            if protocol == "vless" and route_type == "cdn":
                route_label = f"Через {provider.title() or 'CDN'} ({public_host})"
            else:
                route_label = "Напрямую"

            if protocol in ("vless", "web"):
                port = "443"
            elif protocol == "hysteria":
                port = str(item.get("advanced", {}).get("inbound", {}).get("port") or cfg.get("port") or 8443)
            elif protocol in ("awg20", "awg31"):
                awg_p = cfg.get("port") or 0
                port = str(awg_p) if awg_p else "Авто"
            elif protocol == "mtproto":
                port = str(cfg.get("port") or 2399)
            else:
                port = str(cfg.get("port") or 443)

            mode = str(cfg.get("transport") or cfg.get("mode") or ("UDP" if protocol in ("hysteria", "awg20", "awg31") else "AUTO")).upper()

            matching_users = [u for u in users if str(u.get("connection_id", "")) == cid]

            conn_up = 0
            conn_down = 0
            assigned_clients_names = []

            for u in matching_users:
                uid = str(u.get("id", ""))
                t = traffic.get(uid, {})
                conn_up += t.get("up", 0)
                conn_down += t.get("down", 0)

                sub_id = u.get("subscription_id")
                if sub_id and sub_id in sub_names:
                    assigned_clients_names.append(f"{sub_names[sub_id]} (Подписка)")
                else:
                    assigned_clients_names.append(u.get("name", "Клиент"))

            total_bytes = conn_up + conn_down

            # Live speed data from the 3-5 sec tracker
            speed_info = live_tracker.connection_speeds.get(cid, {})
            current_speed_bps = speed_info.get("speed_total", 0.0)
            last_active_ts = speed_info.get("last_active_time", 0.0)
            speed_human = speed_info.get("speed_human", "0 Б/с")

            # Active now if current speed > 512 B/s OR transfer detected in the last 5 seconds!
            is_active_now = (current_speed_bps > 512) or (last_active_ts > 0 and (now - last_active_ts <= 5))

            if is_active_now and current_speed_bps > 512:
                last_seen_str = f"🔥 {speed_human}"
            elif is_active_now:
                last_seen_str = "🔥 ТРАФИК ИДЕТ СЕЙЧАС"
            elif last_active_ts > 0:
                diff = int(now - last_active_ts)
                if diff < 60:
                    last_seen_str = f"{diff} сек. назад"
                elif diff < 3600:
                    last_seen_str = f"{diff // 60} мин. назад"
                else:
                    last_seen_str = f"{diff // 3600} ч. назад"
            else:
                last_seen_str = "Не использовался"

            unique_clients = list(dict.fromkeys(assigned_clients_names))

            result.append({
                "id": cid,
                "name": item.get("name", cid),
                "protocol": protocol,
                "enabled": enabled,
                "port": port,
                "mode": mode,
                "route_label": route_label,
                "public_host": public_host,
                "traffic_up": conn_up,
                "traffic_down": conn_down,
                "traffic_total": total_bytes,
                "traffic_human": format_bytes(total_bytes),
                "clients_count": len(matching_users),
                "clients_list": unique_clients,
                "is_active_now": is_active_now,
                "speed_bps": current_speed_bps,
                "speed_str": speed_human,
                "last_seen_str": last_seen_str,
                "last_active_ts": last_active_ts,
            })

        return result

    @classmethod
    def get_connection_by_id(cls, conn_id: str) -> dict | None:
        for c in cls.get_connections():
            if str(c.get("id")) == str(conn_id):
                return c
        return None

    @classmethod
    def toggle_connection(cls, conn_id: str, enable: bool) -> bool:
        """Toggle a transport the same way the web panel does, rolling back if the services fail to apply it."""
        if not CONNECTIONS_FILE.is_file():
            raise RuntimeError("Файл connections.json не найден")

        try:
            import wpp_connections as store
        except ImportError:
            store = None

        if store is not None:
            previous = store.load(str(CONNECTIONS_FILE))
            existing = store.get(previous, conn_id)
            if not isinstance(existing, dict):
                raise RuntimeError(f"Подключение {conn_id} не найдено")
            updated = dict(existing)
            updated["enabled"] = bool(enable)
            store.upsert(str(CONNECTIONS_FILE), updated)
            try:
                run_ctl("connections-refresh")
            except Exception:
                store.save(str(CONNECTIONS_FILE), previous)
                try:
                    run_ctl("connections-refresh")
                except Exception:
                    pass
                raise
            return True

        # Fallback without panel modules: atomic write that keeps the original 0600 permissions
        original = CONNECTIONS_FILE.read_text(encoding="utf-8")
        data = json.loads(original)
        conn = next((c for c in data.get("connections", []) if str(c.get("id")) == str(conn_id)), None)
        if conn is None:
            raise RuntimeError(f"Подключение {conn_id} не найдено")
        conn["enabled"] = bool(enable)

        def write(text: str):
            tmp = CONNECTIONS_FILE.with_name(CONNECTIONS_FILE.name + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, CONNECTIONS_FILE)

        write(json.dumps(data, ensure_ascii=False, indent=2))
        try:
            run_ctl("connections-refresh")
        except Exception:
            write(original)
            raise
        return True

    @classmethod
    def get_clients(cls, include_subscriptions: bool = True) -> list[dict]:
        """Return proxy clients with traffic statistics."""
        state = cls.get_raw_state()
        traffic = cls.get_traffic_state()
        subs = state.get("subscriptions", [])
        sub_names = {s.get("id"): s.get("name", "Подписка") for s in subs}

        users = state.get("users", [])
        result = []
        for u in users:
            uid = str(u.get("id", ""))
            sub_id = u.get("subscription_id")

            if not include_subscriptions and sub_id:
                continue

            user_traffic = traffic.get(uid, {})
            up = user_traffic.get("up", 0)
            down = user_traffic.get("down", 0)
            total = up + down

            client = dict(u)
            client["traffic_up"] = up
            client["traffic_down"] = down
            client["traffic_total"] = total
            client["traffic_human"] = format_bytes(total)
            client["is_subscription_child"] = bool(sub_id)
            client["sub_name"] = sub_names.get(sub_id, "")
            result.append(client)

        result.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return result

    @classmethod
    def get_subscriptions(cls) -> list[dict]:
        state = cls.get_raw_state()
        traffic = cls.get_traffic_state()
        subs = state.get("subscriptions", [])
        users = state.get("users", [])

        result = []
        for s in subs:
            sid = s.get("id")
            sub_up = 0
            sub_down = 0
            for u in users:
                if u.get("subscription_id") == sid:
                    uid = str(u.get("id", ""))
                    t = traffic.get(uid, {})
                    sub_up += t.get("up", 0)
                    sub_down += t.get("down", 0)

            sub = dict(s)
            sub["traffic_up"] = sub_up
            sub["traffic_down"] = sub_down
            sub["traffic_total"] = sub_up + sub_down
            sub["traffic_human"] = format_bytes(sub_up + sub_down)
            sub["url"] = f"https://{cls.get_domain()}/wpp-sub/{s.get('token', '')}"
            sub["active_devices"] = len([d for d in s.get("devices", []) if not d.get("revoked")])
            result.append(sub)

        result.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return result

    @classmethod
    def get_client_by_id(cls, client_id: str) -> dict | None:
        for c in cls.get_clients(include_subscriptions=True):
            if str(c.get("id")) == str(client_id):
                return c
        return None

    @classmethod
    def get_subscription_by_id(cls, sub_id: str) -> dict | None:
        for s in cls.get_subscriptions():
            if str(s.get("id")) == str(sub_id):
                return s
        return None

    @staticmethod
    def get_mtproto_host() -> str:
        try:
            host = MTPROTO_HOST_FILE.read_text(encoding="utf-8").strip()
            if host:
                return host
        except OSError:
            pass
        return DOMAIN

    @staticmethod
    def _load_connection(conn_id: str) -> dict | None:
        if not conn_id or not CONNECTIONS_FILE.is_file():
            return None
        try:
            with open(CONNECTIONS_FILE, encoding="utf-8") as f:
                doc = json.load(f)
            return next((c for c in doc.get("connections", []) if c.get("id") == conn_id), None)
        except Exception:
            return None

    @classmethod
    def _vless_link(cls, client: dict, secret: str, label: str) -> str:
        """Mirror of the panel's proxy_link(): honours CDN routes and per-connection XHTTP settings."""
        domain = cls.get_domain()
        connection = cls._load_connection(str(client.get("connection_id", "")))
        try:
            import wpp_cdn as cdn
            import wpp_connections as store
        except ImportError:
            cdn = store = None

        if cdn is not None:
            route = cdn.vless_route(domain, client.get("cdn"))
            if connection:
                route = store.apply_client_advanced(route, connection.get("advanced", {}))
            xray_root = cls.get_xray_path()
            route_path = cdn.client_endpoint_path(xray_root, route.get("path_variant", "cdn" if route["enabled"] else "direct"))
            if connection:
                xhttp = connection.get("advanced", {}).get("inbound", {}).get("streamSettings", {}).get("xhttpSettings", {})
                route_path = store.client_path(connection, xray_root)
                if xhttp.get("mode") and xhttp["mode"] != "auto":
                    route["mode"] = xhttp["mode"]
                    if route.get("extra") and "mode" in route["extra"]:
                        route["extra"]["mode"] = xhttp["mode"]
                route["extra"] = {**(route.get("extra") or {}), **{k: v for k, v in xhttp.items() if k not in ("path", "mode", "host")}}
            query_values = {
                "encryption": "none", "security": "tls", "sni": route["sni"], "fp": route["fingerprint"],
                "type": "xhttp", "host": route["host"], "path": route_path, "mode": route["mode"],
                "alpn": ",".join(route.get("alpn") or ["h2"]),
            }
            if route.get("extra"):
                query_values["extra"] = json.dumps(route["extra"], ensure_ascii=True, separators=(",", ":"))
            return f"vless://{quote(secret, safe='-')}@{route['address']}:443?{urlencode(query_values)}#{label}"

        # Fallback without panel modules (direct route only)
        query_values = {
            "encryption": "none", "security": "tls", "sni": domain, "fp": "chrome", "type": "xhttp",
            "host": domain, "path": cls.get_xray_path(), "mode": "auto", "alpn": "h2",
        }
        return f"vless://{quote(secret, safe='-')}@{domain}:443?{urlencode(query_values)}#{label}"

    @classmethod
    def generate_proxy_link(cls, client: dict) -> str:
        protocol = client.get("protocol", "vless")
        secret = client.get("secret", "")
        name = client.get("name", "Proxy")
        domain = cls.get_domain()
        port = client.get("backend_port", 443)

        label = quote(name, safe="")

        if protocol == "mtproto":
            client_secret = secret if secret.startswith("dd") else "dd" + secret
            return f"https://t.me/proxy?server={cls.get_mtproto_host()}&port={port}&secret={client_secret}"

        if protocol == "web":
            return f"https://t.me/webproxy?server={domain}&secret={secret}"

        if protocol == "vless":
            return cls._vless_link(client, secret, label)

        if protocol == "hysteria":
            query = urlencode({"sni": domain, "alpn": "h3"})
            connection = cls._load_connection(str(client.get("connection_id", "")))
            conn_port = (connection or {}).get("advanced", {}).get("inbound", {}).get("port")
            h_port = conn_port or port or 8443
            return f"hysteria2://{quote(secret, safe='-')}@{domain}:{h_port}/?{query}#{label}"

        if protocol in ("awg20", "awg31"):
            try:
                import wpp_awg
                import wpp_routing as routing_store
                routing_file = Path("/var/lib/tproxy-panel/routing.json")
                try:
                    route_state = routing_store.load(str(routing_file))
                except Exception:
                    route_state = {"profiles": {}, "awg_profiles": {}}
                routes = routing_store.awg_allowed_ips(route_state, client.get("connection_id", ""))
                return wpp_awg.client_config(client, domain, name, routes)
            except Exception as exc:
                # Never hand out a fake .conf that silently does not work
                raise RuntimeError(f"Не удалось собрать конфиг AmneziaWG: {exc}") from exc

        return f"# Неизвестный протокол: {protocol}"

    @classmethod
    def create_client(cls, name: str, protocol: str, devices: int = 1, port: int = None) -> dict:
        payload = {
            "protocol": protocol,
            "name": name.strip(),
            "devices": int(devices),
        }
        if port and protocol == "mtproto":
            payload["port"] = int(port)
        return run_ctl("add-json", input_json=payload)

    @classmethod
    def create_subscription(cls, name: str, max_devices: int = 0) -> dict:
        payload = {
            "operation": "create",
            "name": name.strip(),
            "max_devices": int(max_devices),
            "failover_enabled": True,
        }
        return run_subscription(payload)

    @classmethod
    def toggle_client(cls, client_id: str, enable: bool) -> dict:
        return run_ctl("set-user", client_id, "1" if enable else "0")

    @classmethod
    def rename_client(cls, client_id: str, new_name: str) -> dict:
        return run_ctl("rename-user", client_id, new_name.strip())

    @classmethod
    def delete_client(cls, client_id: str) -> dict:
        return run_ctl("delete", client_id)

    @classmethod
    def toggle_subscription(cls, sub_id: str, enable: bool) -> dict:
        payload = {
            "operation": "set-enabled",
            "id": sub_id,
            "enabled": enable,
        }
        return run_subscription(payload)

    @classmethod
    def rename_subscription(cls, sub_id: str, new_name: str) -> dict:
        payload = {
            "operation": "update",
            "id": sub_id,
            "name": new_name.strip(),
        }
        return run_subscription(payload)

    @classmethod
    def rotate_subscription(cls, sub_id: str) -> dict:
        payload = {
            "operation": "rotate",
            "id": sub_id,
        }
        return run_subscription(payload)

    @classmethod
    def delete_subscription(cls, sub_id: str) -> dict:
        payload = {
            "operation": "delete",
            "id": sub_id,
        }
        return run_subscription(payload)

    @classmethod
    def revoke_sub_device(cls, sub_id: str, device_id: str) -> dict:
        payload = {
            "operation": "revoke",
            "id": sub_id,
            "device_id": device_id,
        }
        return run_subscription(payload)

    @classmethod
    def get_system_metrics(cls) -> dict:
        metrics = {
            "cpu_percent": 0.0,
            "ram_used_gb": 0.0,
            "ram_total_gb": 0.0,
            "ram_percent": 0.0,
            "disk_used_gb": 0.0,
            "disk_total_gb": 0.0,
            "disk_percent": 0.0,
            "uptime_str": "—",
            "services": {},
        }

        try:
            import psutil
            metrics["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            metrics["ram_used_gb"] = round(mem.used / (1024**3), 2)
            metrics["ram_total_gb"] = round(mem.total / (1024**3), 2)
            metrics["ram_percent"] = mem.percent

            disk = psutil.disk_usage("/")
            metrics["disk_used_gb"] = round(disk.used / (1024**3), 1)
            metrics["disk_total_gb"] = round(disk.total / (1024**3), 1)
            metrics["disk_percent"] = disk.percent

            # Precise uptime calculation
            uptime_sec = int(time.time() - psutil.boot_time())
            days, rem = divmod(uptime_sec, 86400)
            hours, rem_sec = divmod(rem, 3600)
            minutes, _ = divmod(rem_sec, 60)
            metrics["uptime_str"] = f"{days}д {hours}ч {minutes}м" if days else f"{hours}ч {minutes}м"
        except ImportError:
            pass

        units = [
            ("xray", "web-panel-proxy-xray.service"),
            ("caddy", "caddy.service"),
            ("mtproxy", "mtproxy.service"),
            ("panel", "tproxy-panel.service"),
            ("openflux", "web-panel-proxy-openflux.service"),
        ]

        for label, unit in units:
            try:
                res = subprocess.run(
                    ["systemctl", "is-active", "--quiet", unit],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                metrics["services"][label] = (res.returncode == 0)
            except Exception:
                metrics["services"][label] = False

        return metrics

    @classmethod
    def export_backup_zip(cls) -> bytes:
        try:
            import wpp_backup
            version = ""
            v_file = Path("/etc/web-proxy-panel/version")
            if v_file.is_file():
                version = v_file.read_text(encoding="ascii").strip()
            return wpp_backup.export_bytes(version)
        except Exception:
            pass

        import io
        import zipfile
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as arc:
            for p in [Path("/etc/web-proxy-panel"), Path("/var/lib/tproxy-panel")]:
                if p.is_dir():
                    for root, _, files in os.walk(p):
                        for f in files:
                            full = Path(root) / f
                            rel = full.relative_to(p.parent)
                            try:
                                arc.write(full, str(rel))
                            except OSError:
                                pass
        return out.getvalue()
