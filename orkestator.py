#!/usr/bin/env python3
import os
import sys
import subprocess
import signal

# Конфигурация: список сервисов с командами и рабочими директориями
SERVICES = [
    ("tg_parser", ["python", "tgmain.py"], "diplom/telegram/telegram_parser"),
    ("paste_parser", ["python", "paste_parser.py"], "diplom/paste_parser"),
    ("github_parser", ["python", "gh_parser.py"], "diplom/github_parser"),
    ("web_parser", ["python", "web_parser.py"], "diplom/web_parser"),
]

def run_services_sequentially():
    for name, cmd, cwd in SERVICES:
        print(f"[оркестратор] Запуск {name}…")
        try:
            # Запускаем процесс в нужной директории
            process = subprocess.Popen(cmd, cwd=cwd)
            process.wait()  # Ждём завершения
            exit_code = process.returncode

            print(f"[оркестратор] {name} завершился с кодом {exit_code}")
            if exit_code != 0:
                print(f"[оркестратор] {name} завершился с ошибкой, переходим к следующему.")
                break
        except KeyboardInterrupt:
            print(f"\n[оркестратор] Прерывание во время выполнения {name}. Завершение работы.")
            break
        except Exception as e:
            print(f"[оркестратор] Ошибка при запуске {name}: {e}")
            break

if __name__ == "__main__":
    run_services_sequentially()