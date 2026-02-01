"""
Десктопное приложение для составления расписания
Запускается как нативное окно (не в браузере)

Установка: pip install pywebview
Запуск: python run_desktop.py
"""

import webview
import threading
import sys
import os

# Добавляем путь к модулю
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_flask():
    """Запуск Flask-сервера в фоновом режиме"""
    from app import app
    # Отключаем reloader чтобы избежать двойного запуска
    app.run(debug=False, host='127.0.0.1', port=5000, use_reloader=False, threaded=True)


def main():
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Даём Flask время на запуск
    import time
    time.sleep(1)

    # Создаём нативное окно
    window = webview.create_window(
        title='Генератор расписания - Школа Покровский квартал',
        url='http://127.0.0.1:5000',
        width=1400,
        height=900,
        resizable=True,
        min_size=(1000, 700),
        confirm_close=True,  # Подтверждение при закрытии
        text_select=True     # Разрешить выделение текста
    )

    # Запускаем GUI
    webview.start(
        debug=False,
        gui='edgechromium'  # На Windows использует Edge WebView2 (современный)
        # Альтернативы: 'cef', 'qt', 'gtk' (для Linux/macOS)
    )


if __name__ == '__main__':
    print("=" * 60)
    print("  Генератор расписания - Школа Покровский квартал")
    print("  Десктопное приложение")
    print("=" * 60)
    print("\n  Запуск...")

    main()
