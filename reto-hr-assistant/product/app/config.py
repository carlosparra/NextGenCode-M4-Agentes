"""Configuración del HR Assistant a partir de variables de entorno."""

import hmac
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

PRODUCT_ROOT = Path(__file__).resolve().parent.parent
SUPPORTED_PROVIDERS = ("fake", "gateway")
DEFAULTS = {
    "MODEL_PROVIDER": "fake",
    "AGENT_MAX_STEPS": "3",
    "MAX_QUESTION_CHARS": "2000",
    "EMPLOYEES_PATH": "data/employees.json",
    "SERVICE_NAME": "hr-assistant",
    "SLO_P95_MS": "2000",
    "LANGSMITH_TRACING": "false",
    "HIDE_INPUTS": "true",
    "HIDE_OUTPUTS": "true",
    "CF_ACCOUNT_ID": "",
    "CF_GATEWAY_ID": "default",
    "CF_API_TOKEN": "",
    "MODEL_SMALL": "@cf/meta/llama-3.1-8b-instruct-fast",
    "MODEL_LARGE": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "ROUTING": "true",
    "ROUTER_MAX_CHARS": "80",
    "HISTORY_WINDOW": "6",
    "MODEL_MAX_TOKENS": "300",
    "MODEL_TEMPERATURE": "0",
    "CACHE_TTL_SECONDS": "0",
    "PRICES_PATH": "data/model_prices.json",
    "ENVIRONMENT": "development",
    "API_KEYS": "",
    "RATE_LIMIT_PER_MINUTE": "30",
    "PII_REDACTION": "true",
    "MAX_ANSWER_CHARS": "1500",
}
SUPPORTED_ENVIRONMENTS = ("development", "production")
API_KEYS_ENTRY_SEPARATOR = ","
API_KEYS_PAIR_SEPARATOR = ":"
BOOLEAN_VALUES = {"true": True, "false": False}
API_KEY_VARIABLE = "LANGSMITH_API_KEY"
GATEWAY_REQUIRED = ("CF_ACCOUNT_ID", "CF_GATEWAY_ID", "CF_API_TOKEN")


class ConfigError(ValueError):
    """Error de configuración que impide arrancar la aplicación."""


class Secret:
    """Valor secreto que nunca aparece en ``repr`` ni en ``str``.

    :param value: Valor real del secreto
    :type value: str
    """

    __slots__ = ("_value",)

    def __init__(self, value: str = ""):
        self._value = value

    def reveal(self) -> str:
        """Devuelve el valor real; solo para armar el encabezado de la llamada.

        :return: Valor del secreto
        :rtype: str
        """
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other) -> bool:
        return isinstance(other, Secret) and other.reveal() == self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __repr__(self) -> str:
        return "Secret('***')" if self._value else "Secret('')"

    __str__ = __repr__


@dataclass(frozen=True)
class GatewaySettings:
    """Parámetros de las llamadas a Workers AI a través de AI Gateway.

    :param account_id: Id de la cuenta de Cloudflare (``CF_ACCOUNT_ID``)
    :type account_id: str
    :param gateway_id: Id del gateway (``CF_GATEWAY_ID``)
    :type gateway_id: str
    :param api_token: Token de la API (``CF_API_TOKEN``), nunca visible en ``repr``
    :type api_token: Secret
    :param max_tokens: Tope de tokens de salida por llamada (``MODEL_MAX_TOKENS``)
    :type max_tokens: int
    :param temperature: Temperatura del modelo (``MODEL_TEMPERATURE``)
    :type temperature: float
    :param cache_ttl_seconds: Vida de la caché del gateway; 0 la apaga
    :type cache_ttl_seconds: int
    """

    account_id: str = DEFAULTS["CF_ACCOUNT_ID"]
    gateway_id: str = DEFAULTS["CF_GATEWAY_ID"]
    api_token: Secret = field(default_factory=Secret, repr=False)
    max_tokens: int = int(DEFAULTS["MODEL_MAX_TOKENS"])
    temperature: float = float(DEFAULTS["MODEL_TEMPERATURE"])
    cache_ttl_seconds: int = int(DEFAULTS["CACHE_TTL_SECONDS"])


