"""Start command and main dashboard handlers."""
import html
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS
from keyboards import back_to_menu_kb, main_menu_kb
from service import WPPService, format_bytes

router = Router()


def is_admin(user_id: int) -> bool:
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


def format_dashboard_text() -> str:
    domain = WPPService.get_domain()
    clients = WPPService.get_clients()
    subs = WPPService.get_subscriptions()
    conns = WPPService.get_connections()
    metrics = WPPService.get_system_metrics()

    # Active counts
    active_clients = len([c for c in clients if c.get("enabled", True)])
    active_subs = len([s for s in subs if s.get("enabled", True)])
    enabled_conns = len([c for c in conns if c.get("enabled", True)])

    # Active route right now (3-5 sec window)
    active_now = [c for c in conns if c.get("is_active_now")]
    if active_now:
        # Sort so highest active speed is first
        active_now.sort(key=lambda x: x.get("speed_bps", 0.0), reverse=True)
        routes_lines = []
        for c in active_now:
            speed_str = f" · ⚡️ <code>{c['speed_str']}</code>" if c.get("speed_str") and c['speed_str'] != "0 Б/с" else ""
            c_name = html.escape(str(c.get("name", "")))
            c_route = html.escape(str(c.get("route_label", "")))
            routes_lines.append(f"  👉 🔥 <b>{c_name}</b> ({c_route}){speed_str}")
        live_route_banner = "⚡️ <b>Трафик идет прямо сейчас через:</b>\n" + "\n".join(routes_lines) + "\n\n"
    else:
        live_route_banner = "⚡️ <b>Активный маршрут:</b> 💤 <i>Ожидание (нет активной передачи)</i>\n\n"

    # Combined traffic
    total_up = sum(c.get("traffic_up", 0) for c in clients)
    total_down = sum(c.get("traffic_down", 0) for c in clients)
    total_traffic = total_up + total_down

    # Services status
    srv = metrics["services"]
    s_xray = "🟢" if srv.get("xray") else "🔴"
    s_caddy = "🟢" if srv.get("caddy") else "🔴"
    s_mt = "🟢" if srv.get("mtproxy") else "⚪️"
    s_panel = "🟢" if srv.get("panel") else "🔴"

    text = (
        "🛡 <b>WPP Control Panel | Web-Panel-Proxy</b>\n"
        "──────────────────────────────\n"
        f"🌐 <b>Сервер:</b> <code>{domain}</code>\n"
        f"⏱ <b>Аптайм VPS:</b> {metrics['uptime_str']}\n\n"
        f"{live_route_banner}"
        f"📊 <b>Нагрузка сервера:</b>\n"
        f"  • CPU: <code>{metrics['cpu_percent']}%</code>\n"
        f"  • RAM: <code>{metrics['ram_used_gb']} / {metrics['ram_total_gb']} ГБ</code> ({metrics['ram_percent']}%)\n"
        f"  • Диск: <code>{metrics['disk_used_gb']} / {metrics['disk_total_gb']} ГБ</code> ({metrics['disk_percent']}%)\n\n"
        f"⚙️ <b>Службы:</b> {s_xray} Xray  {s_caddy} Caddy  {s_mt} MTProxy  {s_panel} Панель\n\n"
        f"👥 <b>Клиенты:</b> <code>{active_clients}</code> активных (всего {len(clients)})\n"
        f"📦 <b>Подписки:</b> <code>{active_subs}</code> активных (всего {len(subs)})\n"
        f"🌐 <b>Маршруты:</b> <code>{enabled_conns}</code> включено (всего {len(conns)})\n"
        f"📈 <b>Трафик сервера:</b> {format_bytes(total_traffic)} (↑ {format_bytes(total_up)} / ↓ {format_bytes(total_down)})\n"
        "──────────────────────────────\n"
        "<i>Выберите раздел для управления:</i>"
    )
    return text


@router.message(CommandStart())
async def cmd_start(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer(
            f"⛔️ <b>Доступ запрещен.</b>\n\n"
            f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n"
            f"Добавьте его в <code>ADMIN_IDS</code> в файле <code>.env</code> для доступа к боту.",
            parse_mode="HTML",
        )
        return

    clients = WPPService.get_clients()
    subs = WPPService.get_subscriptions()
    conns = WPPService.get_connections()
    kb = main_menu_kb(len(clients), len(subs), len(conns))
    text = format_dashboard_text()
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "menu:main")
async def cb_menu_main(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    clients = WPPService.get_clients()
    subs = WPPService.get_subscriptions()
    conns = WPPService.get_connections()
    kb = main_menu_kb(len(clients), len(subs), len(conns))
    text = format_dashboard_text()
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "menu:refresh")
async def cb_menu_refresh(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    clients = WPPService.get_clients()
    subs = WPPService.get_subscriptions()
    conns = WPPService.get_connections()
    kb = main_menu_kb(len(clients), len(subs), len(conns))
    text = format_dashboard_text()
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer("Данные и трафик обновлены 🔄")


@router.callback_query(F.data == "menu:server_status")
async def cb_server_status(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    m = WPPService.get_system_metrics()
    srv = m["services"]

    text = (
        "⚡️ <b>Детальный статус сервера</b>\n"
        "──────────────────────────────\n"
        f"🖥 <b>Процессор (CPU):</b> {m['cpu_percent']}%\n"
        f"🧠 <b>Память (RAM):</b> {m['ram_used_gb']} ГБ / {m['ram_total_gb']} ГБ ({m['ram_percent']}%)\n"
        f"💾 <b>Диск:</b> {m['disk_used_gb']} ГБ / {m['disk_total_gb']} ГБ ({m['disk_percent']}%)\n"
        f"⏱ <b>Время работы:</b> {m['uptime_str']}\n\n"
        "<b>Системные службы:</b>\n"
        f"  • Xray Core: {'🟢 Работает' if srv.get('xray') else '🔴 Остановлен'}\n"
        f"  • Caddy Server: {'🟢 Работает' if srv.get('caddy') else '🔴 Остановлен'}\n"
        f"  • MTProxy: {'🟢 Работает' if srv.get('mtproxy') else '⚪️ Не настроен'}\n"
        f"  • WPP Web Panel: {'🟢 Работает' if srv.get('panel') else '🔴 Остановлен'}\n"
        f"  • OpenFlux: {'🟢 Работает' if srv.get('openflux') else '⚪️ Не активен'}\n"
        "──────────────────────────────"
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu_kb(), parse_mode="HTML")
    await callback.answer()
