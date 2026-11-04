"""Handlers for standalone clients management."""
import datetime
import html
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from keyboards import back_to_menu_kb, client_detail_kb, clients_list_kb, confirm_delete_kb
from qr import generate_qr_bytes
from service import WPPService, format_bytes

router = Router()


class RenameClientState(StatesGroup):
    waiting_for_name = State()


def is_admin(user_id: int) -> bool:
    return not ADMIN_IDS or user_id in ADMIN_IDS


@router.callback_query(F.data.startswith("clients:page:"))
async def cb_clients_page(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    page = int(callback.data.split(":")[-1])
    clients = WPPService.get_clients()
    kb = clients_list_kb(clients, page=page)
    text = (
        "👥 <b>Клиенты и подключения</b>\n"
        "──────────────────────────────\n"
        f"Всего подключений: <b>{len(clients)}</b>\n"
        "Нажмите на клиента для просмотра настроек и получения ссылки:\n"
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("client:view:"))
async def cb_client_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    cid = callback.data.split(":")[-1]
    client = WPPService.get_client_by_id(cid)
    if not client:
        await callback.answer("Клиент не найден!", show_alert=True)
        return

    is_enabled = bool(client.get("enabled", True))
    status_str = "🟢 Активен (Включен)" if is_enabled else "🔴 Отключен"
    created_ts = client.get("created_at", 0)
    created_date = (
        datetime.datetime.fromtimestamp(created_ts).strftime("%d.%m.%Y %H:%M")
        if created_ts else "—"
    )
    up = format_bytes(client.get("traffic_up", 0))
    down = format_bytes(client.get("traffic_down", 0))
    total = client.get("traffic_human", "0 Б")
    proto = str(client.get("protocol", "vless")).upper()
    name = html.escape(str(client.get("name", "Без имени")))

    text = (
        f"👤 <b>Клиент:</b> <code>{name}</code>\n"
        "──────────────────────────────\n"
        f"🔑 <b>Протокол:</b> <code>{proto}</code>\n"
        f"⚡️ <b>Статус:</b> {status_str}\n"
        f"📊 <b>Трафик:</b> {total} (↑ {up} / ↓ {down})\n"
        f"🆔 <b>ID:</b> <code>{client.get('id')}</code>\n"
        f"📅 <b>Создан:</b> {created_date}\n"
        "──────────────────────────────"
    )
    kb = client_detail_kb(cid, is_enabled)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("client:toggle:"))
async def cb_client_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    _, _, cid, action = callback.data.split(":")
    enable = (action == "enable")
    try:
        WPPService.toggle_client(cid, enable)
        await callback.answer("Статус клиента изменен ✅")
    except Exception as exc:
        await callback.answer(f"Ошибка: {exc}", show_alert=True)
        return

    callback.data = f"client:view:{cid}"
    await cb_client_view(callback)


@router.callback_query(F.data.startswith("client:link:"))
async def cb_client_link(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    await callback.answer("Получаем ссылку...")
    cid = callback.data.split(":")[-1]
    client = WPPService.get_client_by_id(cid)
    if not client:
        await callback.message.answer("Клиент не найден.")
        return

    try:
        link = WPPService.generate_proxy_link(client)
        proto = str(client.get("protocol", "vless")).lower()
        name = html.escape(str(client.get("name", "Без имени")))

        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="📱 Показать QR-код", callback_data=f"client:qr:{cid}"))
        builder.row(InlineKeyboardButton(text="🔙 Назад к клиенту", callback_data=f"client:view:{cid}"))

        if proto in ("awg20", "awg31"):
            doc = BufferedInputFile(link.encode("utf-8"), filename=f"wpp-{client.get('name')}.conf")
            await callback.message.answer_document(
                document=doc,
                caption=f"🛡 Конфигурационный файл для <b>{name}</b> (AmneziaWG)",
                reply_markup=builder.as_markup(),
                parse_mode="HTML",
            )
        else:
            escaped_link = html.escape(link)
            text = (
                f"🔗 <b>Ссылка подключения для {name}:</b>\n\n"
                f"<code>{escaped_link}</code>\n\n"
                "<i>💡 Нажмите на ссылку, чтобы скопировать её в буфер обмена.</i>"
            )
            await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception as exc:
        await callback.message.answer(f"❌ Ошибка генерации ссылки: {html.escape(str(exc))}")