@dataclass(frozen=True)
class CostSettings:
    """Palancas de costo: modelos, enrutamiento, ventana de historial y precios.

    :param model_small: Modelo barato (``MODEL_SMALL``)
    :type model_small: str
    :param model_large: Modelo capaz (``MODEL_LARGE``)
    :type model_large: str
    :param routing: Si el enrutador elige el modelo por pregunta (``ROUTING``)
    :type routing: bool
    :param router_max_chars: Preguntas más largas van al modelo capaz
    :type router_max_chars: int
    :param history_window: Mensajes de historial que se mandan al modelo
    :type history_window: int
    :param prices_path: Ruta absoluta a la tabla de precios
    :type prices_path: pathlib.Path
    """

    model_small: str = DEFAULTS["MODEL_SMALL"]
    model_large: str = DEFAULTS["MODEL_LARGE"]
    routing: bool = True
    router_max_chars: int = int(DEFAULTS["ROUTER_MAX_CHARS"])
    history_window: int = int(DEFAULTS["HISTORY_WINDOW"])
    prices_path: Path = PRODUCT_ROOT / DEFAULTS["PRICES_PATH"]


@dataclass(frozen=True)
class Settings:  # pylint: disable=too-many-instance-attributes
    """Configuración inmutable de la aplicación.

    Nunca guarda el valor de ``LANGSMITH_API_KEY``: solo si hay trazas o no. El
    token de Cloudflare se guarda como ``Secret`` y no aparece en ``repr``.

    :param model_provider: Proveedor del modelo de lenguaje
    :type model_provider: str
    :param agent_max_steps: Tope de vueltas del bucle del agente
    :type agent_max_steps: int
    :param max_question_chars: Largo máximo de la pregunta
    :type max_question_chars: int
    :param employees_path: Ruta absoluta al archivo de empleados
    :type employees_path: pathlib.Path
    :param service_name: Nombre del servicio en el log
    :type service_name: str
    :param slo_p95_ms: Meta de latencia p95 en milisegundos
    :type slo_p95_ms: int
    :param langsmith_tracing: Valor de ``LANGSMITH_TRACING``
    :type langsmith_tracing: bool
    :param hide_inputs: No mandar entradas a LangSmith
    :type hide_inputs: bool
    :param hide_outputs: No mandar salidas a LangSmith
    :type hide_outputs: bool
    :param tracing_enabled: ``True`` si el tracing está encendido y hay clave
    :type tracing_enabled: bool
    :param gateway: Parámetros de AI Gateway
    :type gateway: GatewaySettings
    :param costs: Palancas de costo
    :type costs: CostSettings
    :param environment: ``development`` o ``production`` (``ENVIRONMENT``)
    :type environment: str
    :param api_keys: Clave de cada cliente (``API_KEYS``), nunca visible en ``repr``
    :type api_keys: dict[str, Secret]
    :param rate_limit_per_minute: Peticiones por cliente por minuto
    :type rate_limit_per_minute: int
    :param pii_redaction: Redactar PII en preguntas y respuestas
        (``PII_REDACTION``)
    :type pii_redaction: bool
    :param max_answer_chars: Largo máximo de la respuesta al cliente
        (``MAX_ANSWER_CHARS``)
    :type max_answer_chars: int
    """

    model_provider: str
    agent_max_steps: int
    max_question_chars: int
    employees_path: Path
    service_name: str = DEFAULTS["SERVICE_NAME"]
    slo_p95_ms: int = int(DEFAULTS["SLO_P95_MS"])
    langsmith_tracing: bool = False
    hide_inputs: bool = True
    hide_outputs: bool = True
    tracing_enabled: bool = False
    gateway: GatewaySettings = field(default_factory=GatewaySettings)
    costs: CostSettings = field(default_factory=CostSettings)
    environment: str = DEFAULTS["ENVIRONMENT"]
    api_keys: dict[str, Secret] = field(default_factory=dict, repr=False)
    rate_limit_per_minute: int = int(DEFAULTS["RATE_LIMIT_PER_MINUTE"])
    pii_redaction: bool = True
    max_answer_chars: int = int(DEFAULTS["MAX_ANSWER_CHARS"])


