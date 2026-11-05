"""Handlers for subscription management."""
import datetime
import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards import confirm_delete_kb, subscription_detail_kb, subscriptions_list_kb
from qr import generate_qr_bytes
from service import WPPService, format_bytes

from .common import run, show

router = Router()


class RenameSubState(StatesGroup):
    waiting_for_name = State()


SUBS_LIST_TEXT = (
    "📦 <b>Мульти-протокольные подписки</b>\n"
    "──────────────────────────────\n"
    "Всего подписок: <b>{count}</b>\n\n"
    "<i>Подписка объединяет протоколы (VLESS + Hysteria 2) в одну ссылку "
    "для Happ, Streisand, v2rayNG, sing-box и Nekoray.</i>\n\n"
    "Выберите подписку для управления:"
)


@router.callback_query(F.data.startswith("subs:page:"))
async def cb_subs_page(callback: CallbackQuery, state: FSMContext):
    # Also the "Отмена" target of the subscription creation wizard
    await state.clear()
    await callback.answer()
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        page = 0
    subs = await run(WPPService.get_subscriptions)
    await show(callback, SUBS_LIST_TEXT.format(count=len(subs)), subscriptions_list_kb(subs, page=page))


async def render_subscription(callback: CallbackQuery, sid: str) -> bool:
    sub = await run(WPPService.get_subscription_by_id, sid)
    if not sub:
        return False

    is_enabled = bool(sub.get("enabled", True))
    status_str = "🟢 Активна (Включена)" if is_enabled else "🔴 Отключена"
    created_ts = sub.get("created_at", 0)
    created_date = (
        datetime.datetime.fromtimestamp(created_ts).strftime("%d.%m.%Y %H:%M")
        if created_ts else "—"
    )

    max_d = sub.get("max_devices", 0)
    devices_info = f"{sub.get('active_devices', 0)} / {max_d}" if max_d else f"{sub.get('active_devices', 0)} (без лимита)"
    total_traffic = sub.get("traffic_human", "0 Б")
    up = format_bytes(sub.get("traffic_up", 0))
    down = format_bytes(sub.get("traffic_down", 0))
    name = html.escape(str(sub.get("name", "Без имени")))
    sub_url = html.escape(str(sub.get("url", "")))

    text = (
        f"📦 <b>Подписка:</b> <code>{name}</code>\n"
        "──────────────────────────────\n"
        f"⚡️ <b>Статус:</b> {status_str}\n"
        f"📱 <b>Устройств подключено:</b> <code>{devices_info}</code>\n"
        f"📊 <b>Суммарный трафик:</b> {total_traffic} (↑ {up} / ↓ {down})\n"
        f"🆔 <b>ID:</b> <code>{html.escape(str(sub.get('id')))}</code>\n"
        f"📅 <b>Создана:</b> {created_date}\n"
        "──────────────────────────────\n"
        f"🔗 <b>URL:</b> <code>{sub_url}</code>"
    )
    await show(callback, text, subscription_detail_kb(sid, is_enabled))
    return True


@router.callback_query(F.data.startswith("sub:view:"))
async def cb_sub_view(callback: CallbackQuery, state: FSMContext):
    # "Отмена" from rename comes here: without clearing, the next text message would rename the subscription
    await state.clear()
    sid = callback.data.split(":")[-1]
    if await render_subscription(callback, sid):
        await callback.answer()
    else:
        await callback.answer("Подписка не найдена!", show_alert=True)


@router.callback_query(F.data.startswith("sub:toggle:"))
async def cb_sub_toggle(callback: CallbackQuery):
    _, _, sid, action = callback.data.split(":")
    enable = (action == "enable")
    try:
        await run(WPPService.toggle_subscription, sid, enable)
    except Exception as exc:
        await callback.answer(f"Ошибка: {exc}"[:200], show_alert=True)
        return

    await callback.answer("Статус подписки изменен ✅")
    await render_subscription(callback, sid)


