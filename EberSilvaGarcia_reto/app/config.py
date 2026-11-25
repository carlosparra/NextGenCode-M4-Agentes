"""Configuración del HR Assistant leída de variables de entorno.

Toda la configuración vive aquí y se valida al arrancar: un valor inválido
impide que el proceso inicie, con un mensaje que dice qué variable falla y
nunca muestra el valor de un secreto.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parent.parent

VALID_PROVIDERS = ("fake", "gateway")
VALID_ENVIRONMENTS = ("development", "production")
VALID_PII_POLICIES = ("mask", "block")
ALL_SCOPES = frozenset({"ask", "metrics", "mcp"})
MIN_PRODUCTION_KEY_CHARS = 16


class ConfigError(ValueError):
    """Error de configuración: el producto no debe arrancar."""


@dataclass(frozen=True)
class ApiClient:
    """Un cliente autorizado de la API.

    :param name: Nombre del cliente; es lo que aparece en logs y auditoría
    :type name: str
    :param key: Clave secreta; nunca se escribe en logs ni trazas
    :type key: str
    :param scopes: Permisos del cliente (mínimo privilegio)
    :type scopes: frozenset[str]
    """

    name: str
    key: str = field(repr=False)
    scopes: frozenset[str] = ALL_SCOPES


@dataclass(frozen=True)
class Settings:
    """Configuración completa y validada del producto."""

    # pylint: disable=too-many-instance-attributes
    environment: str = "development"
    service_name: str = "hr-assistant"
    model_provider: str = "fake"
    agent_max_steps: int = 4
    subagent_max_steps: int = 6
    reflection_max_rounds: int = 2
    max_question_chars: int = 2000
    employees_path: Path = ROOT / "data" / "employees.json"
    vacations_path: Path = ROOT / "data" / "vacations.json"
    prices_path: Path = ROOT / "data" / "model_prices.json"
    slo_p95_ms: int = 2000
    langsmith_tracing: bool = False
    langsmith_project: str = "hr-assistant"
    hide_inputs: bool = True
    hide_outputs: bool = True
    cf_account_id: str = ""
    cf_gateway_id: str = "default"
    cf_api_token: str = field(default="", repr=False)
    cf_gateway_auth: bool = True
    model_small: str = "@cf/meta/llama-3.1-8b-instruct-fast"
    model_large: str = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    routing: bool = True
    router_max_chars: int = 80
    history_window: int = 6
    model_max_tokens: int = 300
    model_temperature: float = 0.0
    model_timeout_seconds: float = 30.0
    model_retries: int = 2
    cache_ttl_seconds: int = 0
    answer_cache_ttl_seconds: int = 0
    compact_prompts: bool = True
    api_clients: tuple[ApiClient, ...] = ()
    rate_limit_per_minute: int = 30
    pii_policy: str = "mask"
    audit_log_path: str = ""

    @property
    def is_production(self) -> bool:
        """Indica si aplican las reglas de compliance de producción.

        :return: ``True`` con ``ENVIRONMENT=production``
        :rtype: bool
        """
        return self.environment == "production"


def _int(env: Mapping[str, str], name: str, default: int, minimum: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} debe ser un entero") from exc
    if value < minimum:
        raise ConfigError(f"{name} debe ser mayor o igual a {minimum}")
    return value


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} debe ser un número") from exc
    if value < 0:
        raise ConfigError(f"{name} no puede ser negativo")
    return value


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "si"):
        return True
    if raw in ("0", "false", "no"):
        return False
    raise ConfigError(f"{name} debe ser true o false")


def _choice(env: Mapping[str, str], name: str, default: str, valid) -> str:
    value = env.get(name, "").strip() or default
    if value not in valid:
        raise ConfigError(f"{name} debe ser uno de: {', '.join(valid)}")
    return value


def _path(env: Mapping[str, str], name: str, default: Path) -> Path:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def parse_scopes(raw: str) -> dict[str, frozenset[str]]:
    """Lee ``CLIENT_SCOPES`` con la forma ``cliente:ask|mcp,otro:metrics``.

    :param raw: Valor de la variable
    :type raw: str
    :return: Permisos por cliente
    :rtype: dict[str, frozenset[str]]
    :raises ConfigError: Si un permiso no existe
    """
    scopes: dict[str, frozenset[str]] = {}
    for entry in filter(None, (part.strip() for part in raw.split(","))):
        name, _, values = entry.partition(":")
        wanted = frozenset(filter(None, values.split("|")))
        unknown = wanted - ALL_SCOPES
        if not name or not wanted or unknown:
            raise ConfigError(
                f"CLIENT_SCOPES: la entrada de '{name}' no es válida; "
                f"permisos posibles: {', '.join(sorted(ALL_SCOPES))}"
            )
        scopes[name] = wanted
    return scopes


def parse_api_keys(raw: str, scopes_raw: str = "") -> tuple[ApiClient, ...]:
    """Lee ``API_KEYS`` con la forma ``cliente:clave,cliente2:clave2``.

    El mensaje de error dice qué entrada falla y su largo, nunca su valor.

    :param raw: Valor de la variable ``API_KEYS``
    :type raw: str
    :param scopes_raw: Valor de ``CLIENT_SCOPES`` (opcional)
    :type scopes_raw: str
    :return: Clientes autorizados
    :rtype: tuple[ApiClient, ...]
    :raises ConfigError: Si alguna entrada está mal formada o se repite
    """
    scopes = parse_scopes(scopes_raw)
    clients: list[ApiClient] = []
    entries = [part.strip() for part in raw.split(",") if part.strip()]
    for position, entry in enumerate(entries, start=1):
        name, separator, key = entry.partition(":")
        if not separator or not name.strip() or not key.strip():
            raise ConfigError(
                f"API_KEYS: la entrada {position} (largo {len(entry)}) "
                "no tiene la forma cliente:clave"
            )
        name = name.strip()
        if any(client.name == name for client in clients):
            raise ConfigError(
                f"API_KEYS: el cliente de la entrada {position} se repite"
            )
        clients.append(ApiClient(name, key.strip(), scopes.get(name, ALL_SCOPES)))
    return tuple(clients)


def check_compliance(settings: Settings) -> None:
    """Compliance como código: en producción se niega a arrancar si algo falla.

    :param settings: Configuración ya leída
    :type settings: Settings
    :raises ConfigError: Con la regla que no se cumple
    """
    if settings.model_provider == "gateway":
        missing = [
            name
            for name, value in (
                ("CF_ACCOUNT_ID", settings.cf_account_id),
                ("CF_GATEWAY_ID", settings.cf_gateway_id),
                ("CF_API_TOKEN", settings.cf_api_token),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                f"Con MODEL_PROVIDER=gateway faltan: {', '.join(missing)}"
            )
    if not settings.is_production:
        return
    if settings.model_provider == "fake":
        raise ConfigError("En producción MODEL_PROVIDER no puede ser fake")
    if not settings.api_clients:
        raise ConfigError("En producción API_KEYS no puede estar vacía")
    for position, client in enumerate(settings.api_clients, start=1):
        if len(client.key) < MIN_PRODUCTION_KEY_CHARS:
            raise ConfigError(
                f"En producción la clave {position} debe tener al menos "
                f"{MIN_PRODUCTION_KEY_CHARS} caracteres"
            )
    if settings.langsmith_tracing and not (
        settings.hide_inputs and settings.hide_outputs
    ):
        raise ConfigError(
            "En producción, con trazas encendidas, HIDE_INPUTS y HIDE_OUTPUTS deben "
            "ser true"
        )


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Lee y valida la configuración.

    :param env: Variables de entorno; por omisión, las del proceso
    :type env: Mapping[str, str] | None
    :return: Configuración validada
    :rtype: Settings
    :raises ConfigError: Si algún valor es inválido o falla el compliance
    """
    env = os.environ if env is None else env
    settings = Settings(
        environment=_choice(env, "ENVIRONMENT", "development", VALID_ENVIRONMENTS),
        service_name=env.get("SERVICE_NAME", "").strip() or "hr-assistant",
        model_provider=_choice(env, "MODEL_PROVIDER", "fake", VALID_PROVIDERS),
        agent_max_steps=_int(env, "AGENT_MAX_STEPS", 4, 1),
        subagent_max_steps=_int(env, "SUBAGENT_MAX_STEPS", 6, 2),
        reflection_max_rounds=_int(env, "REFLECTION_MAX_ROUNDS", 2, 0),
        max_question_chars=_int(env, "MAX_QUESTION_CHARS", 2000, 1),
        employees_path=_path(env, "EMPLOYEES_PATH", ROOT / "data" / "employees.json"),
        vacations_path=_path(env, "VACATIONS_PATH", ROOT / "data" / "vacations.json"),
        prices_path=_path(env, "PRICES_PATH", ROOT / "data" / "model_prices.json"),
        slo_p95_ms=_int(env, "SLO_P95_MS", 2000, 1),
        langsmith_tracing=_bool(env, "LANGSMITH_TRACING", False),
        langsmith_project=env.get("LANGSMITH_PROJECT", "").strip() or "hr-assistant",
        hide_inputs=_bool(env, "HIDE_INPUTS", True),
        hide_outputs=_bool(env, "HIDE_OUTPUTS", True),
        cf_account_id=env.get("CF_ACCOUNT_ID", "").strip(),
        cf_gateway_id=env.get("CF_GATEWAY_ID", "").strip() or "default",
        cf_api_token=env.get("CF_API_TOKEN", "").strip(),
        cf_gateway_auth=_bool(env, "CF_GATEWAY_AUTH", True),
        model_small=env.get("MODEL_SMALL", "").strip()
        or "@cf/meta/llama-3.1-8b-instruct-fast",
        model_large=env.get("MODEL_LARGE", "").strip()
        or "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        routing=_bool(env, "ROUTING", True),
        router_max_chars=_int(env, "ROUTER_MAX_CHARS", 80, 1),
        history_window=_int(env, "HISTORY_WINDOW", 6, 0),
        model_max_tokens=_int(env, "MODEL_MAX_TOKENS", 300, 1),
        model_temperature=_float(env, "MODEL_TEMPERATURE", 0.0),
        model_timeout_seconds=_float(env, "MODEL_TIMEOUT_SECONDS", 30.0),
        model_retries=_int(env, "MODEL_RETRIES", 2, 0),
        cache_ttl_seconds=_int(env, "CACHE_TTL_SECONDS", 0, 0),
        answer_cache_ttl_seconds=_int(env, "ANSWER_CACHE_TTL_SECONDS", 0, 0),
        compact_prompts=_bool(env, "COMPACT_PROMPTS", True),
        api_clients=parse_api_keys(
            env.get("API_KEYS", ""), env.get("CLIENT_SCOPES", "")
        ),
        rate_limit_per_minute=_int(env, "RATE_LIMIT_PER_MINUTE", 30, 1),
        pii_policy=_choice(env, "PII_POLICY", "mask", VALID_PII_POLICIES),
        audit_log_path=env.get("AUDIT_LOG_PATH", "").strip(),
    )
    check_compliance(settings)
    return settings