def _integer(name: str, raw: str, minimum: int) -> int:
    """Convierte un texto en entero mayor o igual que ``minimum``.

    :param name: Nombre de la variable de entorno
    :type name: str
    :param raw: Valor recibido
    :type raw: str
    :param minimum: Valor mínimo aceptado
    :type minimum: int
    :return: Entero validado
    :rtype: int
    :raises ConfigError: Si el valor no es un entero o es menor que ``minimum``
    """
    message = f"{name} must be an integer greater than or equal to {minimum}"
    try:
        value = int(raw.strip())
    except ValueError as error:
        raise ConfigError(f"{message}, got {raw!r}") from error
    if value < minimum:
        raise ConfigError(f"{message}, got {raw!r}")
    return value


def _positive_int(name: str, raw: str) -> int:
    """Convierte un texto en entero mayor que cero.

    :param name: Nombre de la variable de entorno
    :type name: str
    :param raw: Valor recibido
    :type raw: str
    :return: Entero positivo
    :rtype: int
    :raises ConfigError: Si el valor no es un entero mayor que cero
    """
    try:
        value = int(raw.strip())
    except ValueError as error:
        raise ConfigError(
            f"{name} must be an integer greater than 0, got {raw!r}"
        ) from error
    if value <= 0:
        raise ConfigError(f"{name} must be an integer greater than 0, got {raw!r}")
    return value


def _non_negative_float(name: str, raw: str) -> float:
    """Convierte un texto en número real finito mayor o igual que cero.

    :param name: Nombre de la variable de entorno
    :type name: str
    :param raw: Valor recibido
    :type raw: str
    :return: Número validado
    :rtype: float
    :raises ConfigError: Si el valor no es numérico, no es finito o es negativo
    """
    message = f"{name} must be a number greater than or equal to 0, got {raw!r}"
    try:
        value = float(raw.strip())
    except ValueError as error:
        raise ConfigError(message) from error
    if not math.isfinite(value) or value < 0:
        raise ConfigError(message)
    return value


def _boolean(name: str, raw: str) -> bool:
    """Convierte ``true`` o ``false`` (sin importar mayúsculas) en booleano.

    :param name: Nombre de la variable de entorno
    :type name: str
    :param raw: Valor recibido
    :type raw: str
    :return: Valor booleano
    :rtype: bool
    :raises ConfigError: Si el valor no es ``true`` ni ``false``
    """
    value = raw.strip().lower()
    if value not in BOOLEAN_VALUES:
        raise ConfigError(f"{name} must be 'true' or 'false', got {raw!r}")
    return BOOLEAN_VALUES[value]


def _non_empty(name: str, raw: str) -> str:
    """Quita espacios y exige que el texto no quede vacío.

    :param name: Nombre de la variable de entorno
    :type name: str
    :param raw: Valor recibido
    :type raw: str
    :return: Texto sin espacios en los extremos
    :rtype: str
    :raises ConfigError: Si el valor está vacío
    """
    value = raw.strip()
    if not value:
        raise ConfigError(f"{name} must not be empty")
    return value


def _load_tracing(environ: Mapping[str, str]) -> dict:
    """Lee la configuración de trazas sin guardar el valor de la clave.

    :param environ: Variables de entorno
    :type environ: collections.abc.Mapping
    :return: Campos de trazas para ``Settings``
    :rtype: dict
    :raises ConfigError: Si algún booleano no es ``true`` ni ``false``
    """
    values = {
        name: _boolean(name, environ.get(name, DEFAULTS[name]))
        for name in ("LANGSMITH_TRACING", "HIDE_INPUTS", "HIDE_OUTPUTS")
    }
    has_key = bool(environ.get(API_KEY_VARIABLE, "").strip())
    return {
        "langsmith_tracing": values["LANGSMITH_TRACING"],
        "hide_inputs": values["HIDE_INPUTS"],
        "hide_outputs": values["HIDE_OUTPUTS"],
        "tracing_enabled": values["LANGSMITH_TRACING"] and has_key,
    }


