"""Reglas de compliance que se revisan al arrancar en producción (ADR 0011).

Cada mensaje nombra la variable y, si aplica, el cliente y el largo de su
clave; nunca incluye una clave.
"""

MIN_API_KEY_CHARS = 16


def _provider_problems(config):
    """Revisa que producción no use el modelo simulado.

    :param config: Configuración validada
    :type config: app.config.Config
    :return: Reglas incumplidas
    :rtype: list[str]
    """
    if config.model_provider == "fake":
        return ["MODEL_PROVIDER=fake no está permitido en producción."]
    return []


def _api_key_problems(config):
    """Revisa que haya claves y que todas tengan el largo mínimo.

    :param config: Configuración validada
    :type config: app.config.Config
    :return: Reglas incumplidas, con cliente y largo pero sin la clave
    :rtype: list[str]
    """
    if not config.api_keys:
        return ["API_KEYS no puede estar vacía en producción."]
    return [
        f"API_KEYS: la clave del cliente {client!r} tiene {len(key)} "
        f"caracteres; el mínimo es {MIN_API_KEY_CHARS}."
        for client, key in config.api_keys.items()
        if len(key) < MIN_API_KEY_CHARS
    ]


def _tracing_problems(config):
    """Revisa que las trazas encendidas oculten entradas y salidas.

    :param config: Configuración validada
    :type config: app.config.Config
    :return: Reglas incumplidas
    :rtype: list[str]
    """
    if not config.langsmith_tracing:
        return []
    visible = [
        name
        for name, hidden in (
            ("HIDE_INPUTS", config.hide_inputs),
            ("HIDE_OUTPUTS", config.hide_outputs),
        )
        if not hidden
    ]
    if not visible:
        return []
    return [
        "Con LANGSMITH_TRACING=true en producción deben valer true: "
        + ", ".join(visible) + "."
    ]


def check_production(config):
    """Devuelve las reglas de producción que la configuración incumple.

    :param config: Configuración validada
    :type config: app.config.Config
    :return: Mensajes de las reglas incumplidas; vacía si cumple todas
    :rtype: list[str]
    """
    return (
        _provider_problems(config)
        + _api_key_problems(config)
        + _tracing_problems(config)
    )
