"""Configuración del HR Assistant leída de variables de entorno.

La configuración se valida completa al arrancar (ADR 0004): un valor inválido
lanza :class:`ConfigError` con un mensaje que nombra la variable. Con
``MODEL_PROVIDER=gateway`` las tres variables ``CF_*`` son obligatorias
(ADR 0006). El token de Cloudflare y la clave de LangSmith nunca aparecen en
``repr``.

Desde la sesión 4 lee ``ENVIRONMENT``, ``API_KEYS`` y
``RATE_LIMIT_PER_MINUTE`` (ADR 0009 a 0011). Las claves de ``API_KEYS`` nunca
aparecen en ``repr`` ni en un error. Con ``ENVIRONMENT=production`` se aplican
las reglas de :mod:`app.compliance` y, si alguna falla, no se arranca.
"""

from dataclasses import dataclass, field
from typing import Mapping

from app.auth import ApiKeys, parse_api_keys
from app.compliance import check_production
from app.errors import ConfigError

__all__ = ["Config", "ConfigError", "load_config"]

SUPPORTED_PROVIDERS = ("fake", "gateway")
SUPPORTED_ENVIRONMENTS = ("development", "production")
DEFAULT_ENVIRONMENT = "development"
PRODUCTION_ENVIRONMENT = "production"
DEFAULT_RATE_LIMIT_PER_MINUTE = 30
DEFAULT_MODEL_PROVIDER = "fake"
DEFAULT_AGENT_MAX_STEPS = 3
DEFAULT_MAX_QUESTION_CHARS = 2000
DEFAULT_EMPLOYEES_PATH = "data/employees.json"
DEFAULT_SERVICE_NAME = "hr-assistant"
DEFAULT_SLO_P95_MS = 2000
DEFAULT_CF_GATEWAY_ID = "default"
DEFAULT_MODEL_SMALL = "@cf/meta/llama-3.1-8b-instruct-fast"
DEFAULT_MODEL_LARGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
DEFAULT_ROUTING = True
DEFAULT_ROUTER_MAX_CHARS = 80
DEFAULT_HISTORY_WINDOW = 6
DEFAULT_MODEL_MAX_TOKENS = 300
DEFAULT_MODEL_TEMPERATURE = 0.0
MAX_MODEL_TEMPERATURE = 2.0
DEFAULT_CACHE_TTL_SECONDS = 0
DEFAULT_PRICES_PATH = "data/model_prices.json"
DEFAULT_LANGSMITH_TRACING = False
DEFAULT_HIDE_INPUTS = True
DEFAULT_HIDE_OUTPUTS = True
GATEWAY_VARIABLES = ("CF_ACCOUNT_ID", "CF_GATEWAY_ID", "CF_API_TOKEN")
TRUE_VALUES = ("true", "1", "yes", "on")
FALSE_VALUES = ("false", "0", "no", "off")


@dataclass(frozen=True)
class Config:  # pylint: disable=too-many-instance-attributes
    """Configuración validada del asistente.

    :param model_provider: Proveedor del modelo (``fake`` o ``gateway``)
    :type model_provider: str
    :param agent_max_steps: Tope de vueltas del bucle del agente
    :type agent_max_steps: int
    :param max_question_chars: Largo máximo de la pregunta
    :type max_question_chars: int
    :param employees_path: Ruta del archivo JSON de empleados
    :type employees_path: str
    :param service_name: Campo ``service`` de cada línea del log
    :type service_name: str
    :param slo_p95_ms: Meta de latencia p95 en milisegundos
    :type slo_p95_ms: int
    :param cf_account_id: Cuenta de Cloudflare
    :type cf_account_id: str
    :param cf_gateway_id: Id del AI Gateway
    :type cf_gateway_id: str
    :param model_small: Nombre del modelo barato
    :type model_small: str
    :param model_large: Nombre del modelo capaz
    :type model_large: str
    :param routing: Si el enrutador elige el modelo por pregunta
    :type routing: bool
    :param router_max_chars: Preguntas más largas van al modelo capaz
    :type router_max_chars: int
    :param history_window: Mensajes de historial que se mandan al modelo
    :type history_window: int
    :param model_max_tokens: Tope de tokens de salida por llamada
    :type model_max_tokens: int
    :param model_temperature: Temperatura del modelo, entre 0 y 2
    :type model_temperature: float
    :param cache_ttl_seconds: Vida de la caché del gateway (0: apagada)
    :type cache_ttl_seconds: int
    :param prices_path: Ruta del archivo JSON de precios por modelo
    :type prices_path: str
    :param langsmith_tracing: Si se mandan trazas a LangSmith
    :type langsmith_tracing: bool
    :param hide_inputs: Si las trazas ocultan las entradas
    :type hide_inputs: bool
    :param hide_outputs: Si las trazas ocultan las salidas
    :type hide_outputs: bool
    :param cf_api_token: Token secreto de Cloudflare; no sale en ``repr``
    :type cf_api_token: str
    :param langsmith_api_key: Clave secreta de LangSmith; no sale en ``repr``
    :type langsmith_api_key: str
    :param environment: ``development`` o ``production``
    :type environment: str
    :param rate_limit_per_minute: Peticiones por cliente por minuto
    :type rate_limit_per_minute: int
    :param api_keys: Clave secreta de cada cliente; no sale en ``repr``
    :type api_keys: app.auth.ApiKeys
    """

    model_provider: str
    agent_max_steps: int
    max_question_chars: int
    employees_path: str
    service_name: str = DEFAULT_SERVICE_NAME
    slo_p95_ms: int = DEFAULT_SLO_P95_MS
    cf_account_id: str = ""
    cf_gateway_id: str = DEFAULT_CF_GATEWAY_ID
    model_small: str = DEFAULT_MODEL_SMALL
    model_large: str = DEFAULT_MODEL_LARGE
    routing: bool = DEFAULT_ROUTING
    router_max_chars: int = DEFAULT_ROUTER_MAX_CHARS
    history_window: int = DEFAULT_HISTORY_WINDOW
    model_max_tokens: int = DEFAULT_MODEL_MAX_TOKENS
    model_temperature: float = DEFAULT_MODEL_TEMPERATURE
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    prices_path: str = DEFAULT_PRICES_PATH
    langsmith_tracing: bool = DEFAULT_LANGSMITH_TRACING
    hide_inputs: bool = DEFAULT_HIDE_INPUTS
    hide_outputs: bool = DEFAULT_HIDE_OUTPUTS
    cf_api_token: str = field(default="", repr=False)
    langsmith_api_key: str = field(default="", repr=False)
    environment: str = DEFAULT_ENVIRONMENT
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE
    api_keys: ApiKeys = field(default_factory=ApiKeys, repr=False)


