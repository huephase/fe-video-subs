FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fontconfig \
    fonts-noto-core \
    fonts-noto-extra \
    fonts-noto-ui-core \
    fonts-noto-color-emoji \
    fonts-dejavu-core \
    libfribidi0 \
    libharfbuzz0b \
    ca-certificates \
    curl \
    && fc-cache -f -v \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

