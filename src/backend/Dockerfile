# Forge backend image (ADR-009: one artifact set for local, evaluator, and cloud).
FROM python:3.12-slim

# Faster, quieter, log-friendly Python in containers.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# psycopg[binary] ships wheels, so no libpq/compiler layer is needed.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

# Migrations and operational scripts travel with the image: the same artifact
# that serves traffic can run `alembic upgrade head` and seed.
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts

# Run unprivileged.
RUN useradd --create-home --uid 10001 forge
USER forge

EXPOSE 8000

# Migrations are a deliberate, separate step — never implicit on boot.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
