"""Backup export handler."""
import datetime
from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery

from config import ADMIN_IDS
from keyboards import back_to_menu_kb
from service import WPPService

router = Router()


def is_admin(user_id: int) -> bool:
    return not ADMIN_IDS or user_id in ADMIN_IDS


@router.callback_query(F.data == "menu:backup")
async def cb_export_backup(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    wait_msg = await callback.message.answer("📦 Формируем резервную копию настроек WPP...")
    try:
        raw_zip = WPPService.export_backup_zip()
        now_str = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"wpp-backup-{now_str}.zip"

        doc = BufferedInputFile(raw_zip, filename=filename)
        caption = (
            "💾 <b>Полная резервная копия Web-Panel-Proxy</b>\n\n"
            "Архив содержит:\n"
            "• Клиентов, ключи и подписки\n"
            "• Настройки подключений и маршрутизации\n"
            "• Параметры нод и сайта-заглушки\n\n"
            "<i>Храните архив в надежном месте. При необходимости его можно восстановить прямо в веб-панели (раздел «Настройки»).</i>"
        )
        await wait_msg.delete()
        await callback.message.answer_document(
            document=doc,
            caption=caption,
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
    except Exception as exc:
        await wait_msg.edit_text(f"❌ Не удалось создать резервную копию: {exc}")
    await callback.answer()
