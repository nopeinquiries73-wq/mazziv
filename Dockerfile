FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       7zip \
       libarchive-tools \
       unzip \
       unrar-free \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/runtime

CMD ["sh", "-c", "waitress-serve --host=0.0.0.0 --port=${PORT:-10000} app:app"]
