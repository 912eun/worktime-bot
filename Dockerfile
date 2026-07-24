FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 데이터(SQLite)는 영구 볼륨 /data 에 저장
ENV DATA_DIR=/data

CMD ["python", "bot.py"]
