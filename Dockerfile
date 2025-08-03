FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml poetry.lock ./

RUN pip install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-dev --no-interaction --no-ansi

COPY . .

RUN mkdir -p templates

EXPOSE 8000

ENV PYTHONPATH=/app
ENV PORT=8000

CMD ["poetry", "run", "python", "app.py"] 