@router.callback_query(F.data.startswith("sub:link:"))
async def cb_sub_link(callback: CallbackQuery):
    await callback.answer("Получаем ссылку...")
    sid = callback.data.split(":")[-1]
    sub = await run(WPPService.get_subscription_by_id, sid)
    if not sub:
        await callback.message.answer("Подписка не найдена.")
        return

    sub_name = html.escape(str(sub.get("name", "Подписка")))
    escaped_url = html.escape(str(sub.get("url", "")))

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📱 Открыть QR-код", callback_data=f"sub:qr:{sid}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад к подписке", callback_data=f"sub:view:{sid}"))

    text = (
        f"🔗 <b>Ссылка на подписку «{sub_name}»:</b>\n\n"
        f"<code>{escaped_url}</code>\n\n"
        "<b>Как использовать:</b>\n"
        "1. Скопируйте ссылку нажатием на неё.\n"
        "2. Вставьте в приложение: <b>Happ</b>, <b>Streisand</b>, <b>v2rayNG</b> или <b>sing-box</b>.\n"
        "3. В приложении автоматически появятся все серверные маршруты (Hysteria, VLESS, CDN)!"
    )
    await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("sub:qr:"))
async def cb_sub_qr(callback: CallbackQuery):
    await callback.answer("Генерируем QR-код...")
    sid = callback.data.split(":")[-1]
    sub = await run(WPPService.get_subscription_by_id, sid)
    if not sub:
        await callback.message.answer("Подписка не найдена.")
        return

    sub_url = str(sub.get("url", ""))
    sub_name = html.escape(str(sub.get("name", "Подписка")))

    try:
        qr_io = await run(generate_qr_bytes, sub_url)
        photo = BufferedInputFile(qr_io.getvalue(), filename="sub_qr.png")

        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Назад к подписке", callback_data=f"sub:view:{sid}"))

        caption = (
            f"📱 <b>QR-код подписки: {sub_name}</b>\n\n"
            "<i>Отсканируйте камерой смартфона или через приложение Happ / Streisand / v2rayNG для мгновенного импорта.</i>"
        )
        await callback.message.answer_photo(
            photo=photo,
            caption=caption,
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    except Exception as exc:
        await callback.message.answer(f"❌ Ошибка формирования QR-кода: {html.escape(str(exc))}")


async def render_devices(callback: CallbackQuery, sid: str) -> bool:
    sub = await run(WPPService.get_subscription_by_id, sid)
    if not sub:
        return False

    active_devices = [d for d in sub.get("devices", []) if not d.get("revoked")]
    builder = InlineKeyboardBuilder()
    sub_name = html.escape(str(sub.get("name", "Подписка")))

    if not active_devices:
        text = (
            f"📱 <b>Устройства подписки «{sub_name}»</b>\n\n"
            "Пока ни одно устройство не подключилось по этой подписке.\n"
            "Как только пользователь откроет ссылку или отсканирует QR, его устройство появится здесь."
        )
    else:
        text = f"📱 <b>Подключенные устройства ({len(active_devices)}):</b>\n\n"
        for d in active_devices:
            raw_name = str(d.get("name", "Устройство"))
            did = str(d.get("id", ""))
            text += f"• <b>{html.escape(raw_name)}</b> (ID: <code>{html.escape(did[:8])}...</code>)\n"
            # Button text is plain text, so no HTML escaping there (it would show "&amp;")
            builder.row(InlineKeyboardButton(text=f"🚫 Отозвать {raw_name}"[:60], callback_data=f"sub:revoke:{sid}:{did}"))

    builder.row(InlineKeyboardButton(text="🔙 Назад к подписке", callback_data=f"sub:view:{sid}"))
    await show(callback, text, builder.as_markup())
    return True


@router.callback_query(F.data.startswith("sub:devices:"))
async def cb_sub_devices(callback: CallbackQuery):
    sid = callback.data.split(":")[-1]
    if await render_devices(callback, sid):
        await callback.answer()
    else:
        await callback.answer("Подписка не найдена", show_alert=True)


@router.callback_query(F.data.startswith("sub:revoke:"))
async def cb_sub_revoke_device(callback: CallbackQuery):
    _, _, sid, did = callback.data.split(":")
    try:
        await run(WPPService.revoke_sub_device, sid, did)
    except Exception as exc:
        await callback.answer(f"Ошибка отзыва: {exc}"[:200], show_alert=True)
        return

    await callback.answer("Устройство отозвано 🚫", show_alert=True)
    await render_devices(callback, sid)


@router.callback_query(F.data.startswith("sub:rotate_confirm:"))
async def cb_sub_rotate_confirm(callback: CallbackQuery):
    sid = callback.data.split(":")[-1]
    sub = await run(WPPService.get_subscription_by_id, sid)
    if not sub:
        await callback.answer("Подписка не найдена", show_alert=True)
        return
    sub_name = html.escape(str(sub.get("name", "Подписка")))

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Да, сменить ключ", callback_data=f"sub:rotate_exec:{sid}"),
        InlineKeyboardButton(text="🔙 Отмена", callback_data=f"sub:view:{sid}"),
    )
    text = (
        f"⚠️ <b>Смена ключа подписки «{sub_name}»</b>\n\n"
        "Старая ссылка перестанет работать, и все ранее подключенные устройства будут отключены.\n"
        "Пользователю потребуется обновить ссылку или QR-код."
    )
    await show(callback, text, builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("sub:rotate_exec:"))
