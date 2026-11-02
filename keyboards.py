"""Inline keyboards for WPP Telegram Bot."""
import math
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb(clients_count: int, subs_count: int, conns_count: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"👥 Клиенты ({clients_count})", callback_data="clients:page:0"),
        InlineKeyboardButton(text=f"📦 Подписки ({subs_count})", callback_data="subs:page:0"),
    )
    builder.row(
        InlineKeyboardButton(text=f"🌐 Маршруты / CDN / XHTTP ({conns_count})", callback_data="conns:list"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ Создать", callback_data="create:start"),
        InlineKeyboardButton(text="⚡️ Статус VPS", callback_data="menu:server_status"),
    )
    builder.row(
        InlineKeyboardButton(text="💾 Скачать бэкап", callback_data="menu:backup"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:refresh"),
    )
    return builder.as_markup()


def connections_list_kb(connections: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for c in connections:
        cid = c.get("id", "")
        name = c.get("name", "Подключение")
        enabled = c.get("enabled", True)
        is_active = c.get("is_active_now", False)
        traffic = c.get("traffic_human", "0 Б")

        # Icons
        if is_active:
            status_prefix = "🔥 🟢"
        elif enabled:
            status_prefix = "🟢"
        else:
            status_prefix = "🔴"

        btn_text = f"{status_prefix} {name} · {traffic}"
        builder.row(InlineKeyboardButton(text=btn_text, callback_data=f"conn:view:{cid}"))

    builder.row(
        InlineKeyboardButton(text="🔄 Обновить live-трафик", callback_data="conns:list"),
        InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu:main"),
    )
    return builder.as_markup()


def connection_detail_kb(conn_id: str, is_enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    toggle_text = "🔴 Отключить маршрут" if is_enabled else "🟢 Включить маршрут"
    toggle_action = "disable" if is_enabled else "enable"

    builder.row(
        InlineKeyboardButton(text=toggle_text, callback_data=f"conn:toggle:{conn_id}:{toggle_action}"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Проверить live-трафик", callback_data=f"conn:view:{conn_id}"),
        InlineKeyboardButton(text="🔙 К списку маршрутов", callback_data="conns:list"),
    )
    return builder.as_markup()


def clients_list_kb(clients: list[dict], page: int = 0, per_page: int = 6) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    total_pages = max(1, math.ceil(len(clients) / per_page))
    page = max(0, min(page, total_pages - 1))

    start = page * per_page
    end = start + per_page
    current_items = clients[start:end]

    for c in current_items:
        cid = c.get("id", "")
        name = c.get("name", "Клиент")
        proto = str(c.get("protocol", "vless")).upper()
        status_icon = "🟢" if c.get("enabled", True) else "🔴"
        traffic = c.get("traffic_human", "0 Б")

        sub_tag = " [📦]" if c.get("is_subscription_child") else ""
        btn_text = f"{status_icon} {name}{sub_tag} ({proto}) · {traffic}"
        builder.row(InlineKeyboardButton(text=btn_text, callback_data=f"client:view:{cid}"))

    # Pagination buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"clients:page:{page - 1}"))
    if total_pages > 1:
        nav_buttons.append(InlineKeyboardButton(text=f"Стр. {page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"clients:page:{page + 1}"))

    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(text="➕ Новый клиент", callback_data="create:client_direct"),
        InlineKeyboardButton(text="🔙 В меню", callback_data="menu:main"),
    )
    return builder.as_markup()


def client_detail_kb(client_id: str, is_enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    toggle_text = "🔴 Выключить" if is_enabled else "🟢 Включить"
    toggle_action = "disable" if is_enabled else "enable"

    builder.row(
        InlineKeyboardButton(text=toggle_text, callback_data=f"client:toggle:{client_id}:{toggle_action}"),
    )
    builder.row(
        InlineKeyboardButton(text="📱 QR-код", callback_data=f"client:qr:{client_id}"),
        InlineKeyboardButton(text="📋 Ссылка", callback_data=f"client:link:{client_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"client:rename:{client_id}"),
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"client:del_confirm:{client_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 К списку клиентов", callback_data="clients:page:0"),
    )
    return builder.as_markup()


def subscriptions_list_kb(subs: list[dict], page: int = 0, per_page: int = 6) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    total_pages = max(1, math.ceil(len(subs) / per_page))
    page = max(0, min(page, total_pages - 1))

    start = page * per_page
    end = start + per_page
    current_items = subs[start:end]

    for s in current_items:
        sid = s.get("id", "")
        name = s.get("name", "Подписка")
        status_icon = "🟢" if s.get("enabled", True) else "🔴"
        devices = s.get("active_devices", 0)
        max_d = s.get("max_devices", 0)
        limit_text = f"{devices}/{max_d}" if max_d else f"{devices} устр."
        btn_text = f"{status_icon} {name} ({limit_text})"
        builder.row(InlineKeyboardButton(text=btn_text, callback_data=f"sub:view:{sid}"))

    # Pagination buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"subs:page:{page - 1}"))
    if total_pages > 1:
        nav_buttons.append(InlineKeyboardButton(text=f"Стр. {page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"subs:page:{page + 1}"))

    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(text="➕ Новая подписка", callback_data="create:subscription"),
        InlineKeyboardButton(text="🔙 В меню", callback_data="menu:main"),
    )
    return builder.as_markup()


def subscription_detail_kb(sub_id: str, is_enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    toggle_text = "🔴 Выключить" if is_enabled else "🟢 Включить"
    toggle_action = "disable" if is_enabled else "enable"

    builder.row(
        InlineKeyboardButton(text=toggle_text, callback_data=f"sub:toggle:{sub_id}:{toggle_action}"),
    )
    builder.row(
        InlineKeyboardButton(text="📱 QR-код", callback_data=f"sub:qr:{sub_id}"),
        InlineKeyboardButton(text="🔗 Ссылка", callback_data=f"sub:link:{sub_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="📱 Устройства", callback_data=f"sub:devices:{sub_id}"),
        InlineKeyboardButton(text="🔄 Сменить ключ", callback_data=f"sub:rotate_confirm:{sub_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"sub:rename:{sub_id}"),
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"sub:del_confirm:{sub_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 К списку подписок", callback_data="subs:page:0"),
    )
    return builder.as_markup()


def create_type_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📦 Мульти-подписка (VLESS + Hysteria 2)", callback_data="create:type:subscription"))
    builder.row(InlineKeyboardButton(text="⚡️ Отдельный VLESS (XHTTP)", callback_data="create:type:vless"))
    builder.row(InlineKeyboardButton(text="🚀 Отдельная Hysteria 2 (UDP)", callback_data="create:type:hysteria"))
    builder.row(InlineKeyboardButton(text="✈️ Отдельный MTProto (Telegram)", callback_data="create:type:mtproto"))
    builder.row(InlineKeyboardButton(text="🛡 AmneziaWG (WireGuard)", callback_data="create:type:awg20"))
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="menu:main"))
    return builder.as_markup()


def confirm_delete_kb(target_type: str, target_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Да, удалить", callback_data=f"del:exec:{target_type}:{target_id}"),
        InlineKeyboardButton(text="🔙 Отмена", callback_data=f"{target_type}:view:{target_id}"),
    )
    return builder.as_markup()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu:main"))
    return builder.as_markup()
