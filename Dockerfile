FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY source_api.py demo.html connect_redis.py caching.py ./
COPY bench/ bench/

# lắng nghe 0.0.0.0 để truy cập được từ ngoài container; cổng do docker-compose.yml đặt
CMD ["uvicorn", "source_api:app", "--host", "0.0.0.0", "--port", "3000", "--no-access-log"]
