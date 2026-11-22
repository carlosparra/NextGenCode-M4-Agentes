# Imagen del HR Assistant para Render (o cualquier plataforma con contenedores).
FROM python:3.12-slim

# Sin archivos .pyc, log sin búfer (una línea JSON por evento) y pip sin caché.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/hr-assistant

# Usuario sin privilegios: el proceso nunca corre como root.
RUN useradd --create-home --uid 10001 appuser

# Primero las dependencias, para reutilizar la capa si solo cambia el código.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Solo lo que el producto necesita para correr; el resto lo excluye .dockerignore.
COPY app/ app/
COPY data/ data/

USER appuser

EXPOSE 8000

# Render pone PORT; en local se usa 8000. "exec" deja a uvicorn como proceso
# principal para que reciba las señales de apagado.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
