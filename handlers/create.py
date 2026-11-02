"""Creation wizard handlers for clients and subscriptions."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from keyboards import create_type_kb
from qr import generate_qr_bytes
from service import WPPService

router = Router()


class CreateWizard(StatesGroup):
    choosing_type = State()
    waiting_for_name = State()
    waiting_for_sub_limit = State()


def is_admin(user_id: int) -> bool:
    return not ADMIN_IDS or user_id in ADMIN_IDS


@router.callback_query(F.data.in_(["create:start", "create:client_direct", "create:subscription"]))
async def cb_create_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    if callback.data == "create:subscription":
        await state.update_data(proto_type="subscription")
        await state.set_state(CreateWizard.waiting_for_name)
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="subs:page:0"))
        await callback.message.edit_text(
            "📦 <b>Создание мульти-подписки</b>\n\n"
            "Введите название подписки (например: <i>Семья, iPhone, Личный</i>):",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    elif callback.data == "create:client_direct":
        await state.set_state(CreateWizard.choosing_type)
        text = (
            "➕ <b>Создание отдельного подключения</b>\n\n"
            "Выберите протокол подключения:"
        )
        await callback.message.edit_text(text, reply_markup=create_type_kb(), parse_mode="HTML")
    else:
        await state.set_state(CreateWizard.choosing_type)
        text = (
            "➕ <b>Мастер создания подключений</b>\n\n"
            "Что вы хотите создать?\n"
            "• <b>Мульти-подписка</b> — единая ссылка (VLESS + Hysteria 2) для удобного импорта в Happ, Streisand, v2rayNG.\n"
            "• <b>Прямой протокол</b> — отдельный ключ под конкретный протокол."
        )
        await callback.message.edit_text(text, reply_markup=create_type_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("create:type:"))
async def cb_create_choose_type(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    proto_type = callback.data.split(":")[-1]
    await state.update_data(proto_type=proto_type)
    await state.set_state(CreateWizard.waiting_for_name)

    proto_names = {
        "subscription": "Мульти-подписка (VLESS + Hysteria 2)",
        "vless": "VLESS (XHTTP + CDN)",
        "hysteria": "Hysteria 2 (UDP/QUIC)",
        "mtproto": "MTProto (Telegram Proxy)",
        "awg20": "AmneziaWG (WireGuard)",
    }
    selected_name = proto_names.get(proto_type, proto_type)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="menu:main"))

    text = (
        f"➕ Создание: <b>{selected_name}</b>\n\n"
        "Введите имя пользователя или название устройства\n"
        "<i>(например: iPhone, Рабочий ПК, Мама):</i>"
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.message(CreateWizard.waiting_for_name)
async def msg_create_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
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
            f"📱 Укажите <b>лимит одновременно подключенных устройств</b> для «{name}»:\n"
            "<i>(0 — без ограничений по HWID)</i>",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        return

    # Direct client creation
    await state.clear()
    msg_wait = await message.answer("⏳ Создаем подключение и синхронизируем службы...")
    try:
        res = WPPService.create_client(name=name, protocol=proto_type)
        await msg_wait.delete()

        # Find the newly created client
        clients = WPPService.get_clients()
        created = next((c for c in clients if c.get("name") == name), None) or res
        link = WPPService.generate_proxy_link(created)

        builder = InlineKeyboardBuilder()
        cid = created.get("id", "")
        if cid:
            builder.row(InlineKeyboardButton(text="⚙️ Управление клиентом", callback_data=f"client:view:{cid}"))
        builder.row(InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu:main"))

        # Send QR code
        qr_io = generate_qr_bytes(link)
        photo = BufferedInputFile(qr_io.getvalue(), filename="qr.png")

        caption = (
            f"🎉 <b>Подключение «{name}» успешно создано!</b>\n"
            f"Протокол: <code>{proto_type.upper()}</code>\n\n"
            f"🔗 <b>Ссылка:</b>\n<code>{link}</code>"
        )
        await message.answer_photo(
            photo=photo,
            caption=caption,
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )

    except Exception as exc:
        await msg_wait.edit_text(f"❌ Ошибка создания подключения: {exc}")


@router.callback_query(F.data.startswith("sub_limit:"))
async def cb_sub_limit_button(callback: CallbackQuery, state: FSMContext):
    limit = int(callback.data.split(":")[-1])
    await process_sub_creation(callback.message, state, limit)
    await callback.answer()


@router.message(CreateWizard.waiting_for_sub_limit)
async def msg_sub_limit_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = message.text.strip()
    if not text.isdigit() or not (0 <= int(text) <= 20):
        await message.answer("⚠️ Введите число от 0 до 20 (0 — без лимита):")
        return
    await process_sub_creation(message, state, int(text))


async def process_sub_creation(target_msg: Message, state: FSMContext, max_devices: int):
    data = await state.get_data()
    name = data.get("name", "Подписка")
    await state.clear()

    wait_msg = await target_msg.answer("⏳ Создаем мульти-подписку...")
    try:
        WPPService.create_subscription(name=name, max_devices=max_devices)
        await wait_msg.delete()

        # Find created subscription
        subs = WPPService.get_subscriptions()
        created_sub = next((s for s in subs if s.get("name") == name), None)
        sub_url = created_sub.get("url") if created_sub else ""

        builder = InlineKeyboardBuilder()
        sid = created_sub.get("id", "") if created_sub else ""
        if sid:
            builder.row(InlineKeyboardButton(text="⚙️ Управление подпиской", callback_data=f"sub:view:{sid}"))
        builder.row(InlineKeyboardButton(text="🚀 Открыть в Happ", url=f"happ://add/{sub_url}"))
        builder.row(InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu:main"))

        # Send QR code
        qr_io = generate_qr_bytes(sub_url)
        photo = BufferedInputFile(qr_io.getvalue(), filename="sub_qr.png")

        limit_info = f"{max_devices} устр." if max_devices else "без лимита"
        caption = (
            f"🎉 <b>Мульти-подписка «{name}» создана!</b>\n"
            f"Лимит: <code>{limit_info}</code>\n\n"
            f"🔗 <b>Ссылка для приложений (Happ, Streisand, v2rayNG):</b>\n"
            f"<code>{sub_url}</code>"
        )
        await target_msg.answer_photo(
            photo=photo,
            caption=caption,
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    except Exception as exc:
        await wait_msg.edit_text(f"❌ Ошибка создания подписки: {exc}")
