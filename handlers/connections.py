"""Handlers for server connections / routes live monitoring."""
from aiogram import F, Router
from aiogram.types import CallbackQuery

from config import ADMIN_IDS
from keyboards import connection_detail_kb, connections_list_kb
from service import WPPService, format_bytes

router = Router()


def is_admin(user_id: int) -> bool:
    return not ADMIN_IDS or user_id in ADMIN_IDS


@router.callback_query(F.data == "conns:list")
async def cb_conns_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    conns = WPPService.get_connections()
    active_now = [c for c in conns if c.get("is_active_now")]

    if active_now:
        active_now.sort(key=lambda x: x.get("speed_bps", 0.0), reverse=True)
        active_lines = []
        for c in active_now:
            speed = f" — ⚡️ <code>{c['speed_str']}</code>" if c.get("speed_str") and c["speed_str"] != "0 Б/с" else ""
            active_lines.append(f"  👉 🔥 <b>{c['name']}</b> ({c['route_label']}){speed}")
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
    kb = connections_list_kb(conns)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("conn:view:"))
async def cb_conn_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    cid = callback.data.split(":")[-1]
    conn = WPPService.get_connection_by_id(cid)
    if not conn:
        await callback.answer("Подключение не найдено!", show_alert=True)
        return

    enabled = conn.get("enabled", True)
    status_str = "🟢 Включено (Активно)" if enabled else "🔴 Выключено (Отключено)"
    is_active = conn.get("is_active_now", False)

    if is_active:
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
        clients_str = ", ".join(f"<code>{name}</code>" for name in clients_list)
    else:
        clients_str = "<i>Пока не привязаны</i>"

    text = (
        f"🌐 <b>Подключение:</b> <code>{conn.get('name')}</code>\n"
        "──────────────────────────────\n"
        f"⚡️ <b>Live-статус:</b> {live_status}\n"
        f"🔘 <b>Состояние:</b> {status_str}\n\n"
        f"🛣 <b>Маршрут:</b> <code>{conn.get('route_label')}</code>\n"
        f"🔑 <b>Протокол:</b> <code>{conn.get('protocol').upper()}</code> ({conn.get('mode')})\n"
        f"🔌 <b>Порт:</b> <code>{conn.get('port')}</code>\n"
        f"🌐 <b>Хост / SNI:</b> <code>{conn.get('public_host')}</code>\n\n"
        f"📊 <b>Трафик по этому маршруту:</b> {total}\n"
        f"  • Исходящий (↑): <code>{up}</code>\n"
        f"  • Входящий (↓): <code>{down}</code>\n\n"
        f"👥 <b>Используют этот транспорт ({conn.get('clients_count')}):</b>\n"
        f"  {clients_str}\n"
        "──────────────────────────────"
    )
    kb = connection_detail_kb(cid, enabled)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("conn:toggle:"))
async def cb_conn_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    _, _, cid, action = callback.data.split(":")
    enable = (action == "enable")

    try:
        WPPService.toggle_connection(cid, enable)
        await callback.answer("Состояние маршрута переключено ✅")
    except Exception as exc:
        await callback.answer(f"Ошибка: {exc}", show_alert=True)
        return

    # Refresh view
    callback.data = f"conn:view:{cid}"
    await cb_conn_view(callback)
