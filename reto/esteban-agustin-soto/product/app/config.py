"""Configuración del servicio a partir de variables de entorno."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from app.security import parse_api_keys

SUPPORTED_PROVIDERS = ("fake", "gateway")
SUPPORTED_ENVIRONMENTS = ("development", "production")
DEFAULT_ENVIRONMENT = "development"
DEFAULT_RATE_LIMIT = 30
DEFAULT_GATEWAY_ID = "default"
DEFAULT_MODEL_SMALL = "@cf/meta/llama-3.1-8b-instruct-fast"
DEFAULT_MODEL_LARGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
DEFAULT_ROUTER_MAX_CHARS = 80
DEFAULT_HISTORY_WINDOW = 6
DEFAULT_MODEL_MAX_TOKENS = 300
DEFAULT_PRICES_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "model_prices.json"
)
DEFAULT_PROVIDER = "fake"
DEFAULT_MAX_STEPS = 3
DEFAULT_MAX_QUESTION_CHARS = 2000
DEFAULT_MAX_ANSWER_CHARS = 1500
DEFAULT_SERVICE_NAME = "hr-assistant"
DEFAULT_SLO_P95_MS = 2000
DEFAULT_EMPLOYEES_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "employees.json"
)


@dataclass(frozen=True)
class Settings:  # pylint: disable=too-many-instance-attributes
    """Valores de configuración ya validados.

    :param model_provider: Nombre del proveedor del modelo
    :type model_provider: str
    :param agent_max_steps: Tope de vueltas del bucle del agente
    :type agent_max_steps: int
    :param max_question_chars: Largo máximo de la pregunta
    :type max_question_chars: int
    :param employees_path: Ruta del archivo de empleados
    :type employees_path: pathlib.Path
    :param service_name: Campo ``service`` del log
    :type service_name: str
    :param slo_p95_ms: Meta de latencia p95 en milisegundos
    :type slo_p95_ms: int
    :param langsmith_tracing: Si las trazas están encendidas
    :type langsmith_tracing: bool
    :param hide_inputs: No mandar entradas a LangSmith
    :type hide_inputs: bool
    :param hide_outputs: No mandar salidas a LangSmith
    :type hide_outputs: bool
    :param cf_account_id: Cuenta de Cloudflare
    :type cf_account_id: str
    :param cf_gateway_id: Gateway de Cloudflare
    :type cf_gateway_id: str
    :param cf_api_token: Token de Cloudflare (secreto, no sale en ``repr``)
    :type cf_api_token: str
    :param model_small: Nombre del modelo barato
    :type model_small: str
    :param model_large: Nombre del modelo capaz
    :type model_large: str
    :param routing: Si se enruta por pregunta
    :type routing: bool
    :param router_max_chars: Largo desde el que la pregunta va al modelo capaz
    :type router_max_chars: int
    :param history_window: Mensajes de historial que se mandan al modelo
    :type history_window: int
    :param model_max_tokens: Tope de tokens de salida
    :type model_max_tokens: int
    :param model_temperature: Temperatura del modelo
    :type model_temperature: float
    :param cache_ttl_seconds: TTL de la caché del gateway (0: apagada)
    :type cache_ttl_seconds: int
    :param prices_path: Archivo de precios por modelo
    :type prices_path: pathlib.Path
    :param environment: ``development`` o ``production``
    :type environment: str
    :param api_keys: Diccionario ``cliente -> clave`` (secreto, fuera de ``repr``)
    :type api_keys: dict
    :param rate_limit_per_minute: Peticiones por cliente y por minuto
    :type rate_limit_per_minute: int
    :param pii_masking: Enmascara CURP y correo en entradas, respuestas y logs
        (``PII_MASKING``); en producción no puede ser ``False``
    :type pii_masking: bool
    :param max_answer_chars: Largo máximo de ``answer``; si se pasa, se recorta
        y termina en ``…`` (``MAX_ANSWER_CHARS``)
    :type max_answer_chars: int
    """

    model_provider: str
    agent_max_steps: int
    max_question_chars: int
    employees_path: Path
    service_name: str = DEFAULT_SERVICE_NAME
    slo_p95_ms: int = DEFAULT_SLO_P95_MS
    langsmith_tracing: bool = False
    hide_inputs: bool = True
    hide_outputs: bool = True
    cf_account_id: str = ""
    cf_gateway_id: str = DEFAULT_GATEWAY_ID
    cf_api_token: str = field(default="", repr=False)
    model_small: str = DEFAULT_MODEL_SMALL
    model_large: str = DEFAULT_MODEL_LARGE
    routing: bool = True
    router_max_chars: int = DEFAULT_ROUTER_MAX_CHARS
    history_window: int = DEFAULT_HISTORY_WINDOW
    model_max_tokens: int = DEFAULT_MODEL_MAX_TOKENS
    model_temperature: float = 0
    cache_ttl_seconds: int = 0
    prices_path: Path = DEFAULT_PRICES_PATH
    environment: str = DEFAULT_ENVIRONMENT
    api_keys: dict = field(default_factory=dict, repr=False)
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT
    pii_masking: bool = True
    max_answer_chars: int = DEFAULT_MAX_ANSWER_CHARS


def _environment(env):
    """Lee ``ENVIRONMENT`` y exige un valor conocido.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: ``development`` o ``production``
    :rtype: str
    :raises ValueError: Si el valor no es ninguno de los dos
    """
    value = env.get("ENVIRONMENT", DEFAULT_ENVIRONMENT)
    if value not in SUPPORTED_ENVIRONMENTS:
        raise ValueError(
            f"ENVIRONMENT must be one of {SUPPORTED_ENVIRONMENTS}, got {value!r}"
        )
    return value


def _boolean(env, name, default):
    """Lee un booleano ``true``/``false`` de ``env``.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión
    :type default: bool
    :return: El booleano validado
    :rtype: bool
    :raises ValueError: Si el valor no es ``true`` ni ``false``
    """
    raw = env.get(name)
    if raw is None:
        return default
    if raw not in ("true", "false"):
        raise ValueError(f"{name} must be 'true' or 'false', got {raw!r}")
    return raw == "true"


def _positive_int(env, name, default):
    """Lee un entero positivo de ``env``.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión
    :type default: int
    :return: El entero validado
    :rtype: int
    :raises ValueError: Si no es un entero mayor que cero
    """
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from error
    if value < 1:
        raise ValueError(f"{name} must be greater than zero, got {value}")
    return value


def _non_negative_int(env, name, default):
    """Lee un entero mayor o igual que cero de ``env``.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión
    :type default: int
    :return: El entero validado
    :rtype: int
    :raises ValueError: Si no es un entero o es negativo
    """
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from error
    if value < 0:
        raise ValueError(f"{name} must not be negative, got {value}")
    return value


def _temperature(env):
    """Lee ``MODEL_TEMPERATURE`` como número entre 0 y 2.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: La temperatura validada
    :rtype: float
    :raises ValueError: Si no es un número en el rango
    """
    raw = env.get("MODEL_TEMPERATURE")
    if raw is None:
        return 0
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(
            f"MODEL_TEMPERATURE must be a number, got {raw!r}"
        ) from error
    if not 0 <= value <= 2:
        raise ValueError(f"MODEL_TEMPERATURE must be between 0 and 2, got {value}")
    return value


def _cost_settings(env, provider):
    """Lee las variables de la sesión 3 (modelos, palancas y Cloudflare).

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param provider: Proveedor ya validado
    :type provider: str
    :return: Campos de ``Settings`` para costos
    :rtype: dict
    :raises ValueError: Si un valor es inválido o falta una variable ``CF_*``
    """
    if provider == "gateway":
        for name in ("CF_ACCOUNT_ID", "CF_API_TOKEN"):
            if not env.get(name):
                raise ValueError(f"{name} is required when MODEL_PROVIDER=gateway")
    raw_prices = env.get("PRICES_PATH")
    return {
        "cf_account_id": env.get("CF_ACCOUNT_ID", ""),
        "cf_gateway_id": env.get("CF_GATEWAY_ID") or DEFAULT_GATEWAY_ID,
        "cf_api_token": env.get("CF_API_TOKEN", ""),
        "model_small": env.get("MODEL_SMALL") or DEFAULT_MODEL_SMALL,
        "model_large": env.get("MODEL_LARGE") or DEFAULT_MODEL_LARGE,
        "routing": _boolean(env, "ROUTING", True),
        "router_max_chars": _positive_int(
            env, "ROUTER_MAX_CHARS", DEFAULT_ROUTER_MAX_CHARS
        ),
        "history_window": _positive_int(
            env, "HISTORY_WINDOW", DEFAULT_HISTORY_WINDOW
        ),
        "model_max_tokens": _positive_int(
            env, "MODEL_MAX_TOKENS", DEFAULT_MODEL_MAX_TOKENS
        ),
        "model_temperature": _temperature(env),
        "cache_ttl_seconds": _non_negative_int(env, "CACHE_TTL_SECONDS", 0),
        "prices_path": Path(raw_prices).resolve() if raw_prices
        else DEFAULT_PRICES_PATH,
    }


def load_settings(env: Mapping[str, str]) -> Settings:
    """Construye y valida la configuración.

    :param env: Variables de entorno (por ejemplo ``os.environ``)
    :type env: Mapping[str, str]
    :return: La configuración validada
    :rtype: Settings
    :raises ValueError: Si algún valor es inválido
    """
    provider = env.get("MODEL_PROVIDER", DEFAULT_PROVIDER)
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"MODEL_PROVIDER must be one of {SUPPORTED_PROVIDERS}, "
            f"got {provider!r}"
        )
    raw_path = env.get("EMPLOYEES_PATH")
    path = Path(raw_path) if raw_path else DEFAULT_EMPLOYEES_PATH
    return Settings(
        model_provider=provider,
        agent_max_steps=_positive_int(env, "AGENT_MAX_STEPS", DEFAULT_MAX_STEPS),
        max_question_chars=_positive_int(
            env, "MAX_QUESTION_CHARS", DEFAULT_MAX_QUESTION_CHARS
        ),
        employees_path=path.resolve(),
        service_name=env.get("SERVICE_NAME") or DEFAULT_SERVICE_NAME,
        slo_p95_ms=_positive_int(env, "SLO_P95_MS", DEFAULT_SLO_P95_MS),
        langsmith_tracing=_boolean(env, "LANGSMITH_TRACING", False),
        hide_inputs=_boolean(env, "HIDE_INPUTS", True),
        hide_outputs=_boolean(env, "HIDE_OUTPUTS", True),
        environment=_environment(env),
        api_keys=parse_api_keys(env.get("API_KEYS", "")),
        rate_limit_per_minute=_positive_int(
            env, "RATE_LIMIT_PER_MINUTE", DEFAULT_RATE_LIMIT
        ),
        pii_masking=_boolean(env, "PII_MASKING", True),
        max_answer_chars=_positive_int(
            env, "MAX_ANSWER_CHARS", DEFAULT_MAX_ANSWER_CHARS
        ),
        **_cost_settings(env, provider),
    )
