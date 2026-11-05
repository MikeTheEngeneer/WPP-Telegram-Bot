"""Creation wizard handlers for clients and subscriptions."""
import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards import create_type_kb
from qr import generate_qr_bytes
from service import WPPService

from .common import run, show

router = Router()

PROTO_NAMES = {
    "subscription": "Мульти-подписка (VLESS + Hysteria 2)",
    "vless": "VLESS (XHTTP + CDN)",
    "hysteria": "Hysteria 2 (UDP/QUIC)",
    "mtproto": "MTProto (Telegram Proxy)",
    "awg20": "AmneziaWG (WireGuard)",
}


class CreateWizard(StatesGroup):
    choosing_type = State()
    waiting_for_name = State()
    waiting_for_sub_limit = State()


@router.callback_query(F.data.in_(["create:start", "create:client_direct", "create:subscription"]))
async def cb_create_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.data == "create:subscription":
        await state.set_state(CreateWizard.waiting_for_name)
        await state.update_data(proto_type="subscription")
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="subs:page:0"))
        await show(
            callback,
            "📦 <b>Создание мульти-подписки</b>\n\n"
            "Введите название подписки (например: <i>Семья, iPhone, Личный</i>):",
            builder.as_markup(),
        )
    elif callback.data == "create:client_direct":
        await state.set_state(CreateWizard.choosing_type)
        text = (
            "➕ <b>Создание отдельного подключения</b>\n\n"
            "Выберите протокол подключения:"
        )
        await show(callback, text, create_type_kb())
    else:
        await state.set_state(CreateWizard.choosing_type)
        text = (
            "➕ <b>Мастер создания подключений</b>\n\n"
            "Что вы хотите создать?\n"
            "• <b>Мульти-подписка</b> — единая ссылка (VLESS + Hysteria 2) для удобного импорта в Happ, Streisand, v2rayNG.\n"
            "• <b>Прямой протокол</b> — отдельный ключ под конкретный протокол."
        )
        await show(callback, text, create_type_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("create:type:"))
async def cb_create_choose_type(callback: CallbackQuery, state: FSMContext):
    proto_type = callback.data.split(":")[-1]
    if proto_type not in PROTO_NAMES:
        await callback.answer("Неизвестный тип", show_alert=True)
        return
    await state.set_state(CreateWizard.waiting_for_name)
    await state.update_data(proto_type=proto_type)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="menu:main"))

    text = (
        f"➕ Создание: <b>{PROTO_NAMES[proto_type]}</b>\n\n"
        "Введите имя пользователя или название устройства\n"
        "<i>(например: iPhone, Рабочий ПК, Мама):</i>"
    )
    await show(callback, text, builder.as_markup())
    await callback.answer()


