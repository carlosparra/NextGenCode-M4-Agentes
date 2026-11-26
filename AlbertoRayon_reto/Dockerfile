# Imagen del HR Assistant. Tres etapas: base, test (compuerta) y runtime.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY data data

# Compuerta: si las pruebas o el estilo fallan, la imagen no se construye.
FROM base AS test
COPY requirements-dev.txt pytest.ini ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests tests
RUN python -m pytest -q -p no:cacheprovider tests --cov=app --cov-fail-under=90 \
    && python -m pylint app tests --max-line-length=88 --fail-under=10 \
       --disable=missing-function-docstring,redefined-outer-name,too-few-public-methods \
    && touch /tests-passed

FROM base AS runtime
# Copiar el marcador obliga a que la etapa de pruebas haya pasado.
COPY --from=test /tests-passed /srv/.tests-passed
# Usuario sin privilegios; el código queda de root y solo se puede leer.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin hr \
    && chmod -R a-w /srv
USER hr
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD \
    python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health', timeout=3)"
CMD ["sh", "-c", "python -m app.preflight && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-1}"]
