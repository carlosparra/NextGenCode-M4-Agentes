"""Errores compartidos del HR Assistant.

:class:`ConfigError` vive aquí para que ``config`` y ``auth`` lo usen sin
importarse entre sí; ``app.config`` lo vuelve a exponer.
"""


class ConfigError(ValueError):
    """Error de configuración que impide arrancar el asistente."""
