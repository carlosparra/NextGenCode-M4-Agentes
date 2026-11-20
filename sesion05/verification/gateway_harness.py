"""Arranca el producto con Cloudflare simulado, sin tocar su código.

Se corre como script dentro de ``product/``: ``python gateway_harness.py <puerto>``.
Antes de importar el producto, cambia el transporte de ``httpx`` para que las
llamadas a ``gateway.ai.cloudflare.com`` las conteste este archivo. La URL, el
cuerpo y el encabezado se comprueban tal como los manda el producto: si algo no
coincide, el gateway simulado responde 404 y el producto contesta 502.

Cada petición recibida se guarda como una línea JSON en el archivo que indica
``FACTORY_GATEWAY_LOG``. Las respuestas simulan a un modelo pequeño que se sale
del formato; qué respuesta da depende del id de empleado de la pregunta:

- ``EMP-0004``: mezcla la petición de herramienta con una respuesta inventada.
- ``EMP-0002``: primero contesta texto sin JSON; después responde bien.
- ``EMP-0003``: nunca contesta algo válido.
- Cualquier otro: responde con el protocolo, sin errores.
"""

import json
import os
import re
import sys
from pathlib import Path

import httpx

GATEWAY_HOST = "gateway.ai.cloudflare.com"
ACCOUNT = "factory-acc"
GATEWAY = "factory-gw"
TOKEN = "factory-token"
URL = (
    f"https://{GATEWAY_HOST}/v1/{ACCOUNT}/{GATEWAY}/"
    "workers-ai/v1/chat/completions"
)
TOOL_PREFIX = "Resultado de la herramienta: "
EMPLOYEE_ID = re.compile(r"EMP-\d{4}")
MESSY = (
    TOOL_PREFIX
    + '{"tool": "get_employee", "args": {"employee_id": "EMP-0004"}} \n\n'
    + '{"answer": "Empleado no encontrado"}'
)

# Guion de cada empleado: recibe cuántas peticiones lleva la pregunta.
SCRIPTS = {
    "EMP-0002": lambda n: (
        "No puedo responder eso." if n == 1 else json.dumps({"answer": "Recuperado"})
    ),
    "EMP-0003": lambda n: "not json",
    "EMP-0004": lambda n: MESSY,
}


def respond(messages: list, seen: dict) -> str:
    """Decide qué contesta el modelo simulado a esta petición.

    :param messages: mensajes recibidos, con el ``system`` primero.
    :param seen: cuántas peticiones llevan las preguntas, para los guiones.
    :return: el texto de la respuesta del modelo.
    """
    conversation = [m for m in messages if m["role"] != "system"]
    question = conversation[0]["content"] if conversation else ""
    seen[question] = seen.get(question, 0) + 1
    last = conversation[-1]["content"] if conversation else ""
    found = EMPLOYEE_ID.search(question)
    employee = found.group() if found else ""
    if last.startswith(TOOL_PREFIX):
        return json.dumps({"answer": f"Según el directorio: {last[len(TOOL_PREFIX):]}"})
    if employee in SCRIPTS:
        return SCRIPTS[employee](seen[question])
    if employee:
        return json.dumps({"tool": "get_employee", "args": {"employee_id": employee}})
    return json.dumps({"answer": "Pregúntame por un empleado."})


def build_handler(log_path: Path):
    """Crea el manejador del gateway simulado.

    :param log_path: archivo donde se guarda cada petición válida.
    :return: función que recibe una ``httpx.Request`` y devuelve una respuesta.
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        if str(request.url) != URL:
            return httpx.Response(404, json={"error": "unexpected url"})
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"error": "unexpected token"})
        body = json.loads(request.content)
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(body, ensure_ascii=False) + "\n")
        text = respond(body["messages"], seen)
        words = sum(len(str(m["content"]).split()) for m in body["messages"])
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": text}}],
                "usage": {
                    "prompt_tokens": words,
                    "completion_tokens": len(text.split()),
                },
            },
        )

    return handler


class GatewayOnlyTransport(httpx.BaseTransport):
    """Contesta las llamadas al gateway y deja pasar las demás.

    :param handler: manejador del gateway simulado.
    """

    def __init__(self, handler) -> None:
        self._handler = handler
        self._real = httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Resuelve la petición con el simulado o con la red.

        :param request: petición saliente del producto.
        :return: la respuesta.
        """
        if request.url.host == GATEWAY_HOST:
            return self._handler(request)
        return self._real.handle_request(request)


def install(handler):
    """Hace que todo ``httpx.Client`` sin transporte propio use el simulado.

    :param handler: manejador del gateway simulado.
    :return: función que deshace el cambio.
    """
    original = httpx.Client.__init__

    def patched(self, *args, **kwargs):
        if kwargs.get("transport") is None:
            kwargs["transport"] = GatewayOnlyTransport(handler)
        original(self, *args, **kwargs)

    httpx.Client.__init__ = patched

    def restore() -> None:
        httpx.Client.__init__ = original

    return restore


def main(argv: list) -> int:  # pragma: no cover
    """Instala el gateway simulado y arranca el producto.

    :param argv: el puerto en el que escucha el producto.
    :return: código de salida.
    """
    here = Path(__file__).resolve().parent
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != here]
    sys.path.insert(0, os.getcwd())
    import uvicorn  # pylint: disable=import-outside-toplevel

    install(build_handler(Path(os.environ["FACTORY_GATEWAY_LOG"])))
    uvicorn.run("app.main:app", port=int(argv[0]), log_level="warning")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