@router.callback_query(F.data.startswith("client:qr:"))
async def cb_client_qr(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    await callback.answer("Генерируем QR-код...")
    cid = callback.data.split(":")[-1]
    client = WPPService.get_client_by_id(cid)
    if not client:
        await callback.message.answer("Клиент не найден.")
        return

    try:
        link = WPPService.generate_proxy_link(client)
        proto = str(client.get("protocol", "vless")).upper()
        name = html.escape(str(client.get("name", "Без имени")))

        qr_io = generate_qr_bytes(link)
        photo = BufferedInputFile(qr_io.getvalue(), filename="qr.png")

        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Назад к клиенту", callback_data=f"client:view:{cid}"))

        caption = (
            f"📱 <b>QR-код для подключения: {name}</b>\n"
            f"Протокол: <code>{proto}</code>\n\n"
            "<i>Отсканируйте камерой телефона или клиентом v2rayNG / Streisand / Happ.</i>"
        )
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    except Exception as exc:
        await callback.message.answer(f"❌ Ошибка формирования QR-кода: {html.escape(str(exc))}")


@router.callback_query(F.data.startswith("client:del_confirm:"))
async def cb_client_del_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    cid = callback.data.split(":")[-1]
    client = WPPService.get_client_by_id(cid)
    if not client:
        await callback.answer("Клиент не найден", show_alert=True)
        return

    name = html.escape(str(client.get("name", "Без имени")))
    text = (
        f"⚠️ <b>Вы действительно хотите удалить клиента «{name}»?</b>\n\n"
        "Ключ доступа будет аннулирован, а соединение разорвано."
    )
    kb = confirm_delete_kb("client", cid)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("del:exec:client:"))
async def cb_client_del_exec(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    cid = callback.data.split(":")[-1]
    try:
        WPPService.delete_client(cid)
        await callback.answer("Клиент успешно удален 🗑", show_alert=True)
    except Exception as exc:
        await callback.answer(f"Ошибка удаления: {exc}", show_alert=True)
        return

    clients = WPPService.get_clients()
    kb = clients_list_kb(clients, page=0)
    text = (
        "👥 <b>Клиенты и подключения</b>\n"
        "──────────────────────────────\n"
        f"Всего подключений: <b>{len(clients)}</b>\n"
    )
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("client:rename:"))
async def cb_client_rename(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    cid = callback.data.split(":")[-1]
    await state.update_data(client_id=cid)
    await state.set_state(RenameClientState.waiting_for_name)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data=f"client:view:{cid}"))

    await callback.message.edit_text(
        "✏️ <b>Введите новое имя для клиента:</b>\n<i>(от 1 до 80 символов)</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(RenameClientState.waiting_for_name)
async def msg_client_rename(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    cid = data.get("client_id")
    new_name = message.text.strip()

    if not new_name or len(new_name) > 80:
        await message.answer("⚠️ Имя должно содержать от 1 до 80 символов. Попробуйте еще раз:")
        return

    await state.clear()
    try:
        WPPService.rename_client(cid, new_name)
        await message.answer(f"✅ Клиент успешно переименован в <b>{html.escape(new_name)}</b>!", parse_mode="HTML")
    except Exception as exc:
        await message.answer(f"❌ Не удалось переименовать: {html.escape(str(exc))}")

    client = WPPService.get_client_by_id(cid)
    if client:
        is_enabled = bool(client.get("enabled", True))
        kb = client_detail_kb(cid, is_enabled)
        await message.answer(
            f"👤 <b>Клиент:</b> <code>{html.escape(client.get('name'))}</code>\nID: <code>{cid}</code>",
            reply_markup=kb,
            parse_mode="HTML",
        )
