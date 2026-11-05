"""Handlers for server connections / routes live monitoring."""
import html

from aiogram import F, Router
from aiogram.types import CallbackQuery

from keyboards import connection_detail_kb, connections_list_kb
from service import WPPService, format_bytes

from .common import run, show

router = Router()


@router.callback_query(F.data == "conns:list")
async def cb_conns_list(callback: CallbackQuery):
    await callback.answer()
    conns = await run(WPPService.get_connections)
    active_now = [c for c in conns if c.get("is_active_now")]

    if active_now:
        active_now.sort(key=lambda x: x.get("speed_bps", 0.0), reverse=True)
        active_lines = []
        for c in active_now:
            speed = f" — ⚡️ <code>{c['speed_str']}</code>" if c.get("speed_str") and c["speed_str"] != "0 Б/с" else ""
            c_name = html.escape(str(c.get("name", "")))
            c_route = html.escape(str(c.get("route_label", "")))
            active_lines.append(f"  👉 🔥 <b>{c_name}</b> ({c_route}){speed}")
        live_banner = "⚡️ <b>СЕЙЧАС ТРАФИК ИДЕТ ЧЕРЕЗ:</b>\n" + "\n".join(active_lines) + "\n"
    else:
        live_banner = "💤 <b>Текущая активность:</b> В данный момент активного потока нет (режим ожидания)\n"

    text = (
        "🌐 <b>Серверные подключения и маршрутизация</b>\n"
        "──────────────────────────────\n"
        f"{live_banner}\n"
        "<i>Ниже приведены серверные транспорты (VLESS, Hysteria 2, CDN, AmneziaWG). "
        "Значок 🔥 показывает маршрут, по которому устройства качают трафик прямо сейчас:</i>"
    )
    await show(callback, text, connections_list_kb(conns))


async def render_connection(callback: CallbackQuery, cid: str) -> bool:
    conn = await run(WPPService.get_connection_by_id, cid)
    if not conn:
        return False

    enabled = conn.get("enabled", True)
    status_str = "🟢 Включено (Активно)" if enabled else "🔴 Выключено (Отключено)"

    if conn.get("is_active_now", False):
        speed_str = conn.get("speed_str", "")
        speed_part = f" (скорость: ⚡️ <b>{speed_str}</b>)" if speed_str and speed_str != "0 Б/с" else ""
        live_status = f"🔥 <b>АКТИВНО ПРЯМО СЕЙЧАС!</b>{speed_part}"
    else:
        live_status = f"💤 В резерве ({conn.get('last_seen_str')})"

    up = format_bytes(conn.get("traffic_up", 0))
    down = format_bytes(conn.get("traffic_down", 0))
    total = conn.get("traffic_human", "0 Б")

    clients_list = conn.get("clients_list", [])
    if clients_list:
        clients_str = ", ".join(f"<code>{html.escape(str(name))}</code>" for name in clients_list)
    else:
        clients_str = "<i>Пока не привязаны</i>"

    conn_name = html.escape(str(conn.get('name', '')))
    route_label = html.escape(str(conn.get('route_label', '')))
    proto = html.escape(str(conn.get('protocol', '')).upper())
    mode = html.escape(str(conn.get('mode', '')))
    host = html.escape(str(conn.get('public_host', '')))

    text = (
        f"🌐 <b>Подключение:</b> <code>{conn_name}</code>\n"
        "──────────────────────────────\n"
        f"⚡️ <b>Live-статус:</b> {live_status}\n"
        f"🔘 <b>Состояние:</b> {status_str}\n\n"
        f"🛣 <b>Маршрут:</b> <code>{route_label}</code>\n"
        f"🔑 <b>Протокол:</b> <code>{proto}</code> ({mode})\n"
        f"🔌 <b>Порт:</b> <code>{html.escape(str(conn.get('port')))}</code>\n"
        f"🌐 <b>Хост / SNI:</b> <code>{host}</code>\n\n"
        f"📊 <b>Трафик по этому маршруту:</b> {total}\n"
        f"  • Исходящий (↑): <code>{up}</code>\n"
        f"  • Входящий (↓): <code>{down}</code>\n\n"
        f"👥 <b>Используют этот транспорт ({conn.get('clients_count')}):</b>\n"
        f"  {clients_str}\n"
        "──────────────────────────────"
    )
    await show(callback, text, connection_detail_kb(cid, enabled))
    return True


@router.callback_query(F.data.startswith("conn:view:"))
async def cb_conn_view(callback: CallbackQuery):
    cid = callback.data.split(":", 2)[-1]
    if await render_connection(callback, cid):
        await callback.answer()
    else:
        await callback.answer("Подключение не найдено!", show_alert=True)


@router.callback_query(F.data.startswith("conn:toggle:"))
async def cb_conn_toggle(callback: CallbackQuery):
    _, _, rest = callback.data.split(":", 2)
    cid, _, action = rest.rpartition(":")
    enable = (action == "enable")

    try:
        await run(WPPService.toggle_connection, cid, enable)
    except Exception as exc:
        await callback.answer(f"Ошибка: {exc}"[:200], show_alert=True)
        return

    await callback.answer("Состояние маршрута переключено ✅")
    await render_connection(callback, cid)
