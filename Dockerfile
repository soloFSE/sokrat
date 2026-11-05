FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    DB_PATH=/data/sokrat.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py russian_trusted_ca.pem ./
COPY static ./static

# База учеников хранится в томе /data, чтобы переживать пересборку контейнера
VOLUME /data
EXPOSE 8000
CMD ["python", "main.py"]
