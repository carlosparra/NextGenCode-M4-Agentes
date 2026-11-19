"""Trazas opcionales en LangSmith detras de una interfaz pequena (ADR 0006).

``build_tracer`` devuelve el trazador real solo si ``LANGSMITH_TRACING=true`` y
existe ``LANGSMITH_API_KEY``; si no, un ``NoopTracer`` que no importa ni conecta
nada. La clave la lee el SDK del entorno: aqui nunca se maneja.
"""

from app.config import Settings

# Tipo de corrida de LangSmith para cada nombre de traza del producto.
RUN_TYPES = {"agent_run": "chain", "llm": "llm", "tool": "tool"}


class NoopTracer:  # pylint: disable=too-few-public-methods
    """Trazador apagado: devuelve la misma funcion."""

    def trace(self, func, **_options):
        """Devuelve la funcion sin envolver.

        :param func: Funcion a trazar
        :type func: callable
        :param _options: ``name``, ``request_id``, ``client`` (ignorados)
        :type _options: dict
        :return: La misma funcion
        :rtype: callable
        """
        return func


class LangSmithTracer:  # pylint: disable=too-few-public-methods
    """Trazador que envuelve funciones con ``langsmith.traceable``.

    :param hide_inputs: No mandar las entradas a LangSmith
    :type hide_inputs: bool
    :param hide_outputs: No mandar las salidas a LangSmith
    :type hide_outputs: bool
    """

    def __init__(self, hide_inputs: bool, hide_outputs: bool):
        self._hide_inputs = hide_inputs
        self._hide_outputs = hide_outputs
        self._client = None

    def trace(self, func, name: str, request_id=None, client=None, **_options):
        """Envuelve la funcion para que quede como traza en LangSmith.

        Si el SDK falla al preparar la traza, devuelve la funcion sin envolver
        para no afectar la respuesta.

        :param func: Funcion a trazar
        :type func: callable
        :param name: Nombre de la traza (``agent_run``, ``llm`` o ``tool``)
        :type name: str
        :param request_id: Id de la peticion, que va en los metadatos
        :type request_id: str or None
        :param client: Nombre del cliente (nunca su clave); va en los
            metadatos si se conoce
        :type client: str or None
        :param _options: Opciones extra (ignoradas)
        :type _options: dict
        :return: La funcion envuelta, o la original si el SDK falla
        :rtype: callable
        """
        metadata = {"request_id": request_id}
        if client is not None:
            metadata["client"] = client
        # Un trazador roto no debe tumbar la peticion: se captura cualquier error.
        try:
            import langsmith  # pylint: disable=import-outside-toplevel

            if self._client is None:
                self._client = langsmith.Client(
                    hide_inputs=self._hide_inputs, hide_outputs=self._hide_outputs
                )
            decorator = langsmith.traceable(
                name=name,
                run_type=RUN_TYPES.get(name, "chain"),
                client=self._client,
                metadata=metadata,
            )
            return decorator(func)
        except Exception:  # pylint: disable=broad-exception-caught
            return func


def build_tracer(settings: Settings):
    """Construye el trazador segun la configuracion.

    :param settings: Configuracion de la aplicacion
    :type settings: app.config.Settings
    :return: ``LangSmithTracer`` si las trazas estan habilitadas; si no,
        ``NoopTracer``
    :rtype: LangSmithTracer or NoopTracer
    """
    if settings.langsmith_enabled:
        return LangSmithTracer(settings.hide_inputs, settings.hide_outputs)
    return NoopTracer()
