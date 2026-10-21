# Умный Шопинг — веб-оболочка (Django Templates + Bootstrap)

Базовый каркас для работы над frontend-частью. Бизнес-логики и БД пока нет:
проект отдаёт HTML-шаблоны и статику.

## Быстрый старт

Требуется Python 3.10 или новее.

```bash
git clone <ссылка-на-репозиторий>
cd smart-shopping-web

python -m venv venv
# Windows (PowerShell):  venv\Scripts\Activate.ps1
# Windows (cmd):         venv\Scripts\activate.bat
# macOS / Linux:         source venv/bin/activate

pip install -r requirements.txt
python manage.py runserver
```

Откройте в браузере:

- http://127.0.0.1:8000/ — главная страница (поиск)
- http://127.0.0.1:8000/results/ — дашборд (таблица сравнения)

Проверка, что всё работает: `python manage.py test`.

## Структура

```
manage.py
config/            настройки проекта (settings.py, urls.py)
core/              приложение с заглушками views и urls
templates/         HTML-разметка (base.html, index.html, results.html)
static/
  css/             стили
  js/              локальные скрипты
  img/             картинки
```

## Для frontend-разработчика

- Работайте в папках `templates/` и `static/` (`css/`, `js/`, `img/`).
- Файлы `templates/base.html`, `index.html`, `results.html` — временные заглушки, замените их своими.
- В шаблонах подключайте статику так: `{% load static %}` и `{% static 'css/style.css' %}`.
- Изменения в шаблонах и статике видны сразу после обновления страницы, перезапуск сервера не нужен.
- Новые страницы добавляйте через backend-разработчиков (нужны маршрут в `core/urls.py` и view в `core/views.py`).

## Git-процесс

- Не коммитьте `venv/`, `.env`, `db.sqlite3` — они в `.gitignore`.

## Переменные окружения (необязательно)

См. `.env.example`: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`.
Значения по умолчанию подходят для локальной разработки.
