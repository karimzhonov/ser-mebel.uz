FROM python:3.10-slim

# Убираем интерактивные запросы
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Копируем только requirements.txt на этом этапе, чтобы использовать Docker-кеш
COPY requirements.txt .

# Создаем venv и устанавливаем зависимости
RUN pip install -r requirements.txt

# Копируем остальной код
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80", "--workers", "4"]