def _load_gateway(environ: Mapping[str, str], provider: str) -> GatewaySettings:
    """Lee los parámetros de AI Gateway.

    Con ``MODEL_PROVIDER=gateway`` las tres variables ``CF_*`` son obligatorias.
    Los mensajes de error nombran la variable, nunca el valor del token.

    :param environ: Variables de entorno
    :type environ: collections.abc.Mapping
    :param provider: Proveedor ya validado
    :type provider: str
    :return: Parámetros del gateway
    :rtype: GatewaySettings
    :raises ConfigError: Si falta una variable ``CF_*`` o algún valor no sirve
    """
    values = {
        name: environ.get(name, DEFAULTS[name]).strip() for name in GATEWAY_REQUIRED
    }
    if provider == "gateway":
        for name in GATEWAY_REQUIRED:
            if not values[name]:
                raise ConfigError(f"{name} is required when MODEL_PROVIDER=gateway")

    def get(name: str) -> str:
        return environ.get(name, DEFAULTS[name])

    return GatewaySettings(
        account_id=values["CF_ACCOUNT_ID"],
        gateway_id=values["CF_GATEWAY_ID"],
        api_token=Secret(values["CF_API_TOKEN"]),
        max_tokens=_positive_int("MODEL_MAX_TOKENS", get("MODEL_MAX_TOKENS")),
        temperature=_non_negative_float(
            "MODEL_TEMPERATURE", get("MODEL_TEMPERATURE")
        ),
        cache_ttl_seconds=_integer(
            "CACHE_TTL_SECONDS", get("CACHE_TTL_SECONDS"), minimum=0
        ),
    )


def _load_costs(environ: Mapping[str, str]) -> CostSettings:
    """Lee las palancas de costo.

    :param environ: Variables de entorno
    :type environ: collections.abc.Mapping
    :return: Palancas de costo validadas
    :rtype: CostSettings
    :raises ConfigError: Si algún valor no sirve o falta el archivo de precios
    """

    def get(name: str) -> str:
        return environ.get(name, DEFAULTS[name])

    prices_path = _resolve_path(get("PRICES_PATH"))
    if not prices_path.is_file():
        raise ConfigError(f"PRICES_PATH points to a missing file: {prices_path}")
    return CostSettings(
        model_small=_non_empty("MODEL_SMALL", get("MODEL_SMALL")),
        model_large=_non_empty("MODEL_LARGE", get("MODEL_LARGE")),
        routing=_boolean("ROUTING", get("ROUTING")),
        router_max_chars=_positive_int("ROUTER_MAX_CHARS", get("ROUTER_MAX_CHARS")),
        history_window=_integer("HISTORY_WINDOW", get("HISTORY_WINDOW"), minimum=0),
        prices_path=prices_path,
    )


def _api_keys_error(index: int, entry: str, problem: str) -> ConfigError:
    """Arma el error de una entrada de ``API_KEYS`` sin incluir su valor.

    Solo dice el número de la entrada (desde 1) y su largo.

    :param index: Número de la entrada, empezando en 1
    :type index: int
    :param entry: Entrada sin espacios en los extremos; solo se usa su largo
    :type entry: str
    :param problem: Qué falla en la entrada
    :type problem: str
    :return: Error listo para lanzar
    :rtype: ConfigError
    """
    return ConfigError(
        f"API_KEYS entry {index} ({len(entry)} characters) {problem}; "
        "expected client:key separated by commas"
    )


def _key_already_used(key: str, keys: Mapping[str, Secret]) -> bool:
    """Indica si la clave ya es de otro cliente; compara en tiempo constante.

    :param key: Clave nueva
    :type key: str
    :param keys: Claves ya leídas por cliente
    :type keys: collections.abc.Mapping
    :return: ``True`` si alguna clave leída es igual
    :rtype: bool
    """
    candidate = key.encode("utf-8")
    matches = [
        hmac.compare_digest(candidate, secret.reveal().encode("utf-8"))
        for secret in keys.values()
    ]
    return any(matches)


def parse_api_keys(raw: str) -> dict[str, Secret]:
    """Lee ``API_KEYS`` con la forma ``cliente:clave,cliente2:clave2``.

    Los espacios alrededor de cada cliente y cada clave se ignoran. Una variable
    vacía da un diccionario vacío. Los errores nunca muestran una clave.

    :param raw: Valor de ``API_KEYS``
    :type raw: str
    :return: Clave de cada cliente
    :rtype: dict[str, Secret]
    :raises ConfigError: Si una entrada está vacía, no tiene ``:``, le falta el
        cliente o la clave, o repite un cliente o una clave
    """
    keys: dict[str, Secret] = {}
    if not raw.strip():
        return keys
    entries = raw.split(API_KEYS_ENTRY_SEPARATOR)
    for index, raw_entry in enumerate(entries, start=1):
        entry = raw_entry.strip()
        client, separator, key = entry.partition(API_KEYS_PAIR_SEPARATOR)
        client, key = client.strip(), key.strip()
        if not separator or not client or not key:
            raise _api_keys_error(index, entry, "is not client:key")
        if client in keys:
            raise _api_keys_error(index, entry, "repeats a client")
        if _key_already_used(key, keys):
            raise _api_keys_error(index, entry, "repeats a key")
        keys[client] = Secret(key)
    return keys


