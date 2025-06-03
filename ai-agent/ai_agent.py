import os
import json
import asyncio
import aiofiles
import psycopg2
from datetime import datetime
from tqdm.asyncio import tqdm
from dotenv import load_dotenv
import re
import hashlib
from datetime import timezone
from transformers import pipeline

# Загрузка конфигурации из .env
load_dotenv()

class Config:
    def __init__(self):
        self.DB_HOST = os.getenv('DB_HOST')
        self.DB_PORT = os.getenv('DB_PORT')
        self.DB_NAME = os.getenv('DB_NAME')
        self.DB_USER = os.getenv('DB_USER')
        self.DB_PASSWORD = os.getenv('DB_PASSWORD')

        required_vars = ['DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER', 'DB_PASSWORD']
        for var in required_vars:
            if getattr(self, var) is None:
                raise ValueError(f"Environment variable {var} is not set in .env")

    @staticmethod
    def get_output_dirs():
        script_dir = os.path.dirname(os.path.abspath(__file__))
        return {
            'PROCESSED_DIR': os.path.join(script_dir, 'processed'),
            'REVIEW_DIR': os.path.join(script_dir, 'to_review')
        }

config = Config()

# Инициализация DistilBERT
try:
    classifier = pipeline(
        "zero-shot-classification",
        model="distilbert-base-multilingual-cased",
        device=-1,
        batch_size=16
    )
    print("DistilBERT initialized successfully")
except Exception as e:
    print(f"Failed to initialize DistilBERT: {str(e)}")
    classifier = None

TRUSTED_SOURCES = {'gazeta.ru', 't.me/dataleak'}

def extract_text(entry):
    for field in ['content', 'snippet', 'title', 'description']:
        if field in entry and isinstance(entry[field], str) and len(entry[field].strip()) >= 5:
            return entry[field]
    print(f"Invalid entry: no valid text field found in {json.dumps(entry, ensure_ascii=False)}")
    return None

def determine_type_and_analysis(text, source):
    analysis = {
        "credentials": bool(re.search(r'\b(пароль|password|ключ|token|секрет|auth)\b', text, re.IGNORECASE)),
        "personal": bool(re.search(r'\b(почта|email|телефон|имя|фамилия|адрес|ФИО|СНИЛС|паспорт)\b', text, re.IGNORECASE)),
        "financial": bool(re.search(r'\b(карта|счёт|банковские|кредит|платёж|аккаунты)\b', text, re.IGNORECASE)),
        "health": bool(re.search(r'\b(здоровье|диагноз|лечение|больница|пациент)\b', text, re.IGNORECASE)),
        "intellectual_property": bool(re.search(r'\b(патент|авторское право|исходный код)\b', text, re.IGNORECASE)),
        "volume": bool(re.search(r'\b(\d+\s*(тыс\.|тысяч|млн|миллион|Гб|Gb))\b', text, re.IGNORECASE)),
        "leak": bool(re.search(r'\b(утечка|слив|хакер|взлом|leak|breach|доступ)\b', text, re.IGNORECASE))
    }

    # Расширенный паттерн для сервисов
    has_service = bool(re.search(r'\b(УК [А-Я][а-я]+(?: [А-Я][а-я]+)*|Газета\.Ru|Московский институт психоанализа|4Chan|Steam|ЦАМ|ПРАВОКАРД|[А-Я][а-я]+(?: [А-Я][а-я]+)*)\b', text))

    # Упрощённое условие утечки
    is_leak = analysis["leak"] or (has_service and any(analysis[key] for key in ["credentials", "personal", "financial", "health", "intellectual_property"]))

    # Исключение обобщённых утверждений
    if not has_service and analysis["volume"] and not any(analysis[key] for key in ["credentials", "personal", "financial", "health", "intellectual_property"]):
        is_leak = False
        analysis["leak"] = False

    # DistilBERT
    model_confidence = 0.5
    if classifier:
        try:
            result = classifier(text, candidate_labels=["утечка", "не утечка"], hypothesis_template="Этот текст указывает на {}.", multi_label=False)
            model_is_leak = result["labels"][0] == "утечка"
            model_confidence = result["scores"][0] if model_is_leak else 1 - result["scores"][0]
            print(f"DistilBERT: label={result['labels'][0]}, score={result['scores'][0]}")
        except Exception as e:
            print(f"DistilBERT failed: {str(e)}")

    # Confidence
    confidence = 0.9 if any(s in source.lower() for s in TRUSTED_SOURCES) else 0.7
    if is_leak or model_confidence > 0.7:
        confidence = min(confidence + 0.2, 1.0)
    if analysis["volume"]:
        confidence = min(confidence + 0.1, 1.0)
    confidence = (confidence + model_confidence) / 2
    print(f"Analysis: {analysis}, Confidence: {confidence}")

    # Тип утечки
    if analysis["credentials"]:
        leak_type = "Пароли"
    elif analysis["personal"]:
        leak_type = "Персональные данные"
    elif analysis["financial"]:
        leak_type = "Финансовые данные"
    elif analysis["health"]:
        leak_type = "Медицинские данные"
    elif analysis["intellectual_property"]:
        leak_type = "Интеллектуальная собственность"
    else:
        leak_type = "Прочие данные"

    analysis["leak"] = is_leak
    return leak_type, analysis, confidence

