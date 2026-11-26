"""Valida la configuración antes de arrancar el servidor.

Se corre antes de uvicorn: si la configuración es insegura termina con código 1 y
un mensaje claro, en lugar de dejar que los procesos se reinicien sin fin.
"""

import sys

from app.config import ConfigError, load_settings


def main(env=None) -> int:
    """Revisa la configuración.

    :param env: Variables de entorno; por omisión, las del proceso
    :return: 0 si puede arrancar, 1 si no
    :rtype: int
    """
    try:
        settings = load_settings(env)
    except ConfigError as error:
        print(f"[FAIL] configuración: {error}", file=sys.stderr)
        return 1
    print(
        f"[OK] configuración: environment={settings.environment} "
        f"provider={settings.model_provider} clients={len(settings.api_keys)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
