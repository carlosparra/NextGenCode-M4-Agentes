"""Reglas de compliance que se revisan al arrancar.

Con ``ENVIRONMENT=production``, ``create_app`` llama a ``enforce`` y el
producto se niega a arrancar si alguna regla falla:

- ``MODEL_PROVIDER`` no puede ser ``fake``.
- ``API_KEYS`` no puede estar vacia y cada clave debe tener 16
  caracteres o mas.
- Con las trazas encendidas, ``HIDE_INPUTS`` y ``HIDE_OUTPUTS`` deben
  valer ``true``.

Los mensajes nombran la regla, nunca un valor de configuracion.

:seealso: ``spec/04-production.md`` (punto 3) y
    ``doc/compliance-checklist.md``.
"""

from __future__ import annotations

from app.config import ENVIRONMENT_PRODUCTION, PROVIDER_FAKE, Settings

MIN_KEY_CHARS = 16
RULE_REAL_MODEL = "MODEL_PROVIDER no puede ser fake en produccion"
RULE_STRONG_KEYS = (
    f"API_KEYS no puede estar vacia y cada clave necesita {MIN_KEY_CHARS} "
    "caracteres o mas"
)
RULE_HIDDEN_TRACES = (
    "con LANGSMITH_TRACING encendido, HIDE_INPUTS y HIDE_OUTPUTS deben ser true"
)


class ComplianceError(ValueError):
    """El producto no cumple las reglas de produccion.

    Hereda de ``ValueError`` como el resto de los errores de
    configuracion al arrancar.

    :param violations: Nombres de las reglas que fallan.
    :type violations: list[str]
    """

    def __init__(self, violations: list[str]) -> None:
        """Arma el mensaje con los nombres de las reglas.

        :param violations: Nombres de las reglas que fallan.
        :type violations: list[str]
        """
        self.violations = list(violations)
        super().__init__(
            "ENVIRONMENT=production no arranca; reglas que fallan: "
            + "; ".join(self.violations)
        )


def _has_strong_keys(settings: Settings) -> bool:
    """Indica si hay claves y todas tienen el largo minimo.

    :param settings: Configuracion del producto.
    :type settings: app.config.Settings
    :return: ``True`` si la regla se cumple.
    :rtype: bool
    """
    return bool(settings.api_keys) and all(
        len(item.key.get_secret_value()) >= MIN_KEY_CHARS
        for item in settings.api_keys
    )


def _hides_traced_data(settings: Settings) -> bool:
    """Indica si las trazas, si estan encendidas, ocultan entradas y salidas.

    :param settings: Configuracion del producto.
    :type settings: app.config.Settings
    :return: ``True`` si la regla se cumple.
    :rtype: bool
    """
    if not settings.langsmith_tracing:
        return True
    return settings.hide_inputs and settings.hide_outputs


def production_violations(settings: Settings) -> list[str]:
    """Lista las reglas de produccion que fallan.

    Fuera de ``production`` no hay reglas y la lista es vacia.

    :param settings: Configuracion del producto.
    :type settings: app.config.Settings
    :return: Nombres de las reglas que fallan, sin valores.
    :rtype: list[str]
    """
    if settings.environment != ENVIRONMENT_PRODUCTION:
        return []
    violations = []
    if settings.model_provider == PROVIDER_FAKE:
        violations.append(RULE_REAL_MODEL)
    if not _has_strong_keys(settings):
        violations.append(RULE_STRONG_KEYS)
    if not _hides_traced_data(settings):
        violations.append(RULE_HIDDEN_TRACES)
    return violations


def enforce(settings: Settings) -> None:
    """Se niega a seguir si alguna regla de produccion falla.

    :param settings: Configuracion del producto.
    :type settings: app.config.Settings
    :raises ComplianceError: Si hay al menos una regla que falla.
    """
    violations = production_violations(settings)
    if violations:
        raise ComplianceError(violations)
