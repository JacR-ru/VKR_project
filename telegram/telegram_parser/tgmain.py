import os
import re
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import ChannelPrivateError, ChannelInvalidError

BASE_DIR = Path(__file__).parent.resolve()
ENV_PATH = BASE_DIR.parent.parent / '.env'
CONFIG_PATH = BASE_DIR.parent / 'config.json'
RESULTS_PATH = BASE_DIR / 'telegram_parser_result' / 'leaks_telegram.json'
STATUS_PATH = BASE_DIR / 'telegram_parser_result' / 'status.json'

load_dotenv(dotenv_path=ENV_PATH)

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
PHONE = os.getenv("PHONE", "")
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", 1.0))

if not (API_ID and API_HASH and PHONE):
    raise RuntimeError("В .env должны быть заданы API_ID, API_HASH и PHONE")

def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    return {"channels": [], "threads": [], "request_delay": REQUEST_DELAY}

def load_results():
    if RESULTS_PATH.exists():
        content = RESULTS_PATH.read_text(encoding='utf-8').strip()
        if content:
            return json.loads(content)
    return {"Утечки информации": []}

def save_results(results):
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')

def save_status(status=None, result=None, error=None, reset=False):
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if reset or not STATUS_PATH.exists():
        data = {"status": "Ожидает запуска", "result": "", "errors": []}
    else:
        data = json.loads(STATUS_PATH.read_text(encoding='utf-8'))

    if status:
        data["status"] = status
    if result is not None:
        data["result"] = result
    if error:
        data.setdefault("errors", []).append(error)
    if reset:
        data["errors"] = []

    STATUS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def analyze_content(text):
    patterns = {
        'credentials': r'\b(парол[ей]+|логин[а-я]*|хешированн[ыо][йе]|учётн[ыо][йе]\sзапис[ий]|токены)\b',
        'personal': r'\b(паспорт|снилс|телефон[ы]?|адрес[а]?|email|фамилия|ФИО|дата рождения)\b',
        'financial': r'\b(карт[а-я]+|счет[а-я]*|банк[а-я]*|оплаты|суммы)\b',
        'health': r'\b(медицинск[а-я]+|диагноз|медикамент|анализ[ы]?|здоровь[ея])\b',
        'intellectual_property': r'\b(патент|торговая марка|искусство|код)\b',
        'volume': r'\b(\d{1,3}([\s,]\d{3})*(\.|,)?\d*\s?(GB|MB|TB|тыс\.|млн\.|запис[йи]|строк[и]?))\b',
        'leak': r'\b(утечк[а-я]+|слив|слили|кража|компрометация|хакер[а-я]*|взлом|leak|breach|скомпрометированн[ыо][йе]|база данных|Firebase)\b'
    }
    analysis = {k: bool(re.search(p, text, re.IGNORECASE)) for k, p in patterns.items()}
    
    # Проверка на сервис
    service_pattern = r'\b(УК [А-Я][а-я]+(?: [А-Я][а-я]+)*|4Chan|Московский институт психоанализа|ЦАМ|ПРАВОКАРД|Steam|[А-Я][а-я]+(?: [А-Я][а-я]+)*|aviamed\.ru)\b'
    analysis['has_service'] = bool(re.search(service_pattern, text, re.IGNORECASE))
    
    # Проверка на СНГ
    cis_countries = [
        'Россия', 'Беларусь', 'Украина', 'Казахстан', 'Узбекистан', 'Кыргызстан',
        'Таджикистан', 'Туркменистан', 'Армения', 'Азербайджан', 'Грузия', 'Молдова', 'СНГ'
    ]
    cis_pattern = r'\b(' + '|'.join(cis_countries) + r')\b'
    country_match = re.search(r'Страна:\s*([^\n.]+)', text, re.IGNORECASE)
    country = country_match.group(1).strip() if country_match else ''
    is_cis = (
        bool(re.search(cis_pattern, text, re.IGNORECASE)) or
        country in cis_countries or
        bool(re.search(r'\.ru\b', text, re.IGNORECASE)) or
        bool(re.search(r'\b(медицинский центр|Санкт-Петербург|Москва)\b', text, re.IGNORECASE))
    )
    analysis['is_cis'] = is_cis
    analysis['country'] = country if country else ('Россия' if is_cis else 'Не указано')
    
    return analysis

def filter_results(analysis):
    is_leak = (analysis['leak'] or (
        analysis['has_service'] and any(analysis.get(k, False) for k in [
            'credentials', 'personal', 'financial', 'health', 'intellectual_property'
        ])
    )) and analysis['is_cis']
    
    if not analysis['has_service'] and analysis['volume'] and not any(
        analysis.get(k, False) for k in ['credentials', 'personal', 'financial', 'health', 'intellectual_property']
    ):
        is_leak = False
    
    return is_leak

