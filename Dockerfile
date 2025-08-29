FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    IN_DIR=/data.zip \
    OUT_DIR=/out

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py /app/main.py

RUN mkdir -p /out

ENTRYPOINT ["python", "/app/main.py"]