def _raw(environ, name):
    """Lee una variable sin espacios; ``None`` si no está o está vacía.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :return: El valor leído o ``None``
    :rtype: str or None
    """
    raw = environ.get(name)
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw).strip()


def _int(environ, name, default, minimum):
    """Lee un entero mayor o igual que ``minimum``.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión si la variable no está
    :type default: int
    :param minimum: Valor mínimo permitido
    :type minimum: int
    :return: El entero leído
    :rtype: int
    :raises ConfigError: Si el valor no es un entero o es menor que ``minimum``
    """
    raw = _raw(environ, name)
    if raw is None:
        return default
    message = (
        f"{name} debe ser un entero mayor o igual que {minimum}; "
        f"se recibió {raw!r}."
    )
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(message) from error
    if value < minimum:
        raise ConfigError(message)
    return value


def _positive_int(environ, name, default):
    """Lee un entero positivo de ``environ``.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión si la variable no está
    :type default: int
    :return: El entero leído
    :rtype: int
    :raises ConfigError: Si el valor no es un entero mayor que cero
    """
    return _int(environ, name, default, 1)


def _bool(environ, name, default):
    """Lee un booleano (``true``/``false``, ``1``/``0``, ``yes``/``no``).

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión si la variable no está
    :type default: bool
    :return: El booleano leído
    :rtype: bool
    :raises ConfigError: Si el valor no es un booleano reconocible
    """
    raw = _raw(environ, name)
    if raw is None:
        return default
    if raw.lower() in TRUE_VALUES:
        return True
    if raw.lower() in FALSE_VALUES:
        return False
    raise ConfigError(f"{name} debe ser true o false; se recibió {raw!r}.")


def _temperature(environ):
    """Lee ``MODEL_TEMPERATURE``, un decimal entre 0 y 2.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :return: La temperatura leída
    :rtype: float
    :raises ConfigError: Si no es un número entre 0 y 2
    """
    raw = _raw(environ, "MODEL_TEMPERATURE")
    if raw is None:
        return DEFAULT_MODEL_TEMPERATURE
    message = (
        f"MODEL_TEMPERATURE debe ser un número entre 0 y {MAX_MODEL_TEMPERATURE:g}; "
        f"se recibió {raw!r}."
    )
    try:
        value = float(raw)
    except ValueError as error:
        raise ConfigError(message) from error
    if not 0 <= value <= MAX_MODEL_TEMPERATURE:
        raise ConfigError(message)
    return value


def _text(environ, name, default):
    """Lee un texto; si no está, usa ``default``.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión
    :type default: str
    :return: El texto leído
    :rtype: str
    """
    raw = _raw(environ, name)
    return default if raw is None else raw


def _provider(environ):
    """Lee y valida ``MODEL_PROVIDER``.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :return: El proveedor en minúsculas
    :rtype: str
    :raises ConfigError: Si el proveedor no está soportado
    """
    provider = _text(environ, "MODEL_PROVIDER", DEFAULT_MODEL_PROVIDER).lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(
            f"MODEL_PROVIDER no soportado: {provider!r}. "
            f"Valores permitidos: {', '.join(SUPPORTED_PROVIDERS)}."
        )
    return provider


