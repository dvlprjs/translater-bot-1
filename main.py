import json
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from deep_translator import GoogleTranslator

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
print(ADMIN_ID)


users = {}

def load_users():
    global users
    try:
        with open('users.json', 'r', encoding='utf-8') as f:
            users = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        users = {}

def save_users():
    with open('users.json', 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=4)

load_users()

async def start(update: Update, context):
    user_id = str(update.effective_user.id)
    username = update.effective_user.username
    name = update.effective_user.first_name

    if user_id not in users:
        users[user_id] = {
            'username': username,
            'name': name,
            'lang': "en-uz"
        }
        save_users()

    await update.message.reply_text(
        "Salom! Tarjima botiga xush kelibsiz.\n\n"
        "Tarjima qilinadigan matnni kiriting yoki tilni o'zgartirish uchun /change_lang ni bosing."
    )

async def user_id_command(update: Update, context):
    user_id = update.effective_user.id
    await update.message.reply_text(f"Sizning Telegram ID: {user_id}")

async def show_language_selection(update: Update):
    keyboard = [
        [InlineKeyboardButton("en-uz (Inglizcha - O'zbekcha)", callback_data='en-uz')],
        [InlineKeyboardButton("uz-en (O'zbekcha - Inglizcha)", callback_data='uz-en')],
        [InlineKeyboardButton("ru-uz (Ruscha - O'zbekcha)", callback_data='ru-uz')],
        [InlineKeyboardButton("uz-ru (O'zbekcha - Ruscha)", callback_data='uz-ru')],
        [InlineKeyboardButton("ru-en (Ruscha - Inglizcha)", callback_data='ru-en')],
        [InlineKeyboardButton("en-ru (Inglizcha - Ruscha)", callback_data='en-ru')],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Tilni tanlang:", reply_markup=reply_markup)

async def button(update: Update, context):
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)

    if query.data in ["en-uz", "uz-en", "ru-uz", "uz-ru", "ru-en", "en-ru"]:
        users[user_id]["lang"] = query.data
        save_users()
        await query.edit_message_text(f"{query.data} tanlandi. Tarjima qilinadigan matnni kiriting:")
    else:
        await query.edit_message_text("Noto'g'ri tanlov.")

async def change_language(update: Update, context):
    await show_language_selection(update)

async def translate_text(update: Update, context):
    user_id = str(update.effective_user.id)

    current_lang = users.get(user_id, {}).get("lang", "en-uz")

    user_input = update.message.text
    try:
        lang_mapping = {
            "en-uz": "uz",
            "uz-en": "en",
            "ru-uz": "uz",
            "uz-ru": "ru",
            "ru-en": "en",
            "en-ru": "ru"
        }
        target_lang = lang_mapping.get(current_lang, "uz")  # Default til uzbek

        tarjima = GoogleTranslator(source='auto', target=target_lang).translate(user_input)
        await update.message.reply_text(tarjima)
    except Exception:
        await update.message.reply_text("Tarjima qilishda xato yuz berdi. Iltimos, qayta urinib ko'ring.")

async def users_list(update: Update, context):
    user_id = update.effective_user.id

    if user_id == ADMIN_ID:
        if not users:
            await update.message.reply_text("Hech qanday foydalanuvchi ro'yxatda yo'q.")
            return

        user_list_message = "Foydalanuvchilar ro'yxati:\n"
        for uid, info in users.items():
            user_list_message += f"ID: {uid}, username: @{info['username']}, Name: {info['name']}, Lang: {info.get('lang', 'en-uz')}\n"

        await update.message.reply_text(user_list_message)
    else:
        await update.message.reply_text("Sizda bu buyruqni bajarish huquqi yo'q.")

if __name__ == '__main__':
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("user_id", user_id_command))
    application.add_handler(CommandHandler("change_lang", change_language))
    application.add_handler(CommandHandler("users", users_list))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, translate_text))

    application.run_polling()