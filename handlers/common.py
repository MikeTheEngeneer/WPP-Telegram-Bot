"""Shared helpers for handlers."""
import asyncio
import functools
from typing import Any, Callable

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup


async def run(func: Callable, *args: Any, **kwargs: Any) -> Any:
    """Run blocking service code (subprocess, file IO, psutil) off the event loop."""
    return await asyncio.to_thread(functools.partial(func, *args, **kwargs))


async def show(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    """Edit the current message in place; fall back to a new message (e.g. when it is a photo/document)."""
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
