
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards.main import main_keyboard

router = Router(name="start")


@router.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()

    await message.answer(
        "🐙 Welcome to GitHub Downloader!\n\n"
        "Send a GitHub repository link anytime to explore it, "
        "or choose an option below.",
        reply_markup=main_keyboard(),
    )


@router.message(Command("menu"))
async def menu_command_handler(
    message: Message,
    state: FSMContext,
) -> None:
    """Open the main menu from the /menu command."""
    await state.clear()

    await message.answer(
        "🏠 <b>Main Menu</b>\n\nWhat would you like to do today?",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )
