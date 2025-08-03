FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY poetry.lock ./

RUN pip install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --only main --no-interaction --no-ansi --no-root

COPY . .

RUN mkdir -p templates || true

EXPOSE 8000

ENV PYTHONPATH=/app
ENV PORT=8000

CMD ["python", "app.py"] 