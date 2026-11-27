"""Configuración del producto, leída del entorno y validada al arrancar.

Los mensajes de error dicen qué variable falla y nunca muestran un valor secreto.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parent.parent
SCOPES = frozenset({"ask", "mcp", "metrics"})
MIN_KEY_CHARS = 16
# gateway: Workers AI a través de AI Gateway; workers: Workers AI directo, sin caché
REAL_PROVIDERS = ("gateway", "workers")
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}


class ConfigError(ValueError):
    """La configuración impide arrancar."""


@dataclass(frozen=True)
class Settings:  # pylint: disable=too-many-instance-attributes
    """Todas las variables del producto, con sus valores por omisión."""

    environment: str = "development"
    service_name: str = "hr-assistant"
    model_provider: str = "fake"
    agent_max_steps: int = 3
    max_question_chars: int = 2000
    max_history_messages: int = 50
    max_answer_chars: int = 4000
    employees_path: Path = ROOT / "data" / "employees.json"
    vacations_path: Path = ROOT / "data" / "vacations.json"
    prices_path: Path = ROOT / "data" / "model_prices.json"
    slo_p95_ms: float = 2000.0
    langsmith_tracing: bool = False
    langsmith_api_key: str = field(default="", repr=False)
    hide_inputs: bool = True
    hide_outputs: bool = True
    cf_account_id: str = ""
    cf_gateway_id: str = "default"
    cf_api_token: str = field(default="", repr=False)
    cf_aig_token: str = field(default="", repr=False)
    model_small: str = "@cf/meta/llama-3.1-8b-instruct-fast"
    model_large: str = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    routing: bool = True
    router_max_chars: int = 80
    history_window: int = 6
    model_max_tokens: int = 300
    model_temperature: float = 0.0
    cache_ttl_seconds: int = 0
    response_cache_ttl_seconds: int = 0
    compact_prompt: bool = True
    model_timeout_seconds: float = 30.0
    api_keys: Mapping[str, str] = field(default_factory=dict, repr=False)
    client_scopes: Mapping[str, frozenset] = field(default_factory=dict)
    rate_limit_per_minute: int = 30
    mcp_allowed_hosts: tuple = ()

    def scopes_for(self, client: str) -> frozenset:
        """Permisos de un cliente.

        Sin entrada en ``CLIENT_SCOPES`` el cliente tiene todos los permisos; en
        producción esa situación impide arrancar (ver :func:`check_compliance`).

        :param client: Nombre del cliente
        :type client: str
        :return: Permisos del cliente
        :rtype: frozenset
        """
        return self.client_scopes.get(client, SCOPES)


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ConfigError(f"{name} debe ser true o false")


def _number(env: Mapping[str, str], name: str, default, minimum, kind=int):
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = kind(raw)
    except ValueError as error:
        raise ConfigError(f"{name} debe ser un número") from error
    if value < minimum:
        raise ConfigError(f"{name} debe ser mayor o igual a {minimum}")
    return value


def _path(env: Mapping[str, str], name: str, default: Path) -> Path:
    raw = env.get(name)
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def parse_api_keys(raw: str) -> dict:
    """Convierte ``cliente:clave,cliente2:clave2`` en un diccionario.

    :param raw: Valor de ``API_KEYS``
    :type raw: str
    :return: Clave por cliente
    :rtype: dict
    :raises ConfigError: Si una entrada está mal formada; el error dice su posición
        y su largo, nunca su valor
    """
    keys = {}
    for position, entry in enumerate(filter(None, raw.split(",")), start=1):
        client, separator, key = entry.strip().partition(":")
        if not separator or not client or not key:
            raise ConfigError(
                f"API_KEYS: la entrada {position} (largo {len(entry)}) no tiene "
                "la forma cliente:clave"
            )
        keys[client] = key
    return keys


def parse_scopes(raw: str) -> dict:
    """Convierte ``portal:ask,grafana:metrics+ask`` en permisos por cliente.

    :param raw: Valor de ``CLIENT_SCOPES``
    :type raw: str
    :return: Conjunto de permisos por cliente
    :rtype: dict
    :raises ConfigError: Si una entrada está mal formada o el permiso no existe
    """
    scopes = {}
    for entry in filter(None, raw.split(",")):
        client, separator, names = entry.strip().partition(":")
        granted = frozenset(filter(None, names.split("+")))
        if not separator or not client or not granted or not granted <= SCOPES:
            raise ConfigError(
                f"CLIENT_SCOPES: '{client}' debe usar cliente:permiso con permisos "
                f"de {sorted(SCOPES)}"
            )
        scopes[client] = granted
    return scopes


def check_compliance(settings: Settings) -> None:
    """Reglas de compliance: en producción una configuración insegura no arranca.

    :param settings: Configuración ya leída
    :type settings: Settings
    :raises ConfigError: Con la regla que no se cumple
    """
    if settings.model_provider in REAL_PROVIDERS:
        required = [
            ("CF_ACCOUNT_ID", settings.cf_account_id),
            ("CF_API_TOKEN", settings.cf_api_token),
        ]
        if settings.model_provider == "gateway":
            required.append(("CF_GATEWAY_ID", settings.cf_gateway_id))
        missing = [name for name, value in required if not value]
        if missing:
            raise ConfigError(
                f"MODEL_PROVIDER={settings.model_provider} necesita "
                f"{', '.join(missing)}"
            )
    if settings.environment != "production":
        return
    if settings.model_provider == "fake":
        raise ConfigError("En producción no se permite MODEL_PROVIDER=fake")
    if not settings.api_keys:
        raise ConfigError("En producción API_KEYS no puede estar vacía")
    for client, key in settings.api_keys.items():
        if len(key) < MIN_KEY_CHARS:
            raise ConfigError(
                f"La clave de '{client}' tiene menos de {MIN_KEY_CHARS} caracteres"
            )
        if client not in settings.client_scopes:
            raise ConfigError(
                f"En producción '{client}' necesita permisos en CLIENT_SCOPES"
            )
    hidden = settings.hide_inputs and settings.hide_outputs
    if settings.langsmith_tracing and not hidden:
        raise ConfigError(
            "En producción las trazas exigen HIDE_INPUTS=true y HIDE_OUTPUTS=true"
        )


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Lee la configuración del entorno y la valida.

    :param env: Variables de entorno; por omisión, las del proceso
    :type env: Mapping[str, str] | None
    :return: Configuración validada
    :rtype: Settings
    :raises ConfigError: Si un valor es inválido o incumple una regla de compliance
    """
    env = os.environ if env is None else env
    provider = env.get("MODEL_PROVIDER", "fake").strip().lower()
    if provider not in ("fake", *REAL_PROVIDERS):
        raise ConfigError("MODEL_PROVIDER debe ser fake, gateway o workers")
    environment = env.get("ENVIRONMENT", "development").strip().lower()
    if environment not in {"development", "production"}:
        raise ConfigError("ENVIRONMENT debe ser development o production")
    hosts = tuple(
        host.strip()
        for name in ("MCP_ALLOWED_HOSTS", "RENDER_EXTERNAL_HOSTNAME")
        for host in env.get(name, "").split(",")
        if host.strip()
    )
    settings = Settings(
        environment=environment,
        service_name=env.get("SERVICE_NAME", "hr-assistant"),
        model_provider=provider,
        agent_max_steps=_number(env, "AGENT_MAX_STEPS", 3, 1),
        max_question_chars=_number(env, "MAX_QUESTION_CHARS", 2000, 1),
        max_history_messages=_number(env, "MAX_HISTORY_MESSAGES", 50, 0),
        max_answer_chars=_number(env, "MAX_ANSWER_CHARS", 4000, 100),
        employees_path=_path(env, "EMPLOYEES_PATH", ROOT / "data" / "employees.json"),
        vacations_path=_path(env, "VACATIONS_PATH", ROOT / "data" / "vacations.json"),
        prices_path=_path(env, "PRICES_PATH", ROOT / "data" / "model_prices.json"),
        slo_p95_ms=_number(env, "SLO_P95_MS", 2000.0, 1, float),
        langsmith_tracing=_flag(env, "LANGSMITH_TRACING", False),
        langsmith_api_key=env.get("LANGSMITH_API_KEY", ""),
        hide_inputs=_flag(env, "HIDE_INPUTS", True),
        hide_outputs=_flag(env, "HIDE_OUTPUTS", True),
        cf_account_id=env.get("CF_ACCOUNT_ID", "").strip(),
        cf_gateway_id=env.get("CF_GATEWAY_ID", "default").strip(),
        cf_api_token=env.get("CF_API_TOKEN", "").strip(),
        cf_aig_token=env.get("CF_AIG_TOKEN", "").strip(),
        model_small=env.get("MODEL_SMALL", Settings.model_small),
        model_large=env.get("MODEL_LARGE", Settings.model_large),
        routing=_flag(env, "ROUTING", True),
        router_max_chars=_number(env, "ROUTER_MAX_CHARS", 80, 1),
        history_window=_number(env, "HISTORY_WINDOW", 6, 0),
        model_max_tokens=_number(env, "MODEL_MAX_TOKENS", 300, 1),
        model_temperature=_number(env, "MODEL_TEMPERATURE", 0.0, 0, float),
        cache_ttl_seconds=_number(env, "CACHE_TTL_SECONDS", 0, 0),
        response_cache_ttl_seconds=_number(env, "RESPONSE_CACHE_TTL_SECONDS", 0, 0),
        compact_prompt=_flag(env, "COMPACT_PROMPT", True),
        model_timeout_seconds=_number(env, "MODEL_TIMEOUT_SECONDS", 30.0, 1, float),
        api_keys=parse_api_keys(env.get("API_KEYS", "")),
        client_scopes=parse_scopes(env.get("CLIENT_SCOPES", "")),
        rate_limit_per_minute=_number(env, "RATE_LIMIT_PER_MINUTE", 30, 1),
        mcp_allowed_hosts=hosts,
    )
    check_compliance(settings)
    return settings
