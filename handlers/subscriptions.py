"""Handlers for subscription management."""
import datetime
import html
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from keyboards import confirm_delete_kb, subscription_detail_kb, subscriptions_list_kb
from qr import generate_qr_bytes
from service import WPPService, format_bytes

router = Router()


class RenameSubState(StatesGroup):
    waiting_for_name = State()


def is_admin(user_id: int) -> bool:
    return not ADMIN_IDS or user_id in ADMIN_IDS


@router.callback_query(F.data.startswith("subs:page:"))
async def cb_subs_page(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    page = int(callback.data.split(":")[-1])
    subs = WPPService.get_subscriptions()
    kb = subscriptions_list_kb(subs, page=page)
    text = (
        "📦 <b>Мульти-протокольные подписки</b>\n"
        "──────────────────────────────\n"
        f"Всего подписок: <b>{len(subs)}</b>\n\n"
        "<i>Подписка объединяет протоколы (VLESS + Hysteria 2) в одну ссылку "
        "для Happ, Streisand, v2rayNG, sing-box и Nekoray.</i>\n\n"
        "Выберите подписку для управления:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("sub:view:"))
async def cb_sub_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    sid = callback.data.split(":")[-1]
    sub = WPPService.get_subscription_by_id(sid)
    if not sub:
        await callback.answer("Подписка не найдена!", show_alert=True)
        return

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
        f"🆔 <b>ID:</b> <code>{sub.get('id')}</code>\n"
        f"📅 <b>Создана:</b> {created_date}\n"
        "──────────────────────────────\n"
        f"🔗 <b>URL:</b> <code>{sub_url}</code>"
    )
    kb = subscription_detail_kb(sid, is_enabled)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("sub:toggle:"))
async def cb_sub_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    _, _, sid, action = callback.data.split(":")
    enable = (action == "enable")
    try:
        WPPService.toggle_subscription(sid, enable)
        await callback.answer("Статус подписки изменен ✅")
    except Exception as exc:
        await callback.answer(f"Ошибка: {exc}", show_alert=True)
        return

    callback.data = f"sub:view:{sid}"
    await cb_sub_view(callback)


