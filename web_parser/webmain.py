import json
import re
import time
import random
from urllib.parse import urlparse
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from googlesearch import search
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tqdm import tqdm

BASE_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / "config.yaml"
RESULTS_DIR = BASE_DIR / "leak_parser_result"
PROCESSED_PATH = RESULTS_DIR / "processed_urls.json"
RESULTS_PATH = RESULTS_DIR / "results.json"
STATUS_PATH = RESULTS_DIR / "status.json"

class LeakParser:
    def __init__(self):
        self.load_config()
        self.processed_urls = self.load_processed_urls()
        self.results = []
        self.validate_config()

    def validate_config(self):
        # Проверяем наличие всех необходимых ключей в конфиге
        required_keys = {
            "keywords", "site_filters", "target_domains",
            "search", "analysis", "crawling", "user_agents"
        }
        if not all(key in self.config for key in required_keys):
            raise ValueError("Invalid config structure")

    def load_config(self):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

    def load_processed_urls(self):
        try:
            if PROCESSED_PATH.exists():
                with open(PROCESSED_PATH, "r", encoding="utf-8") as f:
                    return set(json.load(f))
            return set()
        except Exception as e:
            print(f"Произошла ошибка при загрузке обработанных URL: {e}")
            return set()

    def save_processed_urls(self):
        with open(PROCESSED_PATH, "w", encoding="utf-8") as f:
            json.dump(list(self.processed_urls), f, indent=2, ensure_ascii=False)

    def save_status(self, status, error=None):
        # Сохраняем текущий статус и ошибку (если есть) в файл
        status_data = {"status": status, "error": str(error) if error else ""}
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=2, ensure_ascii=False)

    def generate_search_queries(self):
        # Формируем запросы с фильтром по дате (последние 6 месяцев)
        six_months_ago = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
        date_filter = f"after:{six_months_ago}"
        return [
            f"{keyword} {site} {date_filter}"
            for keyword in self.config["keywords"]
            for site in self.config["site_filters"]
        ]

    def is_relevant_domain(self, url):
        parsed = urlparse(url)
        return any(parsed.netloc.endswith(d) for d in self.config["target_domains"])

    def search_leak_references(self):
        found_urls = set()
        for query in self.generate_search_queries():
            try:
                print(f"Поиск по запросу: {query}")
                time.sleep(random.uniform(*self.config["search"]["delay_range"]))
                urls = search(
                    query,
                    num_results=self.config["search"]["results_per_query"],
                    lang="ru"
                )
                for url in urls:
                    if self.is_relevant_domain(url) and url not in self.processed_urls:
                        found_urls.add(url)
                        print(f"Найден кандидат: {url}")
            except Exception as e:
                self.save_status("Произошла ошибка", f"Ошибка поиска: {e}")
                print(f"Произошла ошибка: Ошибка поиска: {e}")
                time.sleep(60)
        return found_urls

    def analyze_content(self, text):
        # Проверяем текст на наличие признаков утечек по заданным шаблонам
        patterns = {
            "credentials": r"\b(парол[ей]+|логин[а-я]*)\b",
            "personal": r"\b(паспорт|снилс|телефон|адрес|email)\b",
            "financial": r"\b(карт[а-я]+|счет[а-я]*|банк[а-я]*)\b",
            "health": r"\b(медицинск[а-я]+|диагноз|медикамент)\b",
            "intellectual_property": r"\b(патент|торговая марка|искусство|код)\b",
            "volume": r"\b\d{1,3}([\s,]\d{3})*(\.|,)?\d*\s?(GB|MB|TB|тыс\.|млн\.|запися[йи])\b",
            "leak": r"\b(утечк[а-я]+|слив|кража|компрометация)\b"
        }
        return {k: bool(re.search(p, text, re.I)) for k, p in patterns.items()}

    def filter_results(self, analysis):
        # Требуем совпадение хотя бы одного из ключевых триггеров
        return any(analysis.get(t, False) for t in self.config["analysis"]["required_triggers"])

    def extract_details(self, text, url):
        service = urlparse(url).netloc
        match = re.search(r"([^.]{0,200}(утечк[а-я]+|слив|кража)[^.]{0,200}\.)", text, re.I)
        snippet = match.group(1).strip() if match else text[:200]
        volume_match = re.search(r"\b\d{1,3}([\s,]\d{3})*(\.|,)?\d*\s?(GB|MB|TB|тыс\.|млн\.|запися[йи])\b", text, re.I)
        volume = volume_match.group(0) if volume_match else ""
        return service, snippet, volume

    def process_page(self, url):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": random.choice(self.config["user_agents"])},
                timeout=self.config["crawling"]["timeout"]
            )
            soup = BeautifulSoup(response.text, "lxml")
            for element in soup(["script", "style", "nav", "footer", "header"]):
                element.decompose()
            text = " ".join(soup.stripped_strings)
            analysis = self.analyze_content(text)
            if self.filter_results(analysis):
                service, snippet, volume = self.extract_details(text, url)
                result = {
                    "url": url,
                    "service": service,
                    "title": soup.title.text.strip() if soup.title else "",
                    "snippet": snippet,
                    "volume": volume,
                    "analysis": analysis,
                    "timestamp": datetime.now().isoformat()
                }
                self.results.append(result)
                print(f"Обнаружил утечки: {url}")
            self.processed_urls.add(url)
        except Exception as e:
            print(f"Произошла ошибка при обработке {url}: {e}")

    def save_results(self):
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)

    def run(self):
        # Очищаем старый статус перед началом
        self.save_status("Начал работу")
        print("Начал работу")
        try:
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            new_urls = self.search_leak_references()
            print(f"В процессе выполнения... Найдено {len(new_urls)} потенциальных утечек")

            if not new_urls:
                self.save_status("Не обнаружил утечек")
                print("Не обнаружил утечек")
                return

            threads = self.config["crawling"].get("threads", 5)
            with ThreadPoolExecutor(max_workers=threads) as executor:
                futures = {executor.submit(self.process_page, url): url for url in new_urls}
                for idx, future in enumerate(tqdm(as_completed(futures), total=len(futures), desc="Обработка утечек")):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"Произошла ошибка в потоке: {e}")
                    if (idx + 1) % 10 == 0:
                        self.save_results()
                        self.save_processed_urls()

            self.save_results()
            self.save_processed_urls()
            status = "Обнаружил утечки" if self.results else "Не обнаружил утечек"
            self.save_status(status)
            print(status)
            self.save_status("Закончил работу успешно")
            print("Закончил работу успешно")
        except Exception as e:
            self.save_status("Произошла ошибка", e)
            print(f"Произошла ошибка: {e}")

if __name__ == "__main__":
    parser = LeakParser()
    parser.run()