async def cb_sub_rotate_exec(callback: CallbackQuery):
    sid = callback.data.split(":")[-1]
    try:
        await run(WPPService.rotate_subscription, sid)
    except Exception as exc:
        await callback.answer(f"Ошибка ротации: {exc}"[:200], show_alert=True)
        return

    await callback.answer("Ключ подписки успешно обновлен! 🔄", show_alert=True)
    await render_subscription(callback, sid)


@router.callback_query(F.data.startswith("sub:del_confirm:"))
async def cb_sub_del_confirm(callback: CallbackQuery):
    sid = callback.data.split(":")[-1]
    sub = await run(WPPService.get_subscription_by_id, sid)
    if not sub:
        await callback.answer("Подписка не найдена", show_alert=True)
        return

    sub_name = html.escape(str(sub.get("name", "Подписка")))
    text = (
        f"⚠️ <b>Вы уверены, что хотите удалить подписку «{sub_name}»?</b>\n\n"
        "Все привязанные ключи доступа будут удалены, а подключенные устройства потеряют доступ."
    )
    await show(callback, text, confirm_delete_kb("sub", sid))
    await callback.answer()


@router.callback_query(F.data.startswith("del:exec:sub:"))
async def cb_sub_del_exec(callback: CallbackQuery):
    sid = callback.data.split(":")[-1]
    try:
        await run(WPPService.delete_subscription, sid)
    except Exception as exc:
        await callback.answer(f"Ошибка удаления: {exc}"[:200], show_alert=True)
        return

    await callback.answer("Подписка успешно удалена 🗑", show_alert=True)
    subs = await run(WPPService.get_subscriptions)
    await show(callback, SUBS_LIST_TEXT.format(count=len(subs)), subscriptions_list_kb(subs, page=0))


@router.callback_query(F.data.startswith("sub:rename:"))
async def cb_sub_rename(callback: CallbackQuery, state: FSMContext):
    sid = callback.data.split(":")[-1]
    await state.set_state(RenameSubState.waiting_for_name)
    await state.update_data(sub_id=sid)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data=f"sub:view:{sid}"))

    await show(callback, "✏️ <b>Введите новое название для подписки:</b>", builder.as_markup())
    await callback.answer()


@router.message(RenameSubState.waiting_for_name, F.text)
async def msg_sub_rename(message: Message, state: FSMContext):
    data = await state.get_data()
    sid = data.get("sub_id")
    new_name = message.text.strip()

    if not new_name or len(new_name) > 80:
        await message.answer("⚠️ Имя должно содержать от 1 до 80 символов. Попробуйте снова:")
        return

    await state.clear()
    try:
        await run(WPPService.rename_subscription, sid, new_name)
        await message.answer(f"✅ Подписка переименована в <b>{html.escape(new_name)}</b>!", parse_mode="HTML")
    except Exception as exc:
        await message.answer(f"❌ Ошибка переименования: {html.escape(str(exc))}")

    sub = await run(WPPService.get_subscription_by_id, sid)
    if sub:
        is_enabled = bool(sub.get("enabled", True))
        await message.answer(
            f"📦 <b>Подписка:</b> <code>{html.escape(str(sub.get('name', '')))}</code>\nID: <code>{html.escape(str(sid))}</code>",
            reply_markup=subscription_detail_kb(sid, is_enabled),
            parse_mode="HTML",
        )


@router.message(RenameSubState.waiting_for_name)
async def msg_sub_rename_not_text(message: Message):
    await message.answer("⚠️ Отправьте новое название текстом.")
