# Imagen del HR Assistant (spec/04-production.md, punto 5).
# La configuración llega solo por variables de entorno: ningún secreto entra en la imagen.
FROM python:3.12-slim

# Sin archivos .pyc y con la salida sin búfer, para que el log JSON llegue al momento
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Primero las dependencias, para aprovechar la caché de capas de Docker
COPY requirements.txt .
RUN pip install -r requirements.txt

# Solo lo que el producto necesita para correr: el código y los datos
COPY app/ app/
COPY data/ data/

# Usuario sin privilegios: el proceso nunca corre como root
RUN useradd --create-home --uid 10001 appuser
USER appuser

# Render pone el puerto en PORT; en local se usa 8000
EXPOSE 8000

# Forma shell para expandir ${PORT:-8000}; exec deja a uvicorn como PID 1 y recibe las señales
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
