# Imagen del HR Assistant (spec/04-production.md, punto 5).
# Se construye desde product/, que es la raíz del repositorio publicado.
FROM python:3.12-slim

# Sin archivos .pyc, salida sin búfer (los logs JSON llegan enseguida) y sin caché de pip
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/hr-assistant

# Usuario sin privilegios: el proceso nunca corre como root
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin hr

# Primero las dependencias, para que la capa se reutilice si solo cambia el código
COPY requirements.txt .
RUN pip install -r requirements.txt

# Solo lo que el producto necesita para correr; el resto lo deja fuera .dockerignore
COPY app/ app/
COPY data/ data/

USER hr

EXPOSE 8000

# Render pone el puerto en PORT; en local se usa 8000.
# sh -c expande la variable y exec deja a uvicorn como proceso principal (recibe las señales).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
