# Imagen del HR Assistant para Render (spec/04-production.md, punto 5).
FROM python:3.12-slim

# Sin archivos .pyc, log sin búfer (una línea JSON por evento) y sin caché de pip.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/hr-assistant

# Usuario sin privilegios: el proceso nunca corre como root.
RUN useradd --create-home --uid 10001 appuser

# Dependencias primero, para que la capa se reutilice si solo cambia el código.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Solo lo que la aplicación necesita en tiempo de ejecución.
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser data ./data

USER appuser

EXPOSE 8000

# Render pone el puerto en PORT; en local se usa 8000.
# WEB_CONCURRENCY fija los procesos de uvicorn (spec/05-reto.md, punto 7). Las
# métricas, el límite y la caché son por proceso (ADR 0005, 0012 y 0016).
# exec deja a uvicorn como PID 1 para que reciba las señales de apagado.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-1}"]
