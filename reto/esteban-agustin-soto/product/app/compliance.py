"""Reglas de compliance que se comprueban al arrancar en producción."""

MIN_KEY_CHARS = 16


def check_production(settings):
    """Lista las reglas de producción que la configuración viola.

    Con ``ENVIRONMENT`` distinto de ``production`` no aplica ninguna regla. Los
    mensajes nombran la regla y el cliente, nunca el valor de una clave.

    :param settings: Configuración ya validada
    :type settings: app.config.Settings
    :return: Un mensaje por regla violada; vacía si todo cumple
    :rtype: list
    """
    if settings.environment != "production":
        return []
    found = []
    if settings.model_provider == "fake":
        found.append("MODEL_PROVIDER must not be 'fake' in production")
    if not settings.api_keys:
        found.append("API_KEYS must define at least one client in production")
    for name, key in settings.api_keys.items():
        if len(key) < MIN_KEY_CHARS:
            found.append(
                f"API_KEYS client '{name}' has a key shorter than "
                f"{MIN_KEY_CHARS} characters"
            )
    if settings.langsmith_tracing:
        if not settings.hide_inputs:
            found.append("HIDE_INPUTS must be 'true' while tracing is on")
        if not settings.hide_outputs:
            found.append("HIDE_OUTPUTS must be 'true' while tracing is on")
    if not settings.pii_masking:
        found.append("PII_MASKING must be 'true' in production")
    return found