@router.callback_query(F.data.startswith("sub:link:"))
async def cb_sub_link(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    await callback.answer("Получаем ссылку...")
    sid = callback.data.split(":")[-1]
    sub = WPPService.get_subscription_by_id(sid)
    if not sub:
        await callback.message.answer("Подписка не найдена.")
        return

    sub_url = str(sub.get("url", ""))
    sub_name = html.escape(str(sub.get("name", "Подписка")))
    escaped_url = html.escape(sub_url)

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
    try:
        await callback.message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception as exc:
        await callback.message.answer(f"❌ Ошибка отправки: {html.escape(str(exc))}")


@router.callback_query(F.data.startswith("sub:qr:"))
async def cb_sub_qr(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    await callback.answer("Генерируем QR-код...")
    sid = callback.data.split(":")[-1]
    sub = WPPService.get_subscription_by_id(sid)
    if not sub:
        await callback.message.answer("Подписка не найдена.")
        return

    sub_url = str(sub.get("url", ""))
    sub_name = html.escape(str(sub.get("name", "Подписка")))

    try:
        qr_io = generate_qr_bytes(sub_url)
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


@router.callback_query(F.data.startswith("sub:devices:"))
async def cb_sub_devices(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    sid = callback.data.split(":")[-1]
    sub = WPPService.get_subscription_by_id(sid)
    if not sub:
        await callback.answer("Подписка не найдена", show_alert=True)
        return

    devices = sub.get("devices", [])
    active_devices = [d for d in devices if not d.get("revoked")]

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
            d_name = html.escape(str(d.get("name", "Устройство")))
            did = d.get("id", "")
            text += f"• <b>{d_name}</b> (ID: <code>{did[:8]}...</code>)\n"
            builder.row(
                InlineKeyboardButton(
                    text=f"🚫 Отозвать {d_name}",
                    callback_data=f"sub:revoke:{sid}:{did}"
                )
            )

    builder.row(InlineKeyboardButton(text="🔙 Назад к подписке", callback_data=f"sub:view:{sid}"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("sub:revoke:"))
async def cb_sub_revoke_device(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    _, _, sid, did = callback.data.split(":")
    try:
        WPPService.revoke_sub_device(sid, did)
        await callback.answer("Устройство отозвано 🚫", show_alert=True)
    except Exception as exc:
        await callback.answer(f"Ошибка отзыва: {exc}", show_alert=True)
        return

    callback.data = f"sub:devices:{sid}"
    await cb_sub_devices(callback)


@router.callback_query(F.data.startswith("sub:rotate_confirm:"))
async def cb_sub_rotate_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    sid = callback.data.split(":")[-1]
    sub = WPPService.get_subscription_by_id(sid)
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
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("sub:rotate_exec:"))
async def cb_sub_rotate_exec(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    sid = callback.data.split(":")[-1]
    try:
        WPPService.rotate_subscription(sid)
        await callback.answer("Ключ подписки успешно обновлен! 🔄", show_alert=True)
    except Exception as exc:
        await callback.answer(f"Ошибка ротации: {exc}", show_alert=True)
        return

    callback.data = f"sub:view:{sid}"
    await cb_sub_view(callback)


@router.callback_query(F.data.startswith("sub:del_confirm:"))
async def cb_sub_del_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    sid = callback.data.split(":")[-1]
    sub = WPPService.get_subscription_by_id(sid)
    if not sub:
        await callback.answer("Подписка не найдена", show_alert=True)
        return

    sub_name = html.escape(str(sub.get("name", "Подписка")))
    text = (
        f"⚠️ <b>Вы уверены, что хотите удалить подписку «{sub_name}»?</b>\n\n"
        "Все привязанные ключи доступа будут удалены, а подключенные устройства потеряют доступ."
    )
    kb = confirm_delete_kb("sub", sid)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("del:exec:sub:"))
async def cb_sub_del_exec(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    sid = callback.data.split(":")[-1]
    try:
        WPPService.delete_subscription(sid)
        await callback.answer("Подписка успешно удалена 🗑", show_alert=True)
    except Exception as exc:
        await callback.answer(f"Ошибка удаления: {exc}", show_alert=True)
        return

    subs = WPPService.get_subscriptions()
    kb = subscriptions_list_kb(subs, page=0)
    text = (
        "📦 <b>Мульти-протокольные подписки</b>\n"
        "──────────────────────────────\n"
        f"Всего подписок: <b>{len(subs)}</b>\n"
    )
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("sub:rename:"))
async def cb_sub_rename(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    sid = callback.data.split(":")[-1]
    await state.update_data(sub_id=sid)
    await state.set_state(RenameSubState.waiting_for_name)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data=f"sub:view:{sid}"))

    await callback.message.edit_text(
        "✏️ <b>Введите новое название для подписки:</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(RenameSubState.waiting_for_name)
async def msg_sub_rename(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    sid = data.get("sub_id")
    new_name = message.text.strip()

    if not new_name or len(new_name) > 80:
        await message.answer("⚠️ Имя должно содержать от 1 до 80 символов. Попробуйте снова:")
        return

    await state.clear()
    try:
        WPPService.rename_subscription(sid, new_name)
        await message.answer(f"✅ Подписка переименована в <b>{html.escape(new_name)}</b>!", parse_mode="HTML")
    except Exception as exc:
        await message.answer(f"❌ Ошибка переименования: {html.escape(str(exc))}")

    sub = WPPService.get_subscription_by_id(sid)
    if sub:
        is_enabled = bool(sub.get("enabled", True))
        kb = subscription_detail_kb(sid, is_enabled)
        await message.answer(
            f"📦 <b>Подписка:</b> <code>{html.escape(sub.get('name'))}</code>\nID: <code>{sid}</code>",
            reply_markup=kb,
            parse_mode="HTML",
        )
