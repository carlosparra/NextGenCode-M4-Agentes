"""Reglas de compliance que se revisan solas al arrancar en producción.

Con ``ENVIRONMENT=production`` la aplicación se niega a arrancar si alguna regla
falla. Los mensajes nombran la variable y el cliente, nunca el valor de una clave.
"""

from app.config import ConfigError, Settings

PRODUCTION = "production"
FORBIDDEN_PRODUCTION_PROVIDER = "fake"
MIN_API_KEY_CHARS = 16


def _provider_violations(settings: Settings) -> list[str]:
    """Revisa que producción no use el modelo simulado.

    :param settings: Configuración validada
    :type settings: app.config.Settings
    :return: Reglas incumplidas
    :rtype: list[str]
    """
    if settings.model_provider == FORBIDDEN_PRODUCTION_PROVIDER:
        return [f"MODEL_PROVIDER must not be '{FORBIDDEN_PRODUCTION_PROVIDER}'"]
    return []


def _api_key_violations(settings: Settings) -> list[str]:
    """Revisa que haya claves y que todas tengan el largo mínimo.

    :param settings: Configuración validada
    :type settings: app.config.Settings
    :return: Reglas incumplidas, con el cliente pero sin la clave
    :rtype: list[str]
    """
    if not settings.api_keys:
        return ["API_KEYS must not be empty"]
    return [
        f"API_KEYS key of client {client!r} must have at least "
        f"{MIN_API_KEY_CHARS} characters"
        for client, secret in settings.api_keys.items()
        if len(secret.reveal()) < MIN_API_KEY_CHARS
    ]


def _tracing_violations(settings: Settings) -> list[str]:
    """Revisa que las trazas, si están encendidas, oculten entradas y salidas.

    :param settings: Configuración validada
    :type settings: app.config.Settings
    :return: Reglas incumplidas
    :rtype: list[str]
    """
    if not settings.langsmith_tracing:
        return []
    hidden = {
        "HIDE_INPUTS": settings.hide_inputs,
        "HIDE_OUTPUTS": settings.hide_outputs,
    }
    return [
        f"{name} must be 'true' when LANGSMITH_TRACING is on"
        for name, value in hidden.items()
        if not value
    ]


def _pii_violations(settings: Settings) -> list[str]:
    """Revisa que la redacción de datos personales esté encendida.

    :param settings: Configuración validada
    :type settings: app.config.Settings
    :return: Reglas incumplidas
    :rtype: list[str]
    """
    if not settings.pii_redaction:
        return ["PII_REDACTION must be 'true'"]
    return []


def violations(settings: Settings) -> list[str]:
    """Lista las reglas de producción que incumple la configuración.

    Fuera de producción no aplica ninguna regla.

    :param settings: Configuración validada
    :type settings: app.config.Settings
    :return: Una descripción por regla incumplida; vacía si todo está bien
    :rtype: list[str]
    """
    if settings.environment != PRODUCTION:
        return []
    return (
        _provider_violations(settings)
        + _api_key_violations(settings)
        + _tracing_violations(settings)
        + _pii_violations(settings)
    )


def check(settings: Settings) -> None:
    """Impide arrancar si la configuración de producción no es segura.

    :param settings: Configuración validada
    :type settings: app.config.Settings
    :raises app.config.ConfigError: Si alguna regla de producción falla
    """
    found = violations(settings)
    if found:
        raise ConfigError(
            "ENVIRONMENT=production refuses to start: " + "; ".join(found)
        )