@router.message(CreateWizard.waiting_for_name, F.text)
async def msg_create_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name or len(name) > 80:
        await message.answer("⚠️ Имя должно содержать от 1 до 80 символов. Попробуйте снова:")
        return

    data = await state.get_data()
    proto_type = data.get("proto_type")
    await state.update_data(name=name)

    if proto_type == "subscription":
        await state.set_state(CreateWizard.waiting_for_sub_limit)
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="0 (Без лимита)", callback_data="sub_limit:0"),
            InlineKeyboardButton(text="1 устр.", callback_data="sub_limit:1"),
            InlineKeyboardButton(text="2 устр.", callback_data="sub_limit:2"),
        )
        builder.row(
            InlineKeyboardButton(text="3 устр.", callback_data="sub_limit:3"),
            InlineKeyboardButton(text="5 устр.", callback_data="sub_limit:5"),
            InlineKeyboardButton(text="10 устр.", callback_data="sub_limit:10"),
        )
        await message.answer(
            f"📱 Укажите <b>лимит одновременно подключенных устройств</b> для «{html.escape(name)}»:\n"
            "<i>(0 — без ограничений по HWID)</i>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        return

    # Direct client creation
    await state.clear()
    msg_wait = await message.answer("⏳ Создаем подключение и синхронизируем службы...")
    try:
        # panelctl add-json prints the created user record (with id and secret)
        created = await run(WPPService.create_client, name=name, protocol=proto_type)
        cid = str(created.get("id", "")) if isinstance(created, dict) else ""
        fresh = await run(WPPService.get_client_by_id, cid) if cid else None
        if fresh:
            created = fresh
        link = await run(WPPService.generate_proxy_link, created)
        await msg_wait.delete()

        builder = InlineKeyboardBuilder()
        if cid:
            builder.row(InlineKeyboardButton(text="⚙️ Управление клиентом", callback_data=f"client:view:{cid}"))
        builder.row(InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu:main"))

        if proto_type in ("awg20", "awg31"):
            # A WireGuard config is multi-line and usually too large for a QR caption: send it as a file
            await message.answer_document(
                document=BufferedInputFile(link.encode("utf-8"), filename=f"wpp-{cid or 'awg'}.conf"),
                caption=f"🎉 <b>Подключение «{html.escape(name)}» успешно создано!</b>\nПротокол: <code>AMNEZIAWG</code>",
                reply_markup=builder.as_markup(),
                parse_mode="HTML",
            )
            return

        qr_io = await run(generate_qr_bytes, link)
        photo = BufferedInputFile(qr_io.getvalue(), filename="qr.png")
        caption = (
            f"🎉 <b>Подключение «{html.escape(name)}» успешно создано!</b>\n"
            f"Протокол: <code>{html.escape(proto_type.upper())}</code>\n\n"
            f"🔗 <b>Ссылка:</b>\n<code>{html.escape(link)}</code>"
        )
        if len(caption) > 1024:  # Telegram caption limit; long VLESS links with "extra" can exceed it
            await message.answer_photo(photo=photo, caption=f"🎉 <b>Подключение «{html.escape(name)}» успешно создано!</b>", parse_mode="HTML")
            await message.answer(f"🔗 <b>Ссылка:</b>\n<code>{html.escape(link)}</code>", reply_markup=builder.as_markup(), parse_mode="HTML")
        else:
            await message.answer_photo(photo=photo, caption=caption, reply_markup=builder.as_markup(), parse_mode="HTML")

    except Exception as exc:
        await msg_wait.edit_text(f"❌ Ошибка создания подключения: {html.escape(str(exc))}")


@router.callback_query(CreateWizard.waiting_for_sub_limit, F.data.startswith("sub_limit:"))
async def cb_sub_limit_button(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    limit = int(callback.data.split(":")[-1])
    await process_sub_creation(callback.message, state, limit)


@router.callback_query(F.data.startswith("sub_limit:"))
async def cb_sub_limit_stale(callback: CallbackQuery):
    # Old buttons after the wizard finished/cancelled used to create a subscription named "Подписка"
    await callback.answer("Мастер уже завершён. Начните создание заново.", show_alert=True)


@router.message(CreateWizard.waiting_for_sub_limit, F.text)
async def msg_sub_limit_text(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or not (0 <= int(text) <= 20):
        await message.answer("⚠️ Введите число от 0 до 20 (0 — без лимита):")
        return
    await process_sub_creation(message, state, int(text))


@router.message(CreateWizard.waiting_for_name)
@router.message(CreateWizard.waiting_for_sub_limit)
async def msg_wizard_not_text(message: Message):
    await message.answer("⚠️ Отправьте ответ текстом или нажмите «Отмена».")


async def process_sub_creation(target_msg: Message, state: FSMContext, max_devices: int):
    data = await state.get_data()
    name = data.get("name", "Подписка")
    await state.clear()

    wait_msg = await target_msg.answer("⏳ Создаем мульти-подписку...")
    try:
        res = await run(WPPService.create_subscription, name=name, max_devices=max_devices)
        sid = str(res.get("id", "")) if isinstance(res, dict) else ""
        created_sub = await run(WPPService.get_subscription_by_id, sid) if sid else None
        if not created_sub:
            raise RuntimeError("подписка создана, но не найдена в списке — проверьте веб-панель")
        sub_url = created_sub.get("url", "")
        await wait_msg.delete()

        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="⚙️ Управление подпиской", callback_data=f"sub:view:{sid}"))
        builder.row(InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu:main"))

        qr_io = await run(generate_qr_bytes, sub_url)
        photo = BufferedInputFile(qr_io.getvalue(), filename="sub_qr.png")

        limit_info = f"{max_devices} устр." if max_devices else "без лимита"
        caption = (
            f"🎉 <b>Мульти-подписка «{html.escape(name)}» создана!</b>\n"
            f"Лимит: <code>{limit_info}</code>\n\n"
            f"🔗 <b>Ссылка для приложений (Happ, Streisand, v2rayNG):</b>\n"
            f"<code>{html.escape(sub_url)}</code>\n\n"
            "<i>💡 Нажмите на ссылку, чтобы скопировать её.</i>"
        )
        await target_msg.answer_photo(
            photo=photo,
            caption=caption,
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    except Exception as exc:
        await wait_msg.edit_text(f"❌ Ошибка создания подписки: {html.escape(str(exc))}")
