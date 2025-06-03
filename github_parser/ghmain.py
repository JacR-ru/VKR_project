import requests
from bs4 import BeautifulSoup
import re
import time
import json
import yaml
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / "config.yaml"
RESULTS_DIR = BASE_DIR / "github_parser_result"
PROCESSED_PATH = RESULTS_DIR / "processed_links.txt"

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_processed_links():
    if not PROCESSED_PATH.exists():
        return set()
    with open(PROCESSED_PATH, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_processed_link(url):
    with open(PROCESSED_PATH, "a", encoding="utf-8") as f:
        f.write(url + "\n")

def analyze_content(text, regex_config):
    analysis = {key: False for key in regex_config}
    for key, pattern in regex_config.items():
        if re.search(pattern, text, re.MULTILINE):
            analysis[key] = True
    analysis["volume"] = False
    analysis["leak"] = any(analysis.values())
    return analysis

def scrape_github(config, processed_links, headers):
    print("В процессе выполнения...")
    results = []
    base_url = "https://github.com"

    for query in config["queries"]:
        for page in range(1, config["max_pages"] + 1):
            search_url = f"https://github.com/search?q={query.replace(' ', '+')}&type=code&p={page}"
            print(f"Fetching: {search_url}")
            try:
                resp = requests.get(search_url, headers=headers)
                soup = BeautifulSoup(resp.text, "html.parser")
                code_links = soup.select("a.v-align-middle")

                for link in code_links:
                    file_path = base_url + link['href']
                    if file_path in processed_links:
                        print(f"Пропущено (уже обработано): {file_path}")
                        continue

                    raw_url = file_path.replace("/blob/", "/raw/")
                    try:
                        raw_resp = requests.get(raw_url, headers=headers)
                        if raw_resp.status_code != 200:
                            continue

                        content = raw_resp.text
                        analysis = analyze_content(content, config["regex_patterns"])
                        if not analysis["leak"]:
                            continue

                        snippet = content.strip().split("\n")[0][:200]
                        result = {
                            "url": file_path,
                            "service": "github.com",
                            "title": link['href'],
                            "snippet": snippet,
                            "volume": "",
                            "analysis": analysis,
                            "timestamp": datetime.utcnow().isoformat()
                        }

                        results.append(result)
                        save_processed_link(file_path)
                        time.sleep(config["delay_between_requests"])
                    except Exception as e:
                        print(f"Ошибка при анализе файла: {e}")
                time.sleep(config["delay_between_pages"])
            except Exception as e:
                print(f"Ошибка при обработке страницы поиска: {e}")
    return results

def save_results(new_results, output_path):
    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = []

    all_results = existing + new_results
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

def ensure_dirs():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

def main():
    print("Начал работу")
    ensure_dirs()
    try:
        config = load_config()
        headers = config.get("headers", {"User-Agent": "Mozilla/5.0"})
        processed_links = load_processed_links()
        output_path = RESULTS_DIR / config.get("output_file", "github_leaks.json")

        new_results = scrape_github(config, processed_links, headers)
        save_results(new_results, output_path)
        status = "Обнаружил утечки" if new_results else "Не обнаружил утечек"
        print(status)
        print("Закончил работу успешно")
    except Exception as e:
        print(f"Произошла ошибка: {e}")

if __name__ == "__main__":
    main()