def extract_entities(text):
    geo_entities = re.findall(r'\b(Австралия|Санкт-Петербург|Москва|Россия)\b', text)
    org_entities = re.findall(r'\b(УК [А-Я][а-я]+(?: [А-Я][а-я]+)*|Газета\.Ru|Московский институт психоанализа|4Chan|Steam|ЦАМ|ПРАВОКАРД)\b', text)
    return list(set(geo_entities)), list(set(org_entities))

def generate_recommendations(analysis, leak_type, geo_entities, org_entities):
    recommendations = []
    if analysis["credentials"]:
        recommendations.extend([
            "Сменить пароли в скомпрометированных системах.",
            "Включить двухфакторную аутентификацию (2FA).",
            f"Проверить безопасность в {', '.join(org_entities) if org_entities else 'затронутых сервисах'}."
        ])
    if analysis["personal"]:
        recommendations.extend([
            f"Уведомить пользователей{' в ' + ', '.join(geo_entities) if geo_entities else ''} об утечке.",
            "Внедрить шифрование персональных данных.",
            "Проверить соответствие законам о защите данных."
        ])
    if analysis["financial"]:
        recommendations.extend([
            "Заблокировать скомпрометированные счета.",
            "Настроить мониторинг транзакций.",
            f"Связаться с банками{' в ' + ', '.join(geo_entities) if geo_entities else ''}."
        ])
    if analysis["health"]:
        recommendations.extend([
            "Уведомить регуляторов здравоохранения.",
            "Зашифровать медицинские данные.",
            "Обучить персонал защите данных."
        ])
    if analysis["intellectual_property"]:
        recommendations.extend([
            "Проверить права на интеллектуальную собственность.",
            "Ограничить доступ к конфиденциальным данным."
        ])
    if analysis["volume"]:
        recommendations.extend([
            "Масштабировать меры реагирования.",
            f"Увеличить ресурсы для анализа{' в ' + ', '.join(geo_entities) if geo_entities else ''}."
        ])
    if analysis["leak"]:
        recommendations.append("Расследовать источник утечки и усилить кибербезопасность.")
    if not recommendations:
        recommendations.append("Провести анализ для уточнения действий.")
    return recommendations

def load_parser_configs():
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Configuration file {config_file} not found")
    with open(config_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("config.json must be a list of parser configurations")
    for parser in data:
        if not isinstance(parser, dict) or 'id' not in parser or 'path' not in parser:
            raise ValueError("Each parser in config.json must have 'id' and 'path' keys")
    return data

def save_to_db(parser_id, entries):
    try:
        conn = psycopg2.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            dbname=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD
        )
        cursor = conn.cursor()
        for entry in entries:
            status = entry['status'] if entry['status'] in ['Новый', 'Подтверждён', 'Требует проверки'] else 'Новый'
            cursor.execute('''
                INSERT INTO incidents (type, source, status, description)
                VALUES (%s, %s, %s, %s)
            ''', (
                entry['type'],
                entry['source'],
                status,
                entry['description']
            ))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error saving to database: {str(e)}")
        raise

def is_valid_entry(entry):
    return extract_text(entry) is not None

def generate_message_id(text):
    return int(hashlib.md5(text.encode('utf-8')).hexdigest(), 16) % 1000000

