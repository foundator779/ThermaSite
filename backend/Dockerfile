FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY pyproject.toml .
COPY src ./src
RUN pip install --no-cache-dir .
RUN useradd --create-home terraforge && mkdir -p /app/.terraforge-data && chown -R terraforge /app
USER terraforge
CMD ["sh", "-c", "uvicorn terraforge.main:app --host 0.0.0.0 --port ${PORT}"]
