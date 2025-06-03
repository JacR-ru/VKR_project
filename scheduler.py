import json
import subprocess
import time
import schedule
import os
import logging
import sys
from logging.handlers import RotatingFileHandler
from threading import Lock

# Привязка всех путей к директории, где лежит этот скрипт
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
AGENT_SCRIPT = os.path.join(BASE_DIR, 'ai-agent/ai_agent.py')

PARSER_PATHS = {
    'webparser': os.path.join(BASE_DIR, 'web_parser/webmain.py'),
    'GitHubparser': os.path.join(BASE_DIR, 'github_parser/ghmain.py'),
    'pastebinparser': os.path.join(BASE_DIR, 'paste_parser/pastemain.py'),
    'telegramparser': os.path.join(BASE_DIR, 'telegram/telegram_parser/tgmain.py')
}

run_lock = Lock()

# Логирование: файл + консоль
os.makedirs(os.path.join(BASE_DIR, 'logs'), exist_ok=True)
logger = logging.getLogger('scheduler')
logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler(os.path.join(BASE_DIR, 'logs/scheduler.log'), maxBytes=1_000_000, backupCount=3)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

logger.addHandler(file_handler)
logger.addHandler(console_handler)

def load_config():
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "frequency": "daily",
            "modules": []
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
        logger.warning("⚠ config.json не найден, создан с настройками по умолчанию.")
        return default_config

    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def run_script(script_path):
    try:
        logger.info(f"Запуск скрипта: {script_path}")
        subprocess.run(['python', script_path], check=True)
        logger.info(f"Успешно завершён: {script_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка при выполнении {script_path}: {e}")

def run_parsers():
    if run_lock.locked():
        logger.warning("Предыдущий запуск ещё не завершён. Новый запуск пропущен.")
        return

    with run_lock:
        logger.info("=== Запуск парсеров по расписанию ===")
        config = load_config()
        modules = config.get('modules', [])

        for name in modules:
            path = PARSER_PATHS.get(name)
            if not path or not os.path.isfile(path):
                logger.warning(f"Парсер '{name}' не найден по пути '{path}', пропускаем.")
                continue
            run_script(path)

        if os.path.isfile(AGENT_SCRIPT):
            logger.info(f"→ Запуск ИИ-агента")
            run_script(AGENT_SCRIPT)
        else:
            logger.warning(f"Агент не найден по пути '{AGENT_SCRIPT}'")

        logger.info("=== Завершено ===")

def setup_schedule(frequency):
    if frequency == 'hourly':
        schedule.every().hour.do(run_parsers)
    elif frequency == 'daily':
        schedule.every().day.at("00:00").do(run_parsers)
    elif frequency == 'weekly':
        schedule.every().monday.at("00:00").do(run_parsers)
    else:
        logger.warning(f"Неизвестная частота: {frequency}")

def main():
    logger.info(f"Аргументы запуска: {sys.argv}")

    config = load_config()
    frequency = config.get('frequency', 'daily')
    setup_schedule(frequency)

    if '--now' in sys.argv:
        logger.info("Ручной запуск через --now")
        run_parsers()

    logger.info(f"Служба запущена. Частота запуска: {frequency}")

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()