def _gateway_settings(environ, provider):
    """Lee las variables ``CF_*``; con ``gateway`` son obligatorias.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :param provider: Proveedor ya validado
    :type provider: str
    :return: Cuenta, gateway y token de Cloudflare
    :rtype: tuple[str, str, str]
    :raises ConfigError: Si falta alguna con ``MODEL_PROVIDER=gateway``
    """
    account = _text(environ, "CF_ACCOUNT_ID", "")
    gateway = _text(environ, "CF_GATEWAY_ID", DEFAULT_CF_GATEWAY_ID)
    token = _text(environ, "CF_API_TOKEN", "")
    if provider == "gateway":
        values = dict(zip(GATEWAY_VARIABLES, (account, gateway, token)))
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ConfigError(
                "Con MODEL_PROVIDER=gateway faltan: " + ", ".join(missing) + "."
            )
    return account, gateway, token


def _required_text(environ, name, default):
    """Lee un texto que no puede quedar vacío.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión
    :type default: str
    :return: El texto leído
    :rtype: str
    :raises ConfigError: Si la variable está presente pero en blanco
    """
    if name in environ and _raw(environ, name) is None:
        raise ConfigError(f"{name} no puede estar vacío.")
    return _text(environ, name, default)


def _environment(environ):
    """Lee y valida ``ENVIRONMENT``.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :return: ``development`` o ``production``
    :rtype: str
    :raises ConfigError: Si el valor no está soportado
    """
    environment = _text(environ, "ENVIRONMENT", DEFAULT_ENVIRONMENT).lower()
    if environment not in SUPPORTED_ENVIRONMENTS:
        raise ConfigError(
            f"ENVIRONMENT no soportado: {environment!r}. "
            f"Valores permitidos: {', '.join(SUPPORTED_ENVIRONMENTS)}."
        )
    return environment


def _enforce_compliance(config):
    """Con ``ENVIRONMENT=production`` aplica las reglas de compliance.

    :param config: Configuración ya leída
    :type config: Config
    :return: La misma configuración si cumple todas las reglas
    :rtype: Config
    :raises ConfigError: Con todas las reglas incumplidas en un solo mensaje
    """
    if config.environment != PRODUCTION_ENVIRONMENT:
        return config
    problems = check_production(config)
    if problems:
        raise ConfigError(
            "ENVIRONMENT=production no cumple las reglas de compliance: "
            + " ".join(problems)
        )
    return config


def load_config(environ: Mapping[str, str]) -> Config:
    """Construye y valida la configuración a partir de ``environ``.

    :param environ: Variables de entorno (por ejemplo ``os.environ``)
    :type environ: Mapping[str, str]
    :return: La configuración validada
    :rtype: Config
    :raises ConfigError: Si algún valor es inválido o, en producción, si se
        incumple alguna regla de compliance
    """
    provider = _provider(environ)
    account, gateway, token = _gateway_settings(environ, provider)
    config = Config(
        model_provider=provider,
        agent_max_steps=_positive_int(
            environ, "AGENT_MAX_STEPS", DEFAULT_AGENT_MAX_STEPS
        ),
        max_question_chars=_positive_int(
            environ, "MAX_QUESTION_CHARS", DEFAULT_MAX_QUESTION_CHARS
        ),
        employees_path=_required_text(
            environ, "EMPLOYEES_PATH", DEFAULT_EMPLOYEES_PATH
        ),
        service_name=_text(environ, "SERVICE_NAME", DEFAULT_SERVICE_NAME),
        slo_p95_ms=_positive_int(environ, "SLO_P95_MS", DEFAULT_SLO_P95_MS),
        cf_account_id=account,
        cf_gateway_id=gateway,
        cf_api_token=token,
        model_small=_text(environ, "MODEL_SMALL", DEFAULT_MODEL_SMALL),
        model_large=_text(environ, "MODEL_LARGE", DEFAULT_MODEL_LARGE),
        routing=_bool(environ, "ROUTING", DEFAULT_ROUTING),
        router_max_chars=_positive_int(
            environ, "ROUTER_MAX_CHARS", DEFAULT_ROUTER_MAX_CHARS
        ),
        history_window=_int(
            environ, "HISTORY_WINDOW", DEFAULT_HISTORY_WINDOW, 0
        ),
        model_max_tokens=_positive_int(
            environ, "MODEL_MAX_TOKENS", DEFAULT_MODEL_MAX_TOKENS
        ),
        model_temperature=_temperature(environ),
        cache_ttl_seconds=_int(
            environ, "CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS, 0
        ),
        prices_path=_required_text(environ, "PRICES_PATH", DEFAULT_PRICES_PATH),
        langsmith_tracing=_bool(
            environ, "LANGSMITH_TRACING", DEFAULT_LANGSMITH_TRACING
        ),
        hide_inputs=_bool(environ, "HIDE_INPUTS", DEFAULT_HIDE_INPUTS),
        hide_outputs=_bool(environ, "HIDE_OUTPUTS", DEFAULT_HIDE_OUTPUTS),
        langsmith_api_key=_text(environ, "LANGSMITH_API_KEY", ""),
        environment=_environment(environ),
        rate_limit_per_minute=_positive_int(
            environ, "RATE_LIMIT_PER_MINUTE", DEFAULT_RATE_LIMIT_PER_MINUTE
        ),
        api_keys=parse_api_keys(_text(environ, "API_KEYS", "")),
    )
    return _enforce_compliance(config)
