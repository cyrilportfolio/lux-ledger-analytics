# Pipeline image: build once, run against any ledger mounted on /app/data.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY data/ ./data/
COPY tests/ ./tests/
COPY pytest.ini ./

RUN useradd --create-home --uid 1000 ledger \
    && mkdir -p /app/output \
    && chown -R ledger:ledger /app
USER ledger

VOLUME ["/app/data", "/app/output"]

ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--journal", "data/journal_dirty.csv", "--faia"]
