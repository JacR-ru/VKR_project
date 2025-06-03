import requests
from bs4 import BeautifulSoup
import re
import time
import random
import json
import yaml
from datetime import datetime
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / "config.yaml"
RESULTS_DIR = BASE_DIR / "paste_result"
PROCESSED_PATH = RESULTS_DIR / "processed_ids.json"
RESULTS_PATH = RESULTS_DIR / "paste_result.json"
STATUS_PATH = RESULTS_DIR / "status.json"

class PastebinMonitor:
    def __init__(self, config_path=None):
        if config_path is None:
            config_path = CONFIG_PATH
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.patterns = self.config["patterns"]
        self.whitelist = self.config["whitelist"]
        self.delay_range = tuple(self.config["delay_range"])
        self.threads = self.config.get("threads", 10)

        self.processed_ids = self.load_processed_ids()
        self.results = []

    def load_processed_ids(self):
        if not PROCESSED_PATH.exists():
            return set()
        with open(PROCESSED_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))

    def save_processed_ids(self):
        with open(PROCESSED_PATH, "w", encoding="utf-8") as f:
            json.dump(list(self.processed_ids), f, indent=2, ensure_ascii=False)

    def save_results(self):
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)

    def save_status(self, status, error=None):
        # Сохраняем статус в файл, включая ошибку, если есть
        status_data = {"status": status, "error": str(error) if error else ""}
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=2, ensure_ascii=False)

    def fetch_archive_links(self):
        paste_keys = set()
        url = "https://pastebin.com/archive"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                self.save_status("Произошла ошибка", f"Ошибка получения страницы: {response.status_code}")
                print(f"Произошла ошибка: Ошибка получения страницы: {response.status_code}")
                return []
            soup = BeautifulSoup(response.text, "html.parser")
            table = soup.find("table", {"class": "maintable"})
            if table:
                for row in table.find_all("tr")[1:]:
                    link = row.find("a")
                    if link and link.get("href"):
                        key = link["href"].strip("/")
                        if key:
                            paste_keys.add(key)
        except Exception as e:
            self.save_status("Произошла ошибка", e)
            print(f"Произошла ошибка: {e}")
        return list(paste_keys)

    def fetch_paste_content(self, paste_key):
        try:
            url = f"https://pastebin.com/raw/{paste_key}"
            response = requests.get(url, timeout=10)
            return response.text if response.status_code == 200 else None
        except Exception as e:
            print(f"Произошла ошибка при получении пасты {paste_key}: {e}")
            return None

    def extract_snippet(self, text):
        for pattern in self.patterns.values():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                start = max(match.start() - 50, 0)
                end = min(match.end() + 100, len(text))
                return text[start:end].strip()
        return text[:200].strip()

    def analyze_content(self, text):
        # Пропускаем текст, если он соответствует белому списку
        for pattern in self.whitelist:
            if re.search(pattern, text, re.IGNORECASE):
                return {}
        # Требуем минимум два совпадения для подтверждения утечки
        findings = {}
        match_count = 0
        for label, pattern in self.patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                findings[label] = True
                match_count += 1
            else:
                findings[label] = False
        return findings if match_count >= 2 else {}

    def process_entry(self, paste_key):
        if paste_key in self.processed_ids:
            return

        time.sleep(random.uniform(*self.delay_range))

        content = self.fetch_paste_content(paste_key)
        if not content:
            return

        analysis = self.analyze_content(content)
        if any(analysis.values()):
            result = {
                "url": f"https://pastebin.com/{paste_key}",
                "service": "pastebin.com",
                "title": "",
                "snippet": self.extract_snippet(content),
                "volume": "",
                "analysis": analysis,
                "timestamp": datetime.utcnow().isoformat()
            }
            self.results.append(result)
            print(f"Обнаружил утечки: {result['url']}")

        self.processed_ids.add(paste_key)

    def run(self):
        # Очищаем старый статус перед началом
        self.save_status("Начал работу")
        print("Начал работу")
        try:
            all_keys = self.fetch_archive_links()
            new_keys = [k for k in all_keys if k not in self.processed_ids]
            print(f"В процессе выполнения... Найдено {len(new_keys)} новых записей")

            if not new_keys:
                self.save_status("Не обнаружил утечек")
                print("Не обнаружил утечек")
                return

            with ThreadPoolExecutor(max_workers=self.threads) as executor:
                list(tqdm(executor.map(self.process_entry, new_keys), total=len(new_keys), desc="Обработка паст"))

            self.save_results()
            self.save_processed_ids()

            status = "Обнаружил утечки" if self.results else "Не обнаружил утечек"
            self.save_status(status)
            print(status)
            self.save_status("Закончил работу успешно")
            print("Закончил работу успешно")
        except Exception as e:
            self.save_status("Произошла ошибка", e)
            print(f"Произошла ошибка: {e}")

if __name__ == "__main__":
    monitor = PastebinMonitor()
    monitor.run()