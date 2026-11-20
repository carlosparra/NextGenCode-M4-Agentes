"""Precios por modelo y costo de cada llamada (ADR 0007).

Los precios vienen de ``data/model_prices.json``, en USD por millón de tokens.
Cambiar un precio es editar ese archivo, sin tocar código.
"""

import json
from pathlib import Path

from app.config import ConfigError

TOKENS_PER_PRICE_UNIT = 1_000_000


class PriceTable:
    """Tabla de precios de entrada y salida por modelo.

    :param prices: Precio por modelo: ``{"input": float, "output": float}``
    :type prices: dict[str, dict[str, float]]
    """

    def __init__(self, prices):
        self._prices = {name: dict(price) for name, price in prices.items()}

    def has(self, model):
        """Indica si el modelo tiene precio.

        :param model: Nombre del modelo
        :type model: str
        :return: ``True`` si el modelo está en la tabla
        :rtype: bool
        """
        return model in self._prices

    def cost(self, model, input_tokens, output_tokens):
        """Calcula el costo en USD de una llamada.

        :param model: Nombre del modelo que respondió
        :type model: str
        :param input_tokens: Tokens de entrada
        :type input_tokens: int
        :param output_tokens: Tokens de salida
        :type output_tokens: int
        :return: Costo en USD
        :rtype: float
        :raises ConfigError: Si el modelo no tiene precio
        """
        if not self.has(model):
            raise ConfigError(f"El modelo {model!r} no tiene precio.")
        price = self._prices[model]
        total = input_tokens * price["input"] + output_tokens * price["output"]
        return total / TOKENS_PER_PRICE_UNIT


def _valid_price(price):
    """Indica si un precio tiene ``input`` y ``output`` numéricos no negativos.

    :param price: Precio leído del archivo
    :type price: object
    :return: ``True`` si el precio es válido
    :rtype: bool
    """
    if not isinstance(price, dict):
        return False
    values = [price.get("input"), price.get("output")]
    return all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and value >= 0
        for value in values
    )


def load_prices(path):
    """Carga la tabla de precios desde un archivo JSON.

    :param path: Ruta del archivo de precios
    :type path: str or pathlib.Path
    :return: La tabla de precios
    :rtype: PriceTable
    :raises ConfigError: Si el archivo no existe, no es JSON o es inválido
    """
    try:
        with Path(path).open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        raise ConfigError(f"No se pudo leer PRICES_PATH ({path}).") from error
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, dict):
        raise ConfigError(f"PRICES_PATH ({path}) no tiene el objeto 'models'.")
    invalid = [name for name, price in models.items() if not _valid_price(price)]
    if invalid:
        raise ConfigError(
            f"PRICES_PATH ({path}) tiene precios inválidos: {', '.join(invalid)}."
        )
    return PriceTable(models)
