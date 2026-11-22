# Imagen del HR Assistant: Python 3.12 slim y un usuario sin privilegios
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# Usuario que no es root: el proceso no necesita privilegios
RUN useradd --create-home --uid 10001 appuser

# Primero las dependencias, para aprovechar la caché de capas
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

USER appuser

# Render entrega el puerto en PORT; por omisión 8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
