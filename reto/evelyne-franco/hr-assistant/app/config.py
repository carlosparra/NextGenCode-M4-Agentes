"""Configuracion de la aplicacion HR Assistant.

Lee variables de entorno, valida valores y expone la
configuracion como un objeto inmutable Pydantic. Desde la sesion 4
guarda el entorno, el limite por minuto y las claves por cliente
(``API_KEYS``, interpretada por ``app.auth`` y guardada como
``SecretStr``). ``app.tracing``
decide las trazas con ``langsmith_tracing``, ``hide_inputs`` y
``hide_outputs`` de aqui. La clave de LangSmith nunca se guarda aqui:
``app.tracing`` solo revisa en el entorno si existe. El token de
Cloudflare se guarda como ``SecretStr`` y no aparece en ``repr``.
Desde el reto de seguridad guarda ``MAX_ANSWER_CHARS`` y expone
``secret_values()`` para que la respuesta nunca muestre un secreto.

:seealso: ``spec/01-architecture.md``, ``spec/02-observability.md`` y
    ``spec/03-costs.md``
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, SecretStr, field_validator, model_validator

from app.auth import ApiKey, parse_api_keys

TRUE_VALUES = {"true", "1", "yes"}
FALSE_VALUES = {"false", "0", "no"}
PROVIDER_FAKE = "fake"
PROVIDER_GATEWAY = "gateway"
PROVIDERS = (PROVIDER_FAKE, PROVIDER_GATEWAY)
ENVIRONMENT_DEVELOPMENT = "development"
ENVIRONMENT_PRODUCTION = "production"
ENVIRONMENTS = (ENVIRONMENT_DEVELOPMENT, ENVIRONMENT_PRODUCTION)


class Settings(BaseModel, frozen=True):
    """Configuracion inmutable de la aplicacion.

    Los valores por omision coinciden con la especificacion.
    Un valor invalido (por ejemplo ``agent_max_steps=0``)
    lanza un ``ValueError`` al instanciar.

    :param model_provider: Proveedor del modelo de lenguaje.
    :type model_provider: str
    :param agent_max_steps: Tope de pasos del bucle del agente.
    :type agent_max_steps: int
    :param max_question_chars: Largo maximo de la pregunta.
    :type max_question_chars: int
    :param employees_path: Ruta al archivo de empleados.
    :type employees_path: str
    :param service_name: Campo ``service`` del log.
    :type service_name: str
    :param slo_p95_ms: Meta de latencia p95 en milisegundos.
    :type slo_p95_ms: int
    :param langsmith_tracing: Enciende las trazas en LangSmith.
    :type langsmith_tracing: bool
    :param hide_inputs: No mandar entradas a LangSmith.
    :type hide_inputs: bool
    :param hide_outputs: No mandar salidas a LangSmith.
    :type hide_outputs: bool
    :param cf_account_id: Cuenta de Cloudflare.
    :type cf_account_id: str
    :param cf_gateway_id: Id del AI Gateway.
    :type cf_gateway_id: str
    :param cf_api_token: Token de Cloudflare (secreto, nunca se imprime).
    :type cf_api_token: pydantic.SecretStr
    :param model_small: Modelo barato.
    :type model_small: str
    :param model_large: Modelo capaz.
    :type model_large: str
    :param routing: Enrutamiento por pregunta (palanca 1).
    :type routing: bool
    :param router_max_chars: Preguntas mas largas van al modelo capaz.
    :type router_max_chars: int
    :param history_window: Mensajes de historial que se mandan
        (palanca 2); 0 no manda ninguno.
    :type history_window: int
    :param model_max_tokens: Tope de tokens de salida (palanca 3).
    :type model_max_tokens: int
    :param model_temperature: Temperatura del modelo.
    :type model_temperature: float
    :param cache_ttl_seconds: TTL de la cache del gateway (palanca 4);
        0 la apaga.
    :type cache_ttl_seconds: int
    :param prices_path: Ruta a los precios por modelo.
    :type prices_path: str
    :param environment: ``development`` o ``production``; con
        ``production`` se aplican las reglas de ``app.compliance``.
    :type environment: str
    :param api_keys: Clientes y claves (las claves son ``SecretStr``).
    :type api_keys: tuple[app.auth.ApiKey, ...]
    :param rate_limit_per_minute: Peticiones por cliente por minuto.
    :type rate_limit_per_minute: int
    :param max_answer_chars: Largo maximo de la respuesta (reto de
        seguridad reforzada).
    :type max_answer_chars: int
    :param policies_path: Ruta a las politicas de RH (spec 06).
    :type policies_path: str
    """

    model_provider: str = "fake"
    agent_max_steps: int = 3
    max_question_chars: int = 2000
    employees_path: str = "data/employees.json"
    service_name: str = "hr-assistant"
    slo_p95_ms: int = 2000
    langsmith_tracing: bool = False
    hide_inputs: bool = True
    hide_outputs: bool = True
    cf_account_id: str = ""
    cf_gateway_id: str = "default"
    cf_api_token: SecretStr = SecretStr("")
    model_small: str = "@cf/meta/llama-3.1-8b-instruct-fast"
    model_large: str = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    routing: bool = True
    router_max_chars: int = 80
    history_window: int = 6
    model_max_tokens: int = 300
    model_temperature: float = 0
    cache_ttl_seconds: int = 0
    prices_path: str = "data/model_prices.json"
    environment: str = ENVIRONMENT_DEVELOPMENT
    api_keys: tuple[ApiKey, ...] = ()
    rate_limit_per_minute: int = 30
    max_answer_chars: int = 2000
    # Spec 06: no es configuracion nueva (no hay variable de entorno); es
    # la ruta fija de las politicas, como la de los empleados.
    policies_path: str = "data/policies.json"

    def secret_values(self) -> tuple[str, ...]:
        """Devuelve los secretos que nunca deben salir en una respuesta.

        Son las claves de ``API_KEYS`` y ``CF_API_TOKEN``, sin vacios.
        Solo los usa ``app.guardrails.validate_answer``; nunca van a
        ``repr``, al log ni a un mensaje de error.

        :return: Valores secretos no vacios.
        :rtype: tuple[str, ...]
        """
        values = [item.key.get_secret_value() for item in self.api_keys]
        values.append(self.cf_api_token.get_secret_value())
        return tuple(value for value in values if value)

    @field_validator("environment")
    @classmethod
    def _known_environment(cls, value: str) -> str:
        """Valida que el entorno sea conocido.

        :param value: Entorno recibido.
        :type value: str
        :return: El entorno validado.
        :rtype: str
        :raises ValueError: Si no es ``development`` ni ``production``.
        """
        if value not in ENVIRONMENTS:
            raise ValueError(
                f"ENVIRONMENT debe ser uno de {', '.join(ENVIRONMENTS)}, "
                f"se recibio: {value!r}"
            )
        return value

    @field_validator("model_provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        """Valida que el proveedor del modelo sea conocido.

        :param value: Proveedor recibido.
        :type value: str
        :return: El proveedor validado.
        :rtype: str
        :raises ValueError: Si no es ``fake`` ni ``gateway``.
        """
        if value not in PROVIDERS:
            raise ValueError(
                f"MODEL_PROVIDER debe ser uno de {', '.join(PROVIDERS)}, "
                f"se recibio: {value!r}"
            )
        return value

    @field_validator("history_window", "cache_ttl_seconds", "model_temperature")
    @classmethod
    def _must_not_be_negative(cls, value: float, info) -> float:
        """Valida que el numero de configuracion no sea negativo.

        :param value: Valor a validar.
        :type value: float
        :param info: Informacion de Pydantic sobre el campo.
        :type info: pydantic.ValidationInfo
        :return: El valor validado.
        :rtype: float
        :raises ValueError: Si el valor es menor que 0.
        """
        if value < 0:
            raise ValueError(
                f"{info.field_name.upper()} no puede ser negativo, "
                f"se recibio: {value}"
            )
        return value

    @model_validator(mode="after")
    def _gateway_needs_cloudflare(self) -> Settings:
        """Con ``gateway`` exige las tres variables ``CF_*``.

        :return: La configuracion validada.
        :rtype: Settings
        :raises ValueError: Si falta alguna; el mensaje la nombra (sin
            mostrar el valor del token).
        """
        if self.model_provider != PROVIDER_GATEWAY:
            return self
        values = {
            "CF_ACCOUNT_ID": self.cf_account_id,
            "CF_GATEWAY_ID": self.cf_gateway_id,
            "CF_API_TOKEN": self.cf_api_token.get_secret_value(),
        }
        missing = [name for name, value in values.items() if not value.strip()]
        if missing:
            raise ValueError(
                f"Con MODEL_PROVIDER=gateway falta: {', '.join(missing)}"
            )
        return self

    @field_validator(
        "agent_max_steps",
        "max_question_chars",
        "slo_p95_ms",
        "router_max_chars",
        "model_max_tokens",
        "rate_limit_per_minute",
        "max_answer_chars",
    )
    @classmethod
    def _must_be_positive(cls, value: int, info) -> int:
        """Valida que los numeros de configuracion sean positivos.

        :param value: Valor a validar.
        :type value: int
        :param info: Informacion de Pydantic sobre el campo.
        :type info: pydantic.ValidationInfo
        :return: El valor validado.
        :rtype: int
        :raises ValueError: Si el valor es menor o igual a 0.
        """
        if value <= 0:
            raise ValueError(
                f"{info.field_name.upper()} debe ser mayor que 0, "
                f"se recibio: {value}"
            )
        return value


def _read_int(environ: Mapping[str, str], name: str, default: int) -> int:
    """Lee un entero del entorno con un mensaje claro si es invalido.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping[str, str]
    :param name: Nombre de la variable.
    :type name: str
    :param default: Valor si la variable no existe.
    :type default: int
    :return: El entero leido.
    :rtype: int
    :raises ValueError: Si el texto no es un entero.
    """
    raw = environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ValueError(
            f"{name} debe ser un numero entero, se recibio: {raw!r}"
        ) from exc


def _read_float(environ: Mapping[str, str], name: str, default: float) -> float:
    """Lee un numero decimal del entorno con un mensaje claro si es invalido.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping[str, str]
    :param name: Nombre de la variable.
    :type name: str
    :param default: Valor si la variable no existe.
    :type default: float
    :return: El numero leido.
    :rtype: float
    :raises ValueError: Si el texto no es un numero.
    """
    raw = environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ValueError(
            f"{name} debe ser un numero, se recibio: {raw!r}"
        ) from exc


def _read_bool(environ: Mapping[str, str], name: str, default: bool) -> bool:
    """Lee un booleano (``true``/``false``) del entorno.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping[str, str]
    :param name: Nombre de la variable.
    :type name: str
    :param default: Valor si la variable no existe.
    :type default: bool
    :return: El booleano leido.
    :rtype: bool
    :raises ValueError: Si el texto no es ``true`` ni ``false``.
    """
    raw = environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    text = raw.strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    raise ValueError(f"{name} debe ser true o false, se recibio: {raw!r}")


def load_settings(environ: Mapping[str, str]) -> Settings:
    """Construye la configuracion a partir de variables de entorno.

    Falla al arrancar, con un mensaje claro, si un valor es invalido.
    ``LANGSMITH_API_KEY`` se ignora a proposito: no se guarda.
    ``CF_API_TOKEN`` se guarda como ``SecretStr``.

    :param environ: Variables de entorno (por ejemplo ``os.environ``).
    :type environ: collections.abc.Mapping[str, str]
    :return: Configuracion validada.
    :rtype: Settings
    :raises ValueError: Si algun valor es invalido.
    """
    defaults = Settings()
    return Settings(
        **_base_values(environ, defaults),
        **_cost_values(environ, defaults),
        **_production_values(environ, defaults),
    )


def _production_values(environ: Mapping[str, str], defaults: Settings) -> dict:
    """Lee las variables de la sesion 4 (entorno, claves y limite).

    ``API_KEYS`` se interpreta aqui, fuera de Pydantic, con
    ``app.auth.parse_api_keys``: asi un error nunca trae el valor
    (Pydantic incluiria ``input_value`` en su mensaje).

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping[str, str]
    :param defaults: Configuracion por omision.
    :type defaults: Settings
    :return: Valores leidos, por nombre de campo.
    :rtype: dict
    :raises ValueError: Si ``API_KEYS`` esta mal formada (sin mostrar
        su valor) o el limite no es un entero.
    """
    return {
        "environment": environ.get("ENVIRONMENT", defaults.environment).strip(),
        "api_keys": parse_api_keys(environ.get("API_KEYS", "")),
        "rate_limit_per_minute": _read_int(
            environ, "RATE_LIMIT_PER_MINUTE", defaults.rate_limit_per_minute
        ),
        "max_answer_chars": _read_int(
            environ, "MAX_ANSWER_CHARS", defaults.max_answer_chars
        ),
    }


def _cost_values(environ: Mapping[str, str], defaults: Settings) -> dict:
    """Lee las variables de la sesion 3 (modelo real y palancas).

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping[str, str]
    :param defaults: Configuracion por omision.
    :type defaults: Settings
    :return: Valores leidos, por nombre de campo.
    :rtype: dict
    :raises ValueError: Si algun numero o booleano es invalido.
    """
    return {
        "cf_account_id": environ.get("CF_ACCOUNT_ID", defaults.cf_account_id),
        "cf_gateway_id": environ.get("CF_GATEWAY_ID", defaults.cf_gateway_id),
        "cf_api_token": SecretStr(environ.get("CF_API_TOKEN", "")),
        "model_small": environ.get("MODEL_SMALL", defaults.model_small),
        "model_large": environ.get("MODEL_LARGE", defaults.model_large),
        "routing": _read_bool(environ, "ROUTING", defaults.routing),
        "router_max_chars": _read_int(
            environ, "ROUTER_MAX_CHARS", defaults.router_max_chars
        ),
        "history_window": _read_int(
            environ, "HISTORY_WINDOW", defaults.history_window
        ),
        "model_max_tokens": _read_int(
            environ, "MODEL_MAX_TOKENS", defaults.model_max_tokens
        ),
        "model_temperature": _read_float(
            environ, "MODEL_TEMPERATURE", defaults.model_temperature
        ),
        "cache_ttl_seconds": _read_int(
            environ, "CACHE_TTL_SECONDS", defaults.cache_ttl_seconds
        ),
        "prices_path": environ.get("PRICES_PATH", defaults.prices_path),
    }


def _base_values(environ: Mapping[str, str], defaults: Settings) -> dict:
    """Lee las variables de las sesiones 1 y 2.

    :param environ: Variables de entorno.
    :type environ: collections.abc.Mapping[str, str]
    :param defaults: Configuracion por omision.
    :type defaults: Settings
    :return: Valores leidos, por nombre de campo.
    :rtype: dict
    :raises ValueError: Si algun numero o booleano es invalido.
    """
    return {
        "model_provider": environ.get("MODEL_PROVIDER", defaults.model_provider),
        "employees_path": environ.get("EMPLOYEES_PATH", defaults.employees_path),
        "agent_max_steps": _read_int(
            environ, "AGENT_MAX_STEPS", defaults.agent_max_steps
        ),
        "max_question_chars": _read_int(
            environ, "MAX_QUESTION_CHARS", defaults.max_question_chars
        ),
        "service_name": environ.get("SERVICE_NAME", defaults.service_name),
        "slo_p95_ms": _read_int(environ, "SLO_P95_MS", defaults.slo_p95_ms),
        "langsmith_tracing": _read_bool(
            environ, "LANGSMITH_TRACING", defaults.langsmith_tracing
        ),
        "hide_inputs": _read_bool(environ, "HIDE_INPUTS", defaults.hide_inputs),
        "hide_outputs": _read_bool(environ, "HIDE_OUTPUTS", defaults.hide_outputs),
    }