async def handle_message(message, thread_id=None):
    content = getattr(message, 'raw_text', '') or getattr(message, 'message', '')
    if not content:
        return

    if thread_id and message.reply_to_msg_id != thread_id and message.id != thread_id:
        return

    analysis = analyze_content(content)
    if not filter_results(analysis):
        return  # Silently skip non-CIS or non-leak messages

    chat_id = getattr(message, 'chat_id', None) or message.peer_id.channel_id
    entity = await client.get_entity(chat_id)
    username = getattr(entity, 'username', None)
    link = f"https://t.me/{username}/{message.id}" if username else f"https://t.me/c/{chat_id}/{message.id}"

    entry = {
        "date": message.date.isoformat(),
        "message_id": message.id,
        "content": content[:500],
        "link": link,
        "analysis": analysis,
        "country": analysis['country']
    }

    results["Утечки информации"].append(entry)
    save_results(results)
    print(f"⚠️ Утечка (СНГ): {link}")

async def scan_history(entity, days=30, thread_id=None):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    name = entity.title or str(entity.id)
    print(f"Сканируем последние {days} дней для «{name}» с {cutoff.date()}" + (f" (ветка {thread_id})" if thread_id else ""))

    try:
        if thread_id:
            async for message in client.iter_messages(entity, reply_to=thread_id):
                if message.date < cutoff:
                    continue
                await handle_message(message, thread_id=thread_id)
                await asyncio.sleep(REQUEST_DELAY)
        else:
            async for message in client.iter_messages(entity, reverse=True):
                if message.date < cutoff:
                    continue
                await handle_message(message)
                await asyncio.sleep(REQUEST_DELAY)
    except (ChannelPrivateError, ChannelInvalidError) as e:
        err_msg = f"Ошибка доступа к каналу {name}: {e} (возможно, канал приватный)"
        print(err_msg)
        save_status(error=err_msg)

async def main(manual_trigger=False):
    save_status(status="Начал работу", result="", reset=True)
    print("Старт парсинга")

    if not config.get('channels') and not config.get('threads'):
        warning_msg = "Нет каналов или веток в config.json — нечего сканировать."
        print(warning_msg)
        save_status(status="Завершено", result=warning_msg)
        return

    try:
        await client.connect()
        if not await client.is_user_authorized():
            await client.send_code_request(PHONE)
            code = input("Введите код из Telegram: ")
            await client.sign_in(PHONE, code)

        entities = []
        for key in config.get("channels", []):
            try:
                ent = await client.get_entity(key)
                entities.append((ent, None))
            except (ChannelPrivateError, ChannelInvalidError) as e:
                err_msg = f"Не удалось получить данные канала {key}: {e} (возможно, канал приватный)"
                print(err_msg)
                save_status(error=err_msg)
            except Exception as e:
                err_msg = f"Не удалось получить данные канала {key}: {e}"
                print(err_msg)
                save_status(error=err_msg)

        for thread in config.get("threads", []):
            try:
                channel = thread.get("channel")
                thread_id = thread.get("thread_id")
                if not channel or not thread_id:
                    raise ValueError("В threads должны быть указаны channel и thread_id")
                ent = await client.get_entity(channel)
                entities.append((ent, thread_id))
            except (ChannelPrivateError, ChannelInvalidError) as e:
                err_msg = f"Не удалось получить данные канала {channel}: {e} (возможно, канал приватный)"
                print(err_msg)
                save_status(error=err_msg)
            except Exception as e:
                err_msg = f"Не удалось обработать ветку {thread}: {e}"
                print(err_msg)
                save_status(error=err_msg)

        if not entities:
            warning_msg = "Нет доступных каналов или веток для обработки."
            print(warning_msg)
            save_status(status="Завершено", result=warning_msg)
            return

        leaks_found = False
        for ent, thread_id in entities:
            await scan_history(ent, days=30, thread_id=thread_id)
            if results["Утечки информации"]:
                leaks_found = True

        result_msg = "Обнаружены утечки" if leaks_found else "Утечек не найдено"
        save_status(status="Завершено", result=result_msg)
        print(result_msg)

        save_status(status="Live-мониторинг запущен")
        print("Live-мониторинг запущен")

        @client.on(events.NewMessage(chats=[ent for ent, _ in entities]))
        async def live_handler(event):
            thread_id = next((tid for ent, tid in entities if ent.id == event.message.peer_id.channel_id and tid), None)
            await handle_message(event.message, thread_id=thread_id)

        await client.run_until_disconnected()

    except Exception as e:
        err_msg = f"Ошибка в работе: {e}"
        print(err_msg)
        save_status(error=err_msg, status="Завершено")

config = load_config()
results = load_results()

client = TelegramClient(BASE_DIR / 'parser_session', API_ID, API_HASH)

if __name__ == "__main__":
    asyncio.run(main())