import tkinter as tk
from tkinter import scrolledtext
import subprocess
import os
import signal
import time
import threading

class ServerManager:
    def __init__(self, root):
        self.root = root
        self.root.title("Управление сервером Node.js")
        self.root.geometry("450x350")

        self.server_process = None

        # Кнопки
        self.start_button = tk.Button(root, text="Запустить сервер", command=self.start_server)
        self.start_button.pack(pady=10)

        self.stop_button = tk.Button(root, text="Остановить сервер", command=self.stop_server)
        self.stop_button.pack(pady=10)

        # Поле для логов
        self.log_area = scrolledtext.ScrolledText(root, height=12, width=50)
        self.log_area.pack(pady=10)

        # Лог по умолчанию
        self.log("Готов к управлению сервером.")

        # Пути
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.server_path = os.path.join(self.script_dir, "server.js")
        self.env_path = os.path.join(self.script_dir, ".env")

    def log(self, message):
        self.log_area.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {message}\n")
        self.log_area.see(tk.END)

    def start_server(self):
        if self.server_process:
            self.log("Сервер уже запущен!")
            return

        if not os.path.exists(self.server_path):
            self.log("Ошибка: файл server.js не найден.")
            return

        if not os.path.exists(self.env_path):
            self.log("Внимание: файл .env не найден. Продолжение без переменных окружения.")

        try:
            env = os.environ.copy()
            if os.path.exists(self.env_path):
                with open(self.env_path) as f:
                    for line in f:
                        if '=' in line:
                            key, value = line.strip().split('=', 1)
                            env[key] = value

            self.server_process = subprocess.Popen(
                ["node", self.server_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )
            self.log(f"Сервер запущен, PID: {self.server_process.pid}")
            print("Сервер запущен на http://localhost:3001")

            def read_output():
                while True:
                    if self.server_process.poll() is not None:
                        break
                    output = self.server_process.stdout.readline()
                    if output:
                        self.log(output.strip())
                    error = self.server_process.stderr.readline()
                    if error:
                        self.log(f"Ошибка: {error.strip()}")
                self.log(f"Сервер остановлен с кодом: {self.server_process.returncode}")
                self.server_process = None

            threading.Thread(target=read_output, daemon=True).start()

        except Exception as e:
            self.log(f"Ошибка при запуске сервера: {str(e)}")
            self.server_process = None

    def stop_server(self):
        if not self.server_process:
            self.log("Сервер не запущен!")
            return

        try:
            if os.name == 'nt':
                os.kill(self.server_process.pid, signal.CTRL_C_EVENT)
            else:
                self.server_process.terminate()
            self.log("Отправлен сигнал на остановку сервера...")
        except Exception as e:
            self.log(f"Ошибка при остановке сервера: {str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = ServerManager(root)
    root.mainloop()