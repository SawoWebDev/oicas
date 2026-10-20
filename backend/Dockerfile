FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

ARG INSTALL_DEV=false
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt && if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; fi

COPY . .

RUN useradd --create-home --uid 1000 oicas && mkdir -p /app/data/exports && chown -R oicas /app/data
USER oicas

EXPOSE 8000
CMD ["sh", "-c", "python -m oicas.cli prepare-db && alembic upgrade head && python -m oicas.cli seed && uvicorn oicas.web.app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
