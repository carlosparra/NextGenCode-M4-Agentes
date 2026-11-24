"""Verificación previa al arranque (compliance como código).

Se corre antes de uvicorn: si la configuración no cumple, el contenedor termina
con código 1 en lugar de quedar reiniciando procesos hijos sin fin.

Uso: ``python -m app.preflight``
"""

import sys

from app.config import ConfigError, load_settings


def main() -> int:
    """Valida la configuración del entorno.

    :return: 0 si cumple; 1 si no (el motivo va a stderr, sin secretos)
    :rtype: int
    """
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"Configuración inválida: {exc}", file=sys.stderr)
        return 1
    print(
        f"preflight ok: environment={settings.environment} "
        f"provider={settings.model_provider} clients={len(settings.api_clients)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
