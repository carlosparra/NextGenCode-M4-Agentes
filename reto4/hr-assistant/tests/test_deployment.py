"""Pruebas de los archivos de publicación (spec/04-production.md, puntos 3 y 5 a 7).

Revisan ``Dockerfile``, ``.dockerignore``, ``.github/workflows/ci.yml``,
``render.yaml`` y ``doc/compliance-checklist.md`` como texto, sin depender de
un lector de YAML, para que corran igual en clase y en el CI.
"""

import re

from conftest import PRODUCT_ROOT

DOCKERFILE = PRODUCT_ROOT / "Dockerfile"
DOCKERIGNORE = PRODUCT_ROOT / ".dockerignore"
CI_WORKFLOW = PRODUCT_ROOT / ".github" / "workflows" / "ci.yml"
RENDER_BLUEPRINT = PRODUCT_ROOT / "render.yaml"
CHECKLIST = PRODUCT_ROOT / "doc" / "compliance-checklist.md"
SECRETS = ("API_KEYS", "CF_ACCOUNT_ID", "CF_API_TOKEN")


def _read(path):
    """Lee un archivo del producto como texto UTF-8.

    :param path: Ruta del archivo
    :type path: pathlib.Path
    :return: Contenido del archivo
    :rtype: str
    """
    return path.read_text(encoding="utf-8")


def _instructions(name):
    """Devuelve los argumentos de cada instrucción ``name`` del Dockerfile.

    :param name: Instrucción, por ejemplo ``FROM`` o ``USER``
    :type name: str
    :return: Argumentos de cada aparición, en orden
    :rtype: list[str]
    """
    pattern = rf"^{name}\s+(.+)$"
    return re.findall(pattern, _read(DOCKERFILE), re.MULTILINE | re.IGNORECASE)


def _ci_jobs():
    """Separa los trabajos de ``ci.yml`` en bloques de texto por nombre.

    :return: Nombre del trabajo a su bloque, en el orden del archivo
    :rtype: dict[str, str]
    """
    jobs_section = _read(CI_WORKFLOW).split("\njobs:", 1)[1]
    parts = re.split(r"^  ([\w-]+):\s*$", jobs_section, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2]))


def _needs(job_text):
    """Devuelve los trabajos de los que depende un trabajo del CI.

    :param job_text: Bloque de texto del trabajo
    :type job_text: str
    :return: Nombres en ``needs``; vacío si no tiene
    :rtype: list[str]
    """
    match = re.search(r"^\s+needs:\s*\[?([\w, -]+)\]?\s*$", job_text, re.MULTILINE)
    if match is None:
        return []
    return [name.strip() for name in match.group(1).split(",")]


def _render_field(name):
    """Devuelve el valor de un campo del servicio en ``render.yaml``.

    :param name: Campo, por ejemplo ``runtime``
    :type name: str
    :return: Valor sin comillas, o ``None`` si no está
    :rtype: str or None
    """
    pattern = rf"^\s*-?\s*{name}:\s*(\S+)\s*$"
    match = re.search(pattern, _read(RENDER_BLUEPRINT), re.MULTILINE)
    return match.group(1).strip("\"'") if match else None


def _render_env_vars():
    """Lee ``envVars`` de ``render.yaml`` como un dict por variable.

    :return: Variable a sus campos (``value`` o ``sync``), sin comillas
    :rtype: dict[str, dict[str, str]]
    """
    env_vars = {}
    current = {}
    seen_key = False
    for line in _read(RENDER_BLUEPRINT).splitlines():
        key = re.match(r"^\s*-\s*key:\s*(\S+)\s*$", line)
        field = re.match(r"^\s*(value|sync):\s*(.+?)\s*$", line)
        if key:
            current = env_vars.setdefault(key.group(1), {})
            seen_key = True
        elif field and seen_key:
            current[field.group(1)] = field.group(2).strip("\"'")
    return env_vars


def _checklist_rows():
    """Devuelve las filas de la tabla de compliance como listas de celdas.

    :return: Encabezado y filas, sin la línea separadora
    :rtype: list[list[str]]
    """
    rows = []
    for line in _read(CHECKLIST).splitlines():
        if not line.startswith("|") or set(line) <= set("|- "):
            continue
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


# --- Contenedor ------------------------------------------------------------


def test_docker_image_is_based_on_python_312_slim():
    images = [arguments.split()[0] for arguments in _instructions("FROM")]

    assert images == ["python:3.12-slim"]


