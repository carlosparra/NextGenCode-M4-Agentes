# syntax=docker/dockerfile:1
# Etapa 1: compuerta de calidad. Si las pruebas o el estilo fallan, la imagen
# no se construye y Render no publica (también corre en CI).
FROM python:3.12-slim AS test
WORKDIR /src
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY pyproject.toml ./
COPY app ./app
COPY data ./data
COPY tests ./tests
RUN python -m pytest -q --cov=app --cov-fail-under=80 \
    && python -m pylint app tests --fail-under=10 \
    && touch /src/.quality-gate-passed

# Etapa 2: imagen de ejecución mínima, sin pruebas ni herramientas de desarrollo.
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 ENVIRONMENT=production PORT=8000
WORKDIR /app
# Obliga a que la etapa de pruebas haya terminado bien
COPY --from=test /src/.quality-gate-passed /tmp/
COPY requirements.txt ./
RUN pip install -r requirements.txt \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin hra
COPY --chown=root:root app ./app
COPY --chown=root:root data ./data
# Mínimo privilegio: el proceso corre sin root y no puede modificar su código
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health',timeout=4)"
CMD ["sh", "-c", "python -m app.preflight && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