def _load_access(environ: Mapping[str, str]) -> dict:
    """Lee el entorno de ejecución, las claves por cliente y el límite por minuto.

    :param environ: Variables de entorno
    :type environ: collections.abc.Mapping
    :return: Campos de acceso para ``Settings``
    :rtype: dict
    :raises ConfigError: Si ``ENVIRONMENT``, ``API_KEYS`` o
        ``RATE_LIMIT_PER_MINUTE`` no sirven
    """

    def get(name: str) -> str:
        return environ.get(name, DEFAULTS[name])

    environment = get("ENVIRONMENT").strip().lower()
    if environment not in SUPPORTED_ENVIRONMENTS:
        raise ConfigError(
            f"ENVIRONMENT must be one of {', '.join(SUPPORTED_ENVIRONMENTS)}, "
            f"got {get('ENVIRONMENT')!r}"
        )
    return {
        "environment": environment,
        "api_keys": parse_api_keys(get("API_KEYS")),
        "rate_limit_per_minute": _positive_int(
            "RATE_LIMIT_PER_MINUTE", get("RATE_LIMIT_PER_MINUTE")
        ),
    }


def _load_pii(environ: Mapping[str, str]) -> dict:
    """Lee la redacción de PII y el largo máximo de la respuesta.

    :param environ: Variables de entorno
    :type environ: collections.abc.Mapping
    :return: Campos de PII para ``Settings``
    :rtype: dict
    :raises ConfigError: Si ``PII_REDACTION`` no es booleano o
        ``MAX_ANSWER_CHARS`` no es un entero mayor que cero
    """

    def get(name: str) -> str:
        return environ.get(name, DEFAULTS[name])

    return {
        "pii_redaction": _boolean("PII_REDACTION", get("PII_REDACTION")),
        "max_answer_chars": _positive_int(
            "MAX_ANSWER_CHARS", get("MAX_ANSWER_CHARS")
        ),
    }


def _resolve_path(raw: str) -> Path:
    """Resuelve una ruta relativa contra la raíz de ``product/``.

    :param raw: Ruta recibida
    :type raw: str
    :return: Ruta absoluta
    :rtype: pathlib.Path
    """
    path = Path(raw)
    if not path.is_absolute():
        path = PRODUCT_ROOT / path
    return path.resolve()


def load_settings(environ: Mapping[str, str]) -> Settings:
    """Lee y valida la configuración.

    :param environ: Variables de entorno (por ejemplo ``os.environ``)
    :type environ: collections.abc.Mapping
    :return: Configuración validada
    :rtype: Settings
    :raises ConfigError: Si algún valor no sirve; el mensaje nombra la variable
    """

    def get(name: str) -> str:
        return environ.get(name, DEFAULTS[name])

    provider = get("MODEL_PROVIDER").strip()
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(
            f"MODEL_PROVIDER must be one of {', '.join(SUPPORTED_PROVIDERS)}, "
            f"got {provider!r}"
        )
    max_steps = _positive_int("AGENT_MAX_STEPS", get("AGENT_MAX_STEPS"))
    max_chars = _positive_int("MAX_QUESTION_CHARS", get("MAX_QUESTION_CHARS"))
    employees_path = _resolve_path(get("EMPLOYEES_PATH"))
    if not employees_path.is_file():
        raise ConfigError(f"EMPLOYEES_PATH points to a missing file: {employees_path}")
    service_name = get("SERVICE_NAME").strip()
    if not service_name:
        raise ConfigError("SERVICE_NAME must not be empty")
    return Settings(
        model_provider=provider,
        agent_max_steps=max_steps,
        max_question_chars=max_chars,
        employees_path=employees_path,
        service_name=service_name,
        slo_p95_ms=_positive_int("SLO_P95_MS", get("SLO_P95_MS")),
        **_load_tracing(environ),
        gateway=_load_gateway(environ, provider),
        costs=_load_costs(environ),
        **_load_access(environ),
        **_load_pii(environ),
    )
