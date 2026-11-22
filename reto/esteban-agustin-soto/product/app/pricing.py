"""Tabla de precios por modelo y costo de cada llamada."""

import json

TOKENS_PER_PRICE_UNIT = 1_000_000


class PriceTable:
    """Precios en USD por millón de tokens, leídos de un archivo JSON.

    :param path: Ruta de ``model_prices.json``
    :type path: str or pathlib.Path
    :raises ValueError: Si el archivo no se puede leer o no tiene ``models``
    """

    def __init__(self, path):
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            self._models = dict(data["models"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ValueError(f"Cannot read price table {path}: {error}") from error

    def cost(self, model, input_tokens, output_tokens, cached):
        """Calcula el costo de una llamada.

        :param model: Nombre del modelo
        :type model: str
        :param input_tokens: Tokens de entrada
        :type input_tokens: int
        :param output_tokens: Tokens de salida
        :type output_tokens: int
        :param cached: Si el gateway respondió desde la caché
        :type cached: bool
        :return: Costo en USD (0 si fue cacheada)
        :rtype: float
        :raises ValueError: Si el modelo no tiene precio
        """
        price = self._models.get(model)
        if price is None:
            raise ValueError(f"No price for model {model!r}")
        if cached:
            return 0.0
        total = input_tokens * price["input"] + output_tokens * price["output"]
        return total / TOKENS_PER_PRICE_UNIT
