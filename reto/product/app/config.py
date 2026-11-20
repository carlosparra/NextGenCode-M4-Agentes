"""Configuracion del HR Assistant leida de variables de entorno.

La configuracion se valida al arrancar: un valor invalido lanza ``ConfigError``
con el nombre de la variable y el valor recibido, y la aplicacion no arranca.
Los valores secretos (``CF_API_TOKEN``, ``CF_AIG_TOKEN`` y las claves de
``API_KEYS``) nunca aparecen en mensajes ni en ``repr``.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from app.auth import parse_api_keys
from app.errors import ConfigError
from app.pricing import PriceTable

PRODUCT_DIR = Path(__file__).resolve().parent.parent
ENVIRONMENT_DEVELOPMENT = "development"
ENVIRONMENT_PRODUCTION = "production"
SUPPORTED_ENVIRONMENTS = (ENVIRONMENT_DEVELOPMENT, ENVIRONMENT_PRODUCTION)
DEFAULT_ENVIRONMENT = ENVIRONMENT_DEVELOPMENT
DEFAULT_RATE_LIMIT_PER_MINUTE = "30"
PROVIDER_FAKE = "fake"
PROVIDER_GATEWAY = "gateway"
SUPPORTED_PROVIDERS = (PROVIDER_FAKE, PROVIDER_GATEWAY)

DEFAULT_MODEL_PROVIDER = "fake"
DEFAULT_AGENT_MAX_STEPS = "3"
DEFAULT_MAX_QUESTION_CHARS = "2000"
DEFAULT_EMPLOYEES_PATH = "data/employees.json"
DEFAULT_SERVICE_NAME = "hr-assistant"
DEFAULT_SLO_P95_MS = "2000"
DEFAULT_LANGSMITH_TRACING = "false"
DEFAULT_HIDE_CONTENT = "true"
DEFAULT_CF_GATEWAY_ID = "default"
DEFAULT_MODEL_SMALL = "@cf/meta/llama-3.1-8b-instruct-fast"
DEFAULT_MODEL_LARGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
DEFAULT_ROUTING = "true"
DEFAULT_ROUTER_MAX_CHARS = "80"
DEFAULT_HISTORY_WINDOW = "6"
DEFAULT_MODEL_MAX_TOKENS = "300"
DEFAULT_MODEL_TEMPERATURE = "0"
DEFAULT_CACHE_TTL_SECONDS = "0"
DEFAULT_PRICES_PATH = "data/model_prices.json"
DEFAULT_APP_VERSION = "1.0.0"
DEFAULT_RESPONSE_CACHE_TTL_SECONDS = "0"
DEFAULT_RESPONSE_CACHE_SIZE = "256"
PII_POLICY_MASK = "mask"
PII_POLICY_BLOCK = "block"
SUPPORTED_PII_POLICIES = (PII_POLICY_MASK, PII_POLICY_BLOCK)
DEFAULT_PII_POLICY = PII_POLICY_MASK
DEFAULT_MAX_ANSWER_CHARS = "2000"
MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 2.0
CLOUDFLARE_VARIABLES = ("CF_ACCOUNT_ID", "CF_GATEWAY_ID", "CF_API_TOKEN")
BOOLEAN_VALUES = {"true": True, "false": False}


@dataclass(frozen=True)
class Settings:  # pylint: disable=too-many-instance-attributes
    """Configuracion inmutable de la aplicacion.

    :param model_provider: Proveedor del modelo: ``fake`` o ``gateway``
    :type model_provider: str
    :param agent_max_steps: Tope de vueltas del bucle del agente
    :type agent_max_steps: int
    :param max_question_chars: Largo maximo de la pregunta
    :type max_question_chars: int
    :param employees_path: Ruta absoluta al archivo de empleados
    :type employees_path: pathlib.Path
    :param service_name: Valor del campo ``service`` del log
    :type service_name: str
    :param slo_p95_ms: Meta de latencia p95 en milisegundos
    :type slo_p95_ms: int
    :param langsmith_tracing: Si se pidieron trazas en LangSmith
    :type langsmith_tracing: bool
    :param hide_inputs: No mandar entradas a LangSmith
    :type hide_inputs: bool
    :param hide_outputs: No mandar salidas a LangSmith
    :type hide_outputs: bool
    :param langsmith_enabled: Trazas pedidas y clave presente (la clave no
        se guarda)
    :type langsmith_enabled: bool
    :param cf_account_id: Cuenta de Cloudflare
    :type cf_account_id: str
    :param cf_gateway_id: Id del AI Gateway
    :type cf_gateway_id: str
    :param cf_api_token: Token de Cloudflare (secreto; no sale en ``repr``)
    :type cf_api_token: str
    :param cf_aig_token: Token del AI Gateway autenticado (opcional y secreto;
        no sale en ``repr``). Vacio: no se manda ``cf-aig-authorization``
    :type cf_aig_token: str
    :param model_small: Modelo barato
    :type model_small: str
    :param model_large: Modelo capaz
    :type model_large: str
    :param routing: Si se enruta por pregunta
    :type routing: bool
    :param router_max_chars: Preguntas mas largas van al modelo capaz
    :type router_max_chars: int
    :param history_window: Mensajes de historial que se mandan al modelo
    :type history_window: int
    :param model_max_tokens: Tope de tokens de salida por llamada
    :type model_max_tokens: int
    :param model_temperature: Temperatura del modelo (0 a 2)
    :type model_temperature: float
    :param cache_ttl_seconds: TTL de la cache del gateway (0: apagada)
    :type cache_ttl_seconds: int
    :param prices_path: Ruta absoluta al archivo de precios
    :type prices_path: pathlib.Path
    :param environment: ``development`` o ``production`` (con ``production``
        se aplican las reglas de compliance)
    :type environment: str
    :param api_keys: Clientes y claves (secreto; no sale en ``repr``)
    :type api_keys: tuple[app.auth.ApiKey, ...]
    :param rate_limit_per_minute: Peticiones por cliente por minuto
    :type rate_limit_per_minute: int
    :param app_version: Version en ``/health`` y en OpenAPI
    :type app_version: str
    :param response_cache_ttl_seconds: TTL de la cache de respuestas (0:
        apagada)
    :type response_cache_ttl_seconds: int
    :param response_cache_size: Entradas maximas de la cache de respuestas
    :type response_cache_size: int
    :param pii_policy: Politica de datos sensibles: ``mask`` o ``block``
    :type pii_policy: str
    :param max_answer_chars: Largo maximo de la respuesta
    :type max_answer_chars: int
    """

    model_provider: str
    agent_max_steps: int
    max_question_chars: int
    employees_path: Path
    service_name: str = DEFAULT_SERVICE_NAME
    slo_p95_ms: int = int(DEFAULT_SLO_P95_MS)
    langsmith_tracing: bool = False
    hide_inputs: bool = True
    hide_outputs: bool = True
    langsmith_enabled: bool = False
    cf_account_id: str = ""
    cf_gateway_id: str = DEFAULT_CF_GATEWAY_ID
    cf_api_token: str = field(default="", repr=False)
    cf_aig_token: str = field(default="", repr=False)
    model_small: str = DEFAULT_MODEL_SMALL
    model_large: str = DEFAULT_MODEL_LARGE
    routing: bool = True
    router_max_chars: int = int(DEFAULT_ROUTER_MAX_CHARS)
    history_window: int = int(DEFAULT_HISTORY_WINDOW)
    model_max_tokens: int = int(DEFAULT_MODEL_MAX_TOKENS)
    model_temperature: float = float(DEFAULT_MODEL_TEMPERATURE)
    cache_ttl_seconds: int = int(DEFAULT_CACHE_TTL_SECONDS)
    prices_path: Path = PRODUCT_DIR / DEFAULT_PRICES_PATH
    environment: str = DEFAULT_ENVIRONMENT
    api_keys: tuple = field(default=(), repr=False)
    rate_limit_per_minute: int = int(DEFAULT_RATE_LIMIT_PER_MINUTE)
    app_version: str = DEFAULT_APP_VERSION
    response_cache_ttl_seconds: int = int(DEFAULT_RESPONSE_CACHE_TTL_SECONDS)
    response_cache_size: int = int(DEFAULT_RESPONSE_CACHE_SIZE)
    pii_policy: str = DEFAULT_PII_POLICY
    max_answer_chars: int = int(DEFAULT_MAX_ANSWER_CHARS)


def _int_at_least(
    env: Mapping[str, str], name: str, default: str, minimum: int
) -> int:
    """Lee una variable entera mayor o igual a ``minimum``.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omision
    :type default: str
    :param minimum: Valor minimo aceptado
    :type minimum: int
    :return: El valor convertido a entero
    :rtype: int
    :raises ConfigError: Si el valor no es un entero mayor o igual al minimo
    """
    raw = env.get(name, default)
    message = f"{name} must be an integer >= {minimum}, got {raw!r}"
    try:
        value = int(str(raw).strip())
    except ValueError as error:
        raise ConfigError(message) from error
    if value < minimum:
        raise ConfigError(message)
    return value


def _positive_int(env: Mapping[str, str], name: str, default: str) -> int:
    """Lee una variable entera mayor o igual a 1.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omision
    :type default: str
    :return: El valor convertido a entero
    :rtype: int
    :raises ConfigError: Si el valor no es un entero mayor o igual a 1
    """
    return _int_at_least(env, name, default, minimum=1)


def _non_negative_int(env: Mapping[str, str], name: str, default: str) -> int:
    """Lee una variable entera mayor o igual a 0.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omision
    :type default: str
    :return: El valor convertido a entero
    :rtype: int
    :raises ConfigError: Si el valor no es un entero mayor o igual a 0
    """
    return _int_at_least(env, name, default, minimum=0)


def _temperature(env: Mapping[str, str]) -> float:
    """Lee ``MODEL_TEMPERATURE``: un numero entre 0 y 2.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: La temperatura
    :rtype: float
    :raises ConfigError: Si no es un numero o esta fuera del rango
    """
    raw = env.get("MODEL_TEMPERATURE", DEFAULT_MODEL_TEMPERATURE)
    message = (
        f"MODEL_TEMPERATURE must be a number between {MIN_TEMPERATURE} and "
        f"{MAX_TEMPERATURE}, got {raw!r}"
    )
    try:
        value = float(str(raw).strip())
    except ValueError as error:
        raise ConfigError(message) from error
    if not MIN_TEMPERATURE <= value <= MAX_TEMPERATURE:
        raise ConfigError(message)
    return value


def _model_provider(env: Mapping[str, str]) -> str:
    """Lee y valida ``MODEL_PROVIDER``.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: El proveedor normalizado
    :rtype: str
    :raises ConfigError: Si el proveedor no esta soportado
    """
    raw = env.get("MODEL_PROVIDER", DEFAULT_MODEL_PROVIDER)
    provider = str(raw).strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        supported = ", ".join(SUPPORTED_PROVIDERS)
        raise ConfigError(
            f"MODEL_PROVIDER must be one of: {supported}; got {raw!r}"
        )
    return provider


def _existing_file(env: Mapping[str, str], name: str, default: str) -> Path:
    """Lee una ruta de archivo y comprueba que el archivo exista.

    Las rutas relativas se resuelven contra la carpeta ``product/``.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omision
    :type default: str
    :return: Ruta absoluta al archivo
    :rtype: pathlib.Path
    :raises ConfigError: Si la variable esta vacia o el archivo no existe
    """
    raw = env.get(name, default)
    if not str(raw).strip():
        raise ConfigError(f"{name} must not be empty")
    path = Path(str(raw).strip())
    if not path.is_absolute():
        path = PRODUCT_DIR / path
    if not path.is_file():
        raise ConfigError(f"{name} file does not exist: {raw!r}")
    return path


def _employees_path(env: Mapping[str, str]) -> Path:
    """Lee ``EMPLOYEES_PATH`` y comprueba que el archivo exista.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: Ruta absoluta al archivo de empleados
    :rtype: pathlib.Path
    :raises ConfigError: Si la variable esta vacia o el archivo no existe
    """
    return _existing_file(env, "EMPLOYEES_PATH", DEFAULT_EMPLOYEES_PATH)


def _cloudflare(env: Mapping[str, str], provider: str) -> dict:
    """Lee las variables ``CF_*``; con ``gateway`` ninguna puede faltar.

    ``CF_AIG_TOKEN`` es opcional siempre: solo hace falta si el AI Gateway
    tiene encendido "Authenticated Gateway". Los mensajes de error nombran la
    variable, nunca su valor (los tokens son secretos).

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param provider: Proveedor ya validado
    :type provider: str
    :return: ``cf_account_id``, ``cf_gateway_id``, ``cf_api_token`` y
        ``cf_aig_token``
    :rtype: dict[str, str]
    :raises ConfigError: Si el proveedor es ``gateway`` y falta alguna
        obligatoria
    """
    defaults = {"CF_GATEWAY_ID": DEFAULT_CF_GATEWAY_ID}
    values = {}
    for name in CLOUDFLARE_VARIABLES:
        value = str(env.get(name, defaults.get(name, ""))).strip()
        if provider == PROVIDER_GATEWAY and not value:
            raise ConfigError(
                f"{name} must not be empty when MODEL_PROVIDER={PROVIDER_GATEWAY}"
            )
        values[name.lower()] = value
    values["cf_aig_token"] = str(env.get("CF_AIG_TOKEN", "")).strip()
    return values


def _models(env: Mapping[str, str], prices_path: Path) -> dict:
    """Lee ``MODEL_SMALL`` y ``MODEL_LARGE`` y exige que tengan precio.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param prices_path: Archivo de precios ya validado
    :type prices_path: pathlib.Path
    :return: ``model_small`` y ``model_large``
    :rtype: dict[str, str]
    :raises ConfigError: Si el archivo de precios es invalido o algun modelo
        esta vacio o no tiene precio
    """
    try:
        prices = PriceTable.load(prices_path)
    except (OSError, ValueError) as error:
        raise ConfigError(
            f"PRICES_PATH is not a valid prices file: {error}"
        ) from error
    defaults = {"MODEL_SMALL": DEFAULT_MODEL_SMALL, "MODEL_LARGE": DEFAULT_MODEL_LARGE}
    models = {}
    for name, default in defaults.items():
        model = str(env.get(name, default)).strip()
        if not model:
            raise ConfigError(f"{name} must not be empty")
        if not prices.has(model):
            raise ConfigError(f"{name} has no price in PRICES_PATH: {model!r}")
        models[name.lower()] = model
    return models


def _cost_levers(env: Mapping[str, str]) -> dict:
    """Lee las variables de las palancas de costo.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: ``routing``, ``router_max_chars``, ``history_window``,
        ``model_max_tokens``, ``model_temperature`` y ``cache_ttl_seconds``
    :rtype: dict
    :raises ConfigError: Si algun valor es invalido
    """
    return {
        "routing": _boolean(env, "ROUTING", DEFAULT_ROUTING),
        "router_max_chars": _positive_int(
            env, "ROUTER_MAX_CHARS", DEFAULT_ROUTER_MAX_CHARS
        ),
        "history_window": _non_negative_int(
            env, "HISTORY_WINDOW", DEFAULT_HISTORY_WINDOW
        ),
        "model_max_tokens": _positive_int(
            env, "MODEL_MAX_TOKENS", DEFAULT_MODEL_MAX_TOKENS
        ),
        "model_temperature": _temperature(env),
        "cache_ttl_seconds": _non_negative_int(
            env, "CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS
        ),
    }


def _boolean(env: Mapping[str, str], name: str, default: str) -> bool:
    """Lee una variable booleana: ``true`` o ``false`` sin importar mayusculas.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omision
    :type default: str
    :return: El valor convertido a booleano
    :rtype: bool
    :raises ConfigError: Si el valor no es ``true`` ni ``false``
    """
    raw = env.get(name, default)
    value = BOOLEAN_VALUES.get(str(raw).strip().lower())
    if value is None:
        raise ConfigError(f"{name} must be 'true' or 'false', got {raw!r}")
    return value


def _service_name(env: Mapping[str, str]) -> str:
    """Lee ``SERVICE_NAME`` y rechaza valores vacios.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: Nombre del servicio sin espacios a los lados
    :rtype: str
    :raises ConfigError: Si el nombre esta vacio
    """
    name = str(env.get("SERVICE_NAME", DEFAULT_SERVICE_NAME)).strip()
    if not name:
        raise ConfigError("SERVICE_NAME must not be empty")
    return name


def _has_langsmith_key(env: Mapping[str, str]) -> bool:
    """Indica si existe ``LANGSMITH_API_KEY`` sin guardar ni mostrar su valor.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: ``True`` si la clave existe y no esta vacia
    :rtype: bool
    """
    return bool(str(env.get("LANGSMITH_API_KEY", "")).strip())


def _environment(env: Mapping[str, str]) -> str:
    """Lee y valida ``ENVIRONMENT``.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: ``development`` o ``production``
    :rtype: str
    :raises ConfigError: Si el valor no es uno de los soportados
    """
    raw = env.get("ENVIRONMENT", DEFAULT_ENVIRONMENT)
    environment = str(raw).strip().lower()
    if environment not in SUPPORTED_ENVIRONMENTS:
        supported = ", ".join(SUPPORTED_ENVIRONMENTS)
        raise ConfigError(f"ENVIRONMENT must be one of: {supported}; got {raw!r}")
    return environment


def _access(env: Mapping[str, str]) -> dict:
    """Lee el entorno, las claves por cliente y el limite de peticiones.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: ``environment``, ``api_keys`` y ``rate_limit_per_minute``
    :rtype: dict
    :raises ConfigError: Si algun valor es invalido; el error de ``API_KEYS``
        nunca muestra una clave
    """
    return {
        "environment": _environment(env),
        "api_keys": parse_api_keys(env.get("API_KEYS", "")),
        "rate_limit_per_minute": _positive_int(
            env, "RATE_LIMIT_PER_MINUTE", DEFAULT_RATE_LIMIT_PER_MINUTE
        ),
    }


def _app_version(env: Mapping[str, str]) -> str:
    """Lee ``APP_VERSION`` y rechaza valores vacios.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: Version sin espacios a los lados
    :rtype: str
    :raises ConfigError: Si la version esta vacia
    """
    version = str(env.get("APP_VERSION", DEFAULT_APP_VERSION)).strip()
    if not version:
        raise ConfigError("APP_VERSION must not be empty")
    return version


def _pii_policy(env: Mapping[str, str]) -> str:
    """Lee y valida ``PII_POLICY``.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: ``mask`` o ``block``
    :rtype: str
    :raises ConfigError: Si el valor no es una politica soportada
    """
    raw = env.get("PII_POLICY", DEFAULT_PII_POLICY)
    policy = str(raw).strip().lower()
    if policy not in SUPPORTED_PII_POLICIES:
        supported = ", ".join(SUPPORTED_PII_POLICIES)
        raise ConfigError(f"PII_POLICY must be one of: {supported}; got {raw!r}")
    return policy


def _operations(env: Mapping[str, str]) -> dict:
    """Lee la version, la cache de respuestas y las guardas del reto.

    :param env: Variables de entorno
    :type env: Mapping[str, str]
    :return: ``app_version``, ``response_cache_ttl_seconds``,
        ``response_cache_size``, ``pii_policy`` y ``max_answer_chars``
    :rtype: dict
    :raises ConfigError: Si algun valor es invalido
    """
    return {
        "app_version": _app_version(env),
        "response_cache_ttl_seconds": _non_negative_int(
            env, "RESPONSE_CACHE_TTL_SECONDS", DEFAULT_RESPONSE_CACHE_TTL_SECONDS
        ),
        "response_cache_size": _positive_int(
            env, "RESPONSE_CACHE_SIZE", DEFAULT_RESPONSE_CACHE_SIZE
        ),
        "pii_policy": _pii_policy(env),
        "max_answer_chars": _positive_int(
            env, "MAX_ANSWER_CHARS", DEFAULT_MAX_ANSWER_CHARS
        ),
    }


def load_settings(env: Mapping[str, str]) -> Settings:
    """Construye y valida la configuracion a partir de un mapeo de variables.

    :param env: Variables de entorno (por ejemplo ``os.environ``)
    :type env: Mapping[str, str]
    :return: Configuracion validada
    :rtype: Settings
    :raises ConfigError: Si algun valor es invalido
    """
    tracing = _boolean(env, "LANGSMITH_TRACING", DEFAULT_LANGSMITH_TRACING)
    provider = _model_provider(env)
    prices_path = _existing_file(env, "PRICES_PATH", DEFAULT_PRICES_PATH)
    return Settings(
        model_provider=provider,
        agent_max_steps=_positive_int(
            env, "AGENT_MAX_STEPS", DEFAULT_AGENT_MAX_STEPS
        ),
        max_question_chars=_positive_int(
            env, "MAX_QUESTION_CHARS", DEFAULT_MAX_QUESTION_CHARS
        ),
        employees_path=_employees_path(env),
        service_name=_service_name(env),
        slo_p95_ms=_positive_int(env, "SLO_P95_MS", DEFAULT_SLO_P95_MS),
        langsmith_tracing=tracing,
        hide_inputs=_boolean(env, "HIDE_INPUTS", DEFAULT_HIDE_CONTENT),
        hide_outputs=_boolean(env, "HIDE_OUTPUTS", DEFAULT_HIDE_CONTENT),
        langsmith_enabled=tracing and _has_langsmith_key(env),
        prices_path=prices_path,
        **_cloudflare(env, provider),
        **_models(env, prices_path),
        **_cost_levers(env),
        **_access(env),
        **_operations(env),
    )
