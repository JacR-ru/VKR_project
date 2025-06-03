import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telethon import TelegramClient
from telethon.tl.types import Channel

BASE_DIR     = Path(__file__).parent.resolve()
ENV_PATH     = BASE_DIR.parent.parent / '.env' 
CONFIG_PATH  = BASE_DIR.parent / 'config.json'

load_dotenv(dotenv_path=ENV_PATH)
API_ID    = int(os.getenv("API_ID", 0))
API_HASH  = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not (API_ID and API_HASH and BOT_TOKEN):
    raise ValueError("API_ID, API_HASH и BOT_TOKEN должны быть заданы в .env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

# Работаем со списком каналов
def load_config():
    if CONFIG_PATH.exists():
        j = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        # Если вдруг старый формат — приводим к новому
        if isinstance(j.get("channels"), dict):
            j["channels"] = list(j["channels"].keys())
        return j
    return {"channels": [], "request_delay": 1.0}

def save_config(cfg):
    # сохраняем только список + request_delay
    data = {
        "channels": cfg.get("channels", []),
        "request_delay": cfg.get("request_delay", 1.0)
    }
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

config = load_config()
client = TelegramClient(BASE_DIR / 'bot_session', API_ID, API_HASH)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет!\n"
        "/add @username_or_id — добавить канал\n"
        "/remove <username_or_id> — удалить канал\n"
        "/list — список каналов"
    )

async def add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Укажите @username или ID канала")
    ident = ctx.args[0]
    try:
        await client.start()
        entity = await client.get_entity(ident)
        if not isinstance(entity, Channel):
            return await update.message.reply_text("Это не канал")
        key = f"@{entity.username}" if entity.username else str(entity.id)
        if key in config["channels"]:
            return await update.message.reply_text("Канал уже в списке")
        config["channels"].append(key)
        save_config(config)
        await update.message.reply_text(f"Добавлен: {entity.title} ({key})")
    except Exception as e:
        logger.error("Ошибка добавления", exc_info=True)
        await update.message.reply_text(f"Ошибка: {e}")

async def remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Укажите @username или ID канала")
    key = ctx.args[0]
    if key.startswith("@") is False and key.isdigit():
        key = key  # остаётся числовой ID в строке
    if key not in config["channels"]:
        return await update.message.reply_text("Такого канала нет в списке")
    config["channels"].remove(key)
    save_config(config)
    await update.message.reply_text(f"Удалён: {key}")

async def list_channels(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not config["channels"]:
        return await update.message.reply_text("Список пуст")
    lines = []
    await client.start()
    for key in config["channels"]:
        try:
            ent = await client.get_entity(key)
            lines.append(f"{ent.title} ({key})")
        except:
            lines.append(key)
    await update.message.reply_text("Каналы:\n" + "\n".join(lines))

# Запуск
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_channels))
    logger.info("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()