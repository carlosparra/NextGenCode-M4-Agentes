"""Compliance como codigo (ADR 0013).

Con ``ENVIRONMENT=production`` el producto se niega a arrancar si la
configuracion no es segura. Cada regla esta en ``doc/compliance-checklist.md``.
Los mensajes nombran la variable y la posicion de la entrada, nunca una clave.
"""

from app.config import (
    ENVIRONMENT_PRODUCTION,
    PROVIDER_FAKE,
    ConfigError,
    Settings,
)

MIN_PRODUCTION_KEY_CHARS = 16


def _model_violations(settings: Settings) -> list[str]:
    """Regla 1: en produccion no se usa el modelo simulado.

    :param settings: Configuracion validada
    :type settings: app.config.Settings
    :return: La regla violada, o una lista vacia
    :rtype: list[str]
    """
    if settings.model_provider == PROVIDER_FAKE:
        return [f"MODEL_PROVIDER must not be '{PROVIDER_FAKE}' in production"]
    return []


def _key_violations(settings: Settings) -> list[str]:
    """Regla 2: hay claves y todas tienen al menos 16 caracteres.

    :param settings: Configuracion validada
    :type settings: app.config.Settings
    :return: La regla violada (con la posicion de las entradas cortas), o una
        lista vacia
    :rtype: list[str]
    """
    if not settings.api_keys:
        return ["API_KEYS must not be empty in production"]
    short = [
        str(position)
        for position, entry in enumerate(settings.api_keys, start=1)
        if len(entry.key) < MIN_PRODUCTION_KEY_CHARS
    ]
    if short:
        return [
            f"API_KEYS entries {', '.join(short)} have keys shorter than "
            f"{MIN_PRODUCTION_KEY_CHARS} characters"
        ]
    return []


def _tracing_violations(settings: Settings) -> list[str]:
    """Regla 3: con trazas encendidas, entradas y salidas van ocultas.

    :param settings: Configuracion validada
    :type settings: app.config.Settings
    :return: La regla violada (con las variables en falso), o una lista vacia
    :rtype: list[str]
    """
    if not settings.langsmith_tracing:
        return []
    visible = [
        name
        for name, hidden in (
            ("HIDE_INPUTS", settings.hide_inputs),
            ("HIDE_OUTPUTS", settings.hide_outputs),
        )
        if not hidden
    ]
    if visible:
        return [
            f"{' and '.join(visible)} must be 'true' when LANGSMITH_TRACING=true "
            "in production"
        ]
    return []


def production_violations(settings: Settings) -> list[str]:
    """Lista las reglas de produccion que la configuracion incumple.

    Fuera de produccion no se exige nada.

    :param settings: Configuracion validada
    :type settings: app.config.Settings
    :return: Un texto por regla violada, sin valores secretos; vacia si cumple
    :rtype: list[str]
    """
    if settings.environment != ENVIRONMENT_PRODUCTION:
        return []
    return [
        *_model_violations(settings),
        *_key_violations(settings),
        *_tracing_violations(settings),
    ]


def enforce(settings: Settings) -> None:
    """Impide arrancar si la configuracion de produccion no es segura.

    :param settings: Configuracion validada
    :type settings: app.config.Settings
    :raises app.config.ConfigError: Con todas las reglas violadas
    """
    violations = production_violations(settings)
    if violations:
        raise ConfigError(
            "unsafe production configuration: " + "; ".join(violations)
        )
