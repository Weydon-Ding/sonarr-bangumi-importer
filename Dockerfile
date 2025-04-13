# Dockerfile
FROM python:3.13-alpine

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# 持久化数据存储
VOLUME /data

CMD ["python", "sonarr_bangumi_importer.py"]