def test_docker_image_runs_as_a_user_that_is_not_root():
    users = _instructions("USER")

    assert users
    assert users[-1].strip() not in {"root", "0", "0:0"}


def test_docker_image_starts_uvicorn_on_the_port_that_render_gives():
    command = " ".join(_instructions("CMD"))

    assert "uvicorn app.main:app" in command
    assert "--host 0.0.0.0" in command
    assert "--port ${PORT:-8000}" in command


def test_docker_context_leaves_out_secrets_tests_and_caches():
    entries = {
        line.strip().rstrip("/")
        for line in _read(DOCKERIGNORE).splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert {".env", "tests", "e2e"} <= entries
    assert any("__pycache__" in entry for entry in entries)
    assert ".pytest_cache" in entries


# --- Pipeline de CI --------------------------------------------------------


def test_ci_runs_on_every_push_and_every_pull_request():
    text = _read(CI_WORKFLOW)
    triggers = re.search(r"^on:(.*?)^\S", text, re.MULTILINE | re.DOTALL)

    assert triggers is not None
    assert "push" in triggers.group(1)
    assert "pull_request" in triggers.group(1)


def test_ci_chains_style_unit_e2e_and_docker_with_needs():
    jobs = _ci_jobs()

    assert list(jobs) == ["style", "unit", "e2e", "docker"]
    assert _needs(jobs["style"]) == []
    assert _needs(jobs["unit"]) == ["style"]
    assert _needs(jobs["e2e"]) == ["unit"]
    assert _needs(jobs["docker"]) == ["e2e"]


def test_ci_style_job_runs_pylint_with_88_columns():
    style = _ci_jobs()["style"]

    assert "pylint" in style
    assert "--max-line-length=88" in style


def test_ci_unit_job_fails_below_80_percent_coverage():
    unit = _ci_jobs()["unit"]

    assert "pytest" in unit
    assert "--cov-fail-under=80" in unit


def test_ci_e2e_job_runs_playwright_against_the_fake_model():
    e2e = _ci_jobs()["e2e"]

    assert "playwright" in e2e
    assert "MODEL_PROVIDER: fake" in e2e
    assert "E2E_API_KEY" in e2e


def test_ci_docker_job_builds_the_image():
    assert "docker build" in _ci_jobs()["docker"]


# --- Render ----------------------------------------------------------------


def test_render_blueprint_has_one_free_docker_web_service_with_health_check():
    text = _read(RENDER_BLUEPRINT)

    assert len(re.findall(r"^\s*-\s*type:\s*web\s*$", text, re.MULTILINE)) == 1
    assert _render_field("name")
    assert _render_field("runtime") == "docker"
    assert _render_field("plan") == "free"
    assert _render_field("healthCheckPath") == "/health"


def test_render_deploys_only_when_the_ci_checks_pass():
    assert _render_field("autoDeployTrigger") == "checksPass"


def test_render_sets_the_safe_production_values():
    env_vars = _render_env_vars()
    expected = {
        "ENVIRONMENT": "production",
        "MODEL_PROVIDER": "gateway",
        "HIDE_INPUTS": "true",
        "HIDE_OUTPUTS": "true",
    }

    for name, value in expected.items():
        assert env_vars[name].get("value") == value


def test_render_secrets_are_never_written_in_the_blueprint():
    env_vars = _render_env_vars()

    for name in SECRETS:
        assert env_vars[name] == {"sync": "false"}
    assert "LANGSMITH_API_KEY" not in env_vars


# --- Checklist de compliance -----------------------------------------------


def test_compliance_checklist_is_a_table_of_rule_code_and_check():
    header, *rows = _checklist_rows()
    production_rules = " ".join(row[0] for row in rows)

    assert len(header) == 3
    assert rows
    assert all(len(row) == 3 and all(row) for row in rows)
    for setting in ("MODEL_PROVIDER", "API_KEYS", "HIDE_INPUTS", "HIDE_OUTPUTS"):
        assert setting in production_rules


def test_compliance_checklist_points_only_to_files_that_exist():
    paths = re.findall(
        r"`((?:app|tests)/[\w/.-]+\.(?:py|feature|html))`", _read(CHECKLIST)
    )

    assert paths
    missing = [path for path in paths if not (PRODUCT_ROOT / path).is_file()]
    assert missing == []
