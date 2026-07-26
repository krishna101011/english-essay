# Reference Dockerfile for deploying to Fly.io (or Railway/Render, which
# also build from a Dockerfile). Not built or pushed by this repo — this is
# a template for you to build and deploy yourself with `fly deploy`.
#
# Includes a JRE for LanguageTool (see app/grammar/checker.py), which the
# brief requires to be present at runtime.

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV APP_ENV=production
EXPOSE 8000

# Run migrations then start the server. Fly's volumes mount before the app
# starts, so this is safe to run on every boot (alembic upgrade is
# idempotent against an already-migrated database).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