async def process_single_file(file_path, parser_id):
    try:
        output_dirs = Config.get_output_dirs()
        os.makedirs(output_dirs['PROCESSED_DIR'], exist_ok=True)
        os.makedirs(output_dirs['REVIEW_DIR'], exist_ok=True)

        if not os.path.exists(file_path):
            print(f"File {file_path} does not exist")
            return []

        async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
            data = await f.read()
        
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON in {file_path}: {str(e)}")
            return []

        # Обработка разных структур
        entries = []
        if isinstance(data, list):
            entries = data
        elif isinstance(data, dict):
            entries = data.get('entries', []) or data.get('Утечки информации', [])
            if not entries:
                entries = [data] if extract_text(data) else []
        if not entries:
            print(f"File {file_path} does not contain a valid list of entries: {json.dumps(data, ensure_ascii=False)[:500]}")
            return []

        valid_entries = [entry for entry in entries if is_valid_entry(entry)]
        print(f"Found {len(valid_entries)} valid entries in {file_path}")
        if not valid_entries:
            return []

        processed_entries = []
        needs_review_entries = []
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")
        
        for entry in valid_entries:
            text = extract_text(entry)
            source = entry.get('url', entry.get('link', f"{parser_id}/{os.path.basename(file_path)}"))
            
            leak_type, analysis, confidence = determine_type_and_analysis(text, source)
            
            if not analysis["leak"] and confidence < 0.5:
                print(f"Skipping entry with low confidence: {text[:100]}...")
                continue

            status = "Подтверждён" if confidence >= 0.85 else "Требует проверки"

            geo_entities, org_entities = extract_entities(text)

            recommendations = generate_recommendations(analysis, leak_type, geo_entities, org_entities)

            description = (
                f"Content: {text}\n"
                f"Analysis: {json.dumps(analysis, ensure_ascii=False)}\n"
                f"Confidence: {confidence:.2f}\n"
                f"Entities: Geo: {', '.join(geo_entities) if geo_entities else 'None'}, Org: {', '.join(org_entities) if org_entities else 'None'}\n"
                f"Recommendations:\n" + "\n".join(f"- {rec}" for rec in recommendations)
            )

            link = source
            message_id = entry.get("message_id", generate_message_id(text))

            output_entry = {
                "date": timestamp,
                "message_id": message_id,
                "content": text,
                "link": link,
                "analysis": analysis,
                "recommendations": recommendations
            }

            db_entry = {
                "parser_id": parser_id,
                "source": link,
                "status": status,
                "type": leak_type,
                "description": description
            }

            if status == "Требует проверки":
                needs_review_entries.append((output_entry, db_entry))
            else:
                processed_entries.append((output_entry, db_entry))

        if processed_entries:
            processed_path = os.path.join(
                output_dirs['PROCESSED_DIR'],
                f"processed_{parser_id}_{os.path.basename(file_path)}"
            )
            async with aiofiles.open(processed_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps({
                    "source": file_path,
                    "timestamp": timestamp,
                    "entries": [entry[0] for entry in processed_entries]
                }, ensure_ascii=False, indent=2))
            save_to_db(parser_id, [entry[1] for entry in processed_entries])

        if needs_review_entries:
            review_path = os.path.join(
                output_dirs['REVIEW_DIR'],
                f"review_{parser_id}_{os.path.basename(file_path)}"
            )
            async with aiofiles.open(review_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps({
                    "source": file_path,
                    "timestamp": timestamp,
                    "entries": [entry[0] for entry in needs_review_entries]
                }, ensure_ascii=False, indent=2))
            save_to_db(parser_id, [entry[1] for entry in needs_review_entries])

        print(f"Processed {file_path}: {len(processed_entries)} confirmed, {len(needs_review_entries)} for review")
        return [entry[0] for entry in processed_entries + needs_review_entries]

    except Exception as e:
        print(f"Error processing {file_path}: {str(e)}")
        return []

async def process_parser(parser_config):
    parser_id = parser_config['id']
    file_path = parser_config['path']
    
    print(f"Обработка парсера {parser_id} ({file_path})...")
    results = await process_single_file(file_path, parser_id)
    print(f"Обработано {len(results)} записей для парсера {parser_id}")
    return results

async def main():
    parser_configs = load_parser_configs()
    all_results = []
    
    tasks = [process_parser(parser_config) for parser_config in parser_configs]
    for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Processing all parsers"):
        result = await f
        all_results.extend(result)

    print(f"Обработка завершена. Найдено {len(all_results)} подозрительных или подтверждённых утечек")
    return all_results

if __name__ == "__main__":
    print("Запуск обработки...")
    results = asyncio.run(main())
    print(f"Обработка завершена. Найдено {len(results)} записей. Данные сохранены в PostgreSQL и в diplom/ai-agent/processed, diplom/ai-agent/to_review.")