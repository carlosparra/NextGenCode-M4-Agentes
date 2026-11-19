"""Tabla de precios por modelo para calcular el costo de cada respuesta.

Los precios estan en USD por millon de tokens y se leen de un archivo JSON
(``PRICES_PATH``), no del codigo, porque cambian con el tiempo.
"""

import json
from pathlib import Path

TOKENS_PER_PRICE_UNIT = 1_000_000


class UnknownModelError(KeyError):
    """El modelo no tiene precio en la tabla."""


class PriceTable:
    """Precios de entrada y salida por nombre de modelo.

    :param prices: Para cada modelo, un par ``(entrada, salida)`` en USD por
        millon de tokens
    :type prices: dict[str, tuple[float, float]]
    """

    def __init__(self, prices: dict):
        self._prices = dict(prices)

    @classmethod
    def load(cls, path) -> "PriceTable":
        """Lee y valida el archivo de precios.

        :param path: Ruta al archivo ``model_prices.json``
        :type path: str or pathlib.Path
        :return: La tabla de precios
        :rtype: PriceTable
        :raises OSError: Si el archivo no se puede leer
        :raises ValueError: Si el archivo no es JSON valido o no tiene el
            formato esperado
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, dict):
            raise ValueError("Prices file must contain a 'models' object.")
        prices = {}
        for name, price in models.items():
            try:
                prices[name] = (float(price["input"]), float(price["output"]))
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    f"Model {name!r} needs numeric 'input' and 'output' prices."
                ) from error
        return cls(prices)

    def has(self, model: str) -> bool:
        """Indica si el modelo tiene precio.

        :param model: Nombre del modelo
        :type model: str
        :return: ``True`` si el modelo esta en la tabla
        :rtype: bool
        """
        return model in self._prices

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calcula el costo en USD de una llamada al modelo.

        :param model: Nombre del modelo
        :type model: str
        :param input_tokens: Tokens de entrada
        :type input_tokens: int
        :param output_tokens: Tokens de salida
        :type output_tokens: int
        :return: Costo en USD
        :rtype: float
        :raises UnknownModelError: Si el modelo no tiene precio
        """
        if model not in self._prices:
            raise UnknownModelError(model)
        input_price, output_price = self._prices[model]
        total = input_tokens * input_price + output_tokens * output_price
        return total / TOKENS_PER_PRICE_UNIT


FREE_MODEL = "fake"
# Tabla por omision del agente: solo el modelo simulado, sin costo.
FREE_PRICES = PriceTable({FREE_MODEL: (0.0, 0.0)})
