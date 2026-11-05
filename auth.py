"""Access control: the bot runs as root and manages the proxy server, so it is admin-only."""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import ADMIN_IDS


def is_admin(user_id: int) -> bool:
    """Fail closed: an empty ADMIN_IDS means nobody is allowed, never everybody."""
    return bool(ADMIN_IDS) and user_id in ADMIN_IDS


class AdminOnlyMiddleware(BaseMiddleware):
    """Outer middleware that drops every update from non-admins before any handler runs."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is not None and is_admin(user.id):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer("Доступ запрещен", show_alert=True)
        elif isinstance(event, Message) and event.text and event.text.startswith("/start") and user:
            await event.answer(
                "⛔️ <b>Доступ запрещен.</b>\n\n"
                f"Ваш Telegram ID: <code>{user.id}</code>\n"
                "Добавьте его в <code>ADMIN_IDS</code> в файле <code>.env</code> для доступа к боту.",
                parse_mode="HTML",
            )
        return None
