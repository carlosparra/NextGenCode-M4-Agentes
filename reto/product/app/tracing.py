"""Trazas opcionales en LangSmith detras de una interfaz pequena (ADR 0006).

``build_tracer`` devuelve el trazador real solo si ``LANGSMITH_TRACING=true`` y
existe ``LANGSMITH_API_KEY``; si no, un ``NoopTracer`` que no importa ni conecta
nada. La clave la lee el SDK del entorno: aqui nunca se maneja.

Cada traza lleva en sus metadatos ``request_id``, ``client``, ``model``,
``route`` y ``environment`` (los que se conozcan) y los tags ``environment`` y
``route``. ``annotate`` agrega metadatos a la corrida en curso, por ejemplo el
``cost_usd`` al cerrar ``agent_run``. Nunca se manda texto de preguntas ni
respuestas en los metadatos; con ``HIDE_INPUTS``/``HIDE_OUTPUTS`` tampoco en
las entradas y salidas.
"""

from app.config import Settings

# Tipo de corrida de LangSmith para cada nombre de traza del producto.
RUN_TYPES = {"agent_run": "chain", "llm": "llm", "tool": "tool"}
# Metadatos opcionales que se copian a la traza si tienen valor.
OPTIONAL_METADATA = ("client", "model", "route", "environment")
# Metadatos que tambien van como tags, con la forma ``nombre:valor``.
TAG_FIELDS = ("environment", "route")


def trace_metadata(request_id, **context) -> dict:
    """Arma los metadatos de una traza con los valores conocidos.

    :param request_id: Id de la peticion (siempre va, aunque sea ``None``)
    :type request_id: str or None
    :param context: ``client``, ``model``, ``route`` y ``environment``
    :type context: dict
    :return: Metadatos sin los valores ``None``
    :rtype: dict
    """
    metadata = {"request_id": request_id}
    for name in OPTIONAL_METADATA:
        if context.get(name) is not None:
            metadata[name] = context[name]
    return metadata


def trace_tags(metadata: dict) -> list:
    """Arma los tags ``environment:<valor>`` y ``route:<valor>``.

    :param metadata: Metadatos de la traza
    :type metadata: dict
    :return: Tags de los campos conocidos
    :rtype: list[str]
    """
    return [f"{name}:{metadata[name]}" for name in TAG_FIELDS if name in metadata]


class NoopTracer:
    """Trazador apagado: devuelve la misma funcion."""

    def trace(self, func, **_options):
        """Devuelve la funcion sin envolver.

        :param func: Funcion a trazar
        :type func: callable
        :param _options: ``name``, ``request_id``, ``client``... (ignorados)
        :type _options: dict
        :return: La misma funcion
        :rtype: callable
        """
        return func

    def annotate(self, **_metadata) -> None:
        """No hace nada.

        :param _metadata: Metadatos (ignorados)
        :type _metadata: dict
        """


class LangSmithTracer:
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

    def trace(self, func, name: str, request_id=None, **context):
        """Envuelve la funcion para que quede como traza en LangSmith.

        Si el SDK falla al preparar la traza, devuelve la funcion sin envolver
        para no afectar la respuesta.

        :param func: Funcion a trazar
        :type func: callable
        :param name: Nombre de la traza (``agent_run``, ``llm`` o ``tool``)
        :type name: str
        :param request_id: Id de la peticion, que va en los metadatos
        :type request_id: str or None
        :param context: ``client`` (el nombre, nunca su clave), ``model``,
            ``route`` y ``environment``; los que tengan valor van en los
            metadatos y ``environment`` y ``route`` tambien como tags
        :type context: dict
        :return: La funcion envuelta, o la original si el SDK falla
        :rtype: callable
        """
        metadata = trace_metadata(request_id, **context)
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
                tags=trace_tags(metadata),
            )
            return decorator(func)
        except Exception:  # pylint: disable=broad-exception-caught
            return func

    def annotate(self, **metadata) -> None:
        """Agrega metadatos a la corrida en curso (por ejemplo ``cost_usd``).

        Se llama dentro de la funcion trazada. Si no hay corrida o el SDK
        falla, no hace nada.

        :param metadata: Metadatos sin texto de la conversacion
        :type metadata: dict
        """
        # Igual que en ``trace``: una falla del SDK no afecta la respuesta.
        try:
            import langsmith  # pylint: disable=import-outside-toplevel

            run = langsmith.get_current_run_tree()
            if run is not None:
                run.add_metadata(metadata)
        except Exception:  # pylint: disable=broad-exception-caught
            pass


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
