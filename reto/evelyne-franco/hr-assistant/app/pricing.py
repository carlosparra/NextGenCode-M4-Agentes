"""Tabla de precios por modelo y costo de cada llamada.

Los precios estan en USD por millon de tokens (``data/model_prices.json``,
copia de ``spec/model_prices.json``). El costo no se redondea: una
pregunta corta cuesta millonesimas de dolar y no debe volverse 0.

:seealso: ``spec/03-costs.md`` punto 6 y ADR 0009.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, NamedTuple

TOKENS_PER_PRICE_UNIT = 1_000_000


class ModelPrice(NamedTuple):
    """Precio de un modelo en USD por millon de tokens.

    :param input: Precio de los tokens de entrada.
    :type input: float
    :param output: Precio de los tokens de salida.
    :type output: float
    """

    input: float
    output: float


def _parse_price(name: str, raw: Any) -> ModelPrice:
    """Valida y convierte el precio de un modelo.

    :param name: Nombre del modelo.
    :type name: str
    :param raw: Valor del archivo, ``{"input": ..., "output": ...}``.
    :type raw: Any
    :return: Precio validado.
    :rtype: ModelPrice
    :raises ValueError: Si falta un precio o es negativo.
    """
    try:
        price = ModelPrice(float(raw["input"]), float(raw["output"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Precio invalido para el modelo {name}") from exc
    if price.input < 0 or price.output < 0:
        raise ValueError(f"Precio negativo para el modelo {name}")
    return price


class PriceTable:
    """Precios por modelo y calculo del costo en USD.

    :param prices: Precio de cada modelo, por nombre.
    :type prices: collections.abc.Mapping[str, ModelPrice]
    """

    def __init__(self, prices: Mapping[str, ModelPrice]) -> None:
        """Guarda una copia de los precios.

        :param prices: Precio de cada modelo, por nombre.
        :type prices: collections.abc.Mapping[str, ModelPrice]
        """
        self._prices = dict(prices)

    @classmethod
    def from_file(cls, path: str, required: Iterable[str]) -> PriceTable:
        """Carga los precios y exige los de los modelos configurados.

        :param path: Ruta al JSON de precios.
        :type path: str
        :param required: Modelos que deben tener precio.
        :type required: collections.abc.Iterable[str]
        :return: Tabla de precios.
        :rtype: PriceTable
        :raises FileNotFoundError: Si el archivo no existe.
        :raises ValueError: Si el archivo no es valido o falta el precio
            de un modelo requerido.
        """
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, dict):
            raise ValueError(f"{path} debe tener un objeto 'models'")
        prices = {name: _parse_price(name, raw) for name, raw in models.items()}
        missing = [name for name in required if name not in prices]
        if missing:
            raise ValueError(
                f"Falta el precio de {', '.join(missing)} en {path}"
            )
        return cls(prices)

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calcula el costo de una llamada en USD, sin redondear.

        :param model: Nombre del modelo.
        :type model: str
        :param input_tokens: Tokens de entrada.
        :type input_tokens: int
        :param output_tokens: Tokens de salida.
        :type output_tokens: int
        :return: Costo en USD.
        :rtype: float
        :raises ValueError: Si el modelo no tiene precio.
        """
        price = self._prices.get(model)
        if price is None:
            raise ValueError(f"No hay precio para el modelo {model}")
        return (
            input_tokens * price.input + output_tokens * price.output
        ) / TOKENS_PER_PRICE_UNIT
