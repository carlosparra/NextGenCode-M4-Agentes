"""Tabla de precios por modelo, en USD por millón de tokens."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app.config import ConfigError

TOKENS_PER_PRICE_UNIT = 1_000_000


@dataclass(frozen=True)
class ModelPrice:
    """Precio de un modelo.

    :param input: USD por millón de tokens de entrada
    :type input: float
    :param output: USD por millón de tokens de salida
    :type output: float
    """

    input: float
    output: float


def _read_price(model: str, raw) -> ModelPrice:
    """Valida el precio de un modelo leído del archivo.

    :param model: Nombre del modelo
    :type model: str
    :param raw: Objeto con ``input`` y ``output``
    :type raw: dict
    :return: Precio validado
    :rtype: ModelPrice
    :raises ConfigError: Si faltan precios o no son números no negativos
    """
    try:
        price = ModelPrice(input=float(raw["input"]), output=float(raw["output"]))
    except (KeyError, TypeError, ValueError) as error:
        raise ConfigError(f"PRICES_PATH has an invalid price for {model}") from error
    if price.input < 0 or price.output < 0:
        raise ConfigError(f"PRICES_PATH has a negative price for {model}")
    return price


class PriceTable:
    """Precios por modelo; calcula el costo de una respuesta.

    :param prices: Precio de cada modelo por nombre
    :type prices: dict[str, ModelPrice]
    """

    def __init__(self, prices: dict):
        self._prices = dict(prices)

    @classmethod
    def load(cls, path: Path) -> "PriceTable":
        """Lee la tabla de precios de un archivo JSON con la clave ``models``.

        :param path: Ruta al archivo de precios
        :type path: pathlib.Path
        :return: Tabla de precios
        :rtype: PriceTable
        :raises ConfigError: Si el archivo no existe o no tiene el formato esperado
        """
        try:
            content = json.loads(Path(path).read_text(encoding="utf-8"))
            models = content["models"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ConfigError(f"PRICES_PATH cannot be read: {path}") from error
        if not isinstance(models, dict):
            raise ConfigError(f"PRICES_PATH must map model names to prices: {path}")
        return cls({name: _read_price(name, raw) for name, raw in models.items()})

    def require(self, models: Iterable[str]) -> None:
        """Comprueba que todos los modelos tengan precio.

        :param models: Nombres de los modelos que usará la aplicación
        :type models: collections.abc.Iterable[str]
        :raises ConfigError: Si algún modelo no está en la tabla
        """
        missing = [model for model in models if model not in self._prices]
        if missing:
            raise ConfigError(f"PRICES_PATH has no price for: {', '.join(missing)}")

    def cost_usd(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calcula el costo en USD de unos tokens con el precio del modelo.

        :param model: Nombre del modelo
        :type model: str
        :param input_tokens: Tokens de entrada cobrables
        :type input_tokens: int
        :param output_tokens: Tokens de salida cobrables
        :type output_tokens: int
        :return: Costo en USD
        :rtype: float
        :raises ConfigError: Si el modelo no tiene precio
        """
        self.require([model])
        price = self._prices[model]
        total = input_tokens * price.input + output_tokens * price.output
        return total / TOKENS_PER_PRICE_UNIT
