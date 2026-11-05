"""Handlers for standalone clients management."""
import datetime
import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards import client_detail_kb, clients_list_kb, confirm_delete_kb
from qr import generate_qr_bytes
from service import WPPService, format_bytes

from .common import run, show

router = Router()


class RenameClientState(StatesGroup):
    waiting_for_name = State()


def clients_list_text(count: int) -> str:
    return (
        "👥 <b>Клиенты и подключения</b>\n"
        "──────────────────────────────\n"
        f"Всего подключений: <b>{count}</b>\n"
        "Нажмите на клиента для просмотра настроек и получения ссылки:\n"
    )


@router.callback_query(F.data.startswith("clients:page:"))
async def cb_clients_page(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        page = 0
    clients = await run(WPPService.get_clients)
    await show(callback, clients_list_text(len(clients)), clients_list_kb(clients, page=page))


async def render_client(callback: CallbackQuery, cid: str) -> bool:
    client = await run(WPPService.get_client_by_id, cid)
    if not client:
        return False

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
    proto = html.escape(str(client.get("protocol", "vless")).upper())
    name = html.escape(str(client.get("name", "Без имени")))

    text = (
        f"👤 <b>Клиент:</b> <code>{name}</code>\n"
        "──────────────────────────────\n"
        f"🔑 <b>Протокол:</b> <code>{proto}</code>\n"
        f"⚡️ <b>Статус:</b> {status_str}\n"
        f"📊 <b>Трафик:</b> {total} (↑ {up} / ↓ {down})\n"
        f"🆔 <b>ID:</b> <code>{html.escape(str(client.get('id')))}</code>\n"
        f"📅 <b>Создан:</b> {created_date}\n"
        "──────────────────────────────"
    )
    await show(callback, text, client_detail_kb(cid, is_enabled))
    return True


@router.callback_query(F.data.startswith("client:view:"))
async def cb_client_view(callback: CallbackQuery, state: FSMContext):
    # "Отмена" from rename comes here: without clearing, the next text message would rename the client
    await state.clear()
    cid = callback.data.split(":")[-1]
    if await render_client(callback, cid):
        await callback.answer()
    else:
        await callback.answer("Клиент не найден!", show_alert=True)


@router.callback_query(F.data.startswith("client:toggle:"))
async def cb_client_toggle(callback: CallbackQuery):
    _, _, cid, action = callback.data.split(":")
    enable = (action == "enable")
    try:
        await run(WPPService.toggle_client, cid, enable)
    except Exception as exc:
        await callback.answer(f"Ошибка: {exc}"[:200], show_alert=True)
        return

    await callback.answer("Статус клиента изменен ✅")
    await render_client(callback, cid)


@router.callback_query(F.data.startswith("client:link:"))
async def cb_client_link(callback: CallbackQuery):
    await callback.answer("Получаем ссылку...")
    cid = callback.data.split(":")[-1]
    client = await run(WPPService.get_client_by_id, cid)
    if not client:
        await callback.message.answer("Клиент не найден.")
        return

    try:
        link = await run(WPPService.generate_proxy_link, client)
        proto = str(client.get("protocol", "vless")).lower()
        name = html.escape(str(client.get("name", "Без имени")))

        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="📱 Показать QR-код", callback_data=f"client:qr:{cid}"))
        builder.row(InlineKeyboardButton(text="🔙 Назад к клиенту", callback_data=f"client:view:{cid}"))

        if proto in ("awg20", "awg31"):
            doc = BufferedInputFile(link.encode("utf-8"), filename=f"wpp-{cid}.conf")
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
    await callback.answer("Генерируем QR-код...")
    cid = callback.data.split(":")[-1]
    client = await run(WPPService.get_client_by_id, cid)
    if not client:
        await callback.message.answer("Клиент не найден.")
        return

    try:
        link = await run(WPPService.generate_proxy_link, client)
        proto = html.escape(str(client.get("protocol", "vless")).upper())
        name = html.escape(str(client.get("name", "Без имени")))

        qr_io = await run(generate_qr_bytes, link)
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
    cid = callback.data.split(":")[-1]
    client = await run(WPPService.get_client_by_id, cid)
    if not client:
        await callback.answer("Клиент не найден", show_alert=True)
        return

    name = html.escape(str(client.get("name", "Без имени")))
    text = (
        f"⚠️ <b>Вы действительно хотите удалить клиента «{name}»?</b>\n\n"
        "Ключ доступа будет аннулирован, а соединение разорвано."
    )
    await show(callback, text, confirm_delete_kb("client", cid))
    await callback.answer()


@router.callback_query(F.data.startswith("del:exec:client:"))
async def cb_client_del_exec(callback: CallbackQuery):
    cid = callback.data.split(":")[-1]
    try:
        await run(WPPService.delete_client, cid)
    except Exception as exc:
        await callback.answer(f"Ошибка удаления: {exc}"[:200], show_alert=True)
        return

    await callback.answer("Клиент успешно удален 🗑", show_alert=True)
    clients = await run(WPPService.get_clients)
    await show(callback, clients_list_text(len(clients)), clients_list_kb(clients, page=0))


@router.callback_query(F.data.startswith("client:rename:"))
async def cb_client_rename(callback: CallbackQuery, state: FSMContext):
    cid = callback.data.split(":")[-1]
    await state.set_state(RenameClientState.waiting_for_name)
    await state.update_data(client_id=cid)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data=f"client:view:{cid}"))

    await show(
        callback,
        "✏️ <b>Введите новое имя для клиента:</b>\n<i>(от 1 до 80 символов)</i>",
        builder.as_markup(),
    )
    await callback.answer()


@router.message(RenameClientState.waiting_for_name, F.text)
async def msg_client_rename(message: Message, state: FSMContext):
    data = await state.get_data()
    cid = data.get("client_id")
    new_name = message.text.strip()

    if not new_name or len(new_name) > 80:
        await message.answer("⚠️ Имя должно содержать от 1 до 80 символов. Попробуйте еще раз:")
        return

    await state.clear()
    try:
        await run(WPPService.rename_client, cid, new_name)
        await message.answer(f"✅ Клиент успешно переименован в <b>{html.escape(new_name)}</b>!", parse_mode="HTML")
    except Exception as exc:
        await message.answer(f"❌ Не удалось переименовать: {html.escape(str(exc))}")

    client = await run(WPPService.get_client_by_id, cid)
    if client:
        is_enabled = bool(client.get("enabled", True))
        await message.answer(
            f"👤 <b>Клиент:</b> <code>{html.escape(str(client.get('name', '')))}</code>\nID: <code>{html.escape(str(cid))}</code>",
            reply_markup=client_detail_kb(cid, is_enabled),
            parse_mode="HTML",
        )


@router.message(RenameClientState.waiting_for_name)
async def msg_client_rename_not_text(message: Message):
    await message.answer("⚠️ Отправьте новое имя текстом.")
