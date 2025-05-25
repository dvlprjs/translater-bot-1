import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
)
from telegram.request import HTTPXRequest
from deep_translator import GoogleTranslator
from dotenv import load_dotenv
import os
import logging
import asyncio
import httpx

logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
db_pool = None

async def create_db_pool():
    try:
        pool = await asyncpg.create_pool(
            dsn=os.getenv("DATABASE_URL"),
            min_size=1,
            max_size=10,
            timeout=30
        )
        logging.info("Database pool created successfully")
        return pool
    except Exception as e:
        logging.error(f"Failed to create database pool: {str(e)}")
        raise

async def init_db():
    async with db_pool.acquire() as conn:
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    name VARCHAR(255),
                    lang VARCHAR(10) DEFAULT 'en-uz'
                );

                CREATE TABLE IF NOT EXISTS translations (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    input_text TEXT,
                    translated_text TEXT,
                    lang VARCHAR(10),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id);
                CREATE INDEX IF NOT EXISTS idx_translations_user_id ON translations(user_id);
            """)
            logging.info("Database tables initialized")
        except Exception as e:
            logging.error(f"Failed to initialize database tables: {str(e)}")
            raise

async def load_user(user_id):
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", int(user_id))
        return dict(result) if result else None

async def save_user(user_id, username, name, lang="en-uz"):
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (user_id, username, name, lang)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE
            SET username = $2, name = $3, lang = $4
            """,
            int(user_id), username, name, lang
        )
        logging.info(f"User {user_id} saved with lang {lang}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or "Unknown"
    name = update.effective_user.first_name or "Unknown"
    await save_user(user_id, username, name)
    await update.message.reply_text(
        "Salom! Tarjima botiga xush kelibsiz. Tarjima qilinadigan matnni kiriting\n\n"
        "Tilni o'zgartirish uchun - /change_lang\n"
        "Tarixni ko'rish uchun - /history\n"
        "Yordam uchun - /help."
    )
    logging.info(f"User {user_id} started the bot")

async def user_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"Sizning Telegram ID: {user_id}")
    logging.info(f"User {user_id} requested their ID")

async def show_language_selection(update: Update):
    keyboard = [
        [InlineKeyboardButton("🇬🇧 Inglizcha - O'zbekcha 🇺🇿", callback_data='en-uz')],
        [InlineKeyboardButton("🇺🇿 O'zbekcha - Inglizcha 🇬🇧", callback_data='uz-en')],
        [InlineKeyboardButton("🇷🇺 Ruscha - O'zbekcha 🇺🇿", callback_data='ru-uz')],
        [InlineKeyboardButton("🇺🇿 O'zbekcha - Ruscha 🇷🇺", callback_data='uz-ru')],
        [InlineKeyboardButton("🇷🇺 Ruscha - Inglizcha 🇬🇧", callback_data='ru-en')],
        [InlineKeyboardButton("🇬🇧 Inglizcha - Ruscha 🇷🇺", callback_data='en-ru')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Tilni tanlang:", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    if query.data in ["en-uz", "uz-en", "ru-uz", "uz-ru", "ru-en", "en-ru"]:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET lang = $1 WHERE user_id = $2",
                query.data, int(user_id)
            )
        await query.edit_message_text(f"{query.data} tanlandi. Tarjima qilinadigan matnni kiriting:")
        logging.info(f"User {user_id} changed language to {query.data}")
    else:
        await query.edit_message_text("Noto'g'ri tanlov.")

async def change_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_language_selection(update)

async def translate_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = await load_user(user_id)
    current_lang = user.get("lang", "en-uz") if user else "en-uz"

    user_input = update.message.text
    try:
        lang_mapping = {
            "en-uz": "uz", "uz-en": "en", "ru-uz": "uz",
            "uz-ru": "ru", "ru-en": "en", "en-ru": "ru"
        }
        target_lang = lang_mapping.get(current_lang, "uz")
        tarjima = GoogleTranslator(source='auto', target=target_lang).translate(user_input)

        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO translations (user_id, input_text, translated_text, lang)
                VALUES ($1, $2, $3, $4)
                """,
                int(user_id), user_input, tarjima, current_lang
            )
        await update.message.reply_text(tarjima)
        logging.info(f"User {user_id} translated text: {user_input} -> {tarjima} ({current_lang})")
    except Exception as e:
        await update.message.reply_text(f"Tarjima qilishda xato yuz berdi: {str(e)}")
        logging.error(f"Translation error for user {user_id}: {str(e)}")

async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("Sizda bu buyruqni bajarish huquqi yo'q.")
        logging.warning(f"User {user_id} attempted /users without permission")
        return

    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT * FROM users")
        if not users:
            await update.message.reply_text("Foydalanuvchi yo'q.")
            return
        message = "Foydalanuvchilar:\n"
        for user in users:
            message += f"ID: {user['user_id']}, Username: @{user['username']}, Name: {user['name']}, Lang: {user['lang']}\n"
        await update.message.reply_text(message)
        logging.info(f"Admin {user_id} requested users list")

async def user_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    async with db_pool.acquire() as conn:
        history = await conn.fetch(
            """
            SELECT input_text, translated_text, created_at, lang
            FROM translations
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT 10
            """,
            int(user_id)
        )
        if not history:
            await update.message.reply_text("Tarjima tarixingiz yo'q.")
            logging.info(f"User {user_id} has no translation history")
            return
        message = "Tarjima tarixi:\n"
        for row in history:
            message += f"[{row['created_at']}]: {row['input_text']} -> {row['translated_text']} ({row['lang']})\n"
        await update.message.reply_text(message)
        logging.info(f"User {user_id} requested translation history")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("Sizda bu buyruqni bajarish huquqi yo'q.")
        logging.warning(f"User {user_id} attempted /stats without permission")
        return
    async with db_pool.acquire() as conn:
        stats = await conn.fetch("SELECT lang, COUNT(*) AS user_count FROM users GROUP BY lang")
        message = "Statistika:\n"
        for row in stats:
            message += f"{row['lang']}: {row['user_count']} foydalanuvchi\n"
        await update.message.reply_text(message or "Statistika yo'q.")
        logging.info(f"Admin {user_id} requested stats")

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Botni boshlash\n"
        "/user_id - ID olish\n"
        "/change_lang - Tilni o‘zgartirish\n"
        "/history - Tarjima tarixi\n"
        "/users - Foydalanuvchilar (admin)\n"
        "/stats - Statistika (admin)\n"
        "Yozgan matningiz tarjima qilinadi."
    )
    logging.info(f"User {update.effective_user.id} requested help")

async def main():
    global db_pool
    try:
        db_pool = await create_db_pool()
        await init_db()
        request = HTTPXRequest(
            connection_pool_size=10,
            http_version="1.1",
            read_timeout=30.0,
            write_timeout=30.0,
            pool_timeout=30.0
        )
        application = ApplicationBuilder().token(BOT_TOKEN).request(request).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("user_id", user_id_command))
        application.add_handler(CommandHandler("change_lang", change_language))
        application.add_handler(CommandHandler("users", users_list))
        application.add_handler(CommandHandler("history", user_history))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("help", help))
        application.add_handler(CallbackQueryHandler(button))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, translate_text))

        print("Bot ishga tushdi...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        logging.error(f"Bot crashed: {str(e)}")
        print(f"Xato: {str(e)}")
        raise
    finally:
        if db_pool:
            await db_pool.close()
            logging.info("Database pool closed")
        if 'application' in locals():
            await application.stop()
            await application.shutdown()

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        loop.run_until_complete(loop.shutdown_asyncgens())
    finally:
        loop.close()