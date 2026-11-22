"""Trazas opcionales en LangSmith.

Si el tracing está apagado o falta la clave, no se importa ``langsmith`` ni se crea
ningún cliente: las funciones se devuelven tal cual.
"""

from contextlib import nullcontext


class Tracer:
    """Envuelve funciones con ``@traceable`` solo cuando el tracing está activo.

    :param settings: Configuración validada
    :type settings: app.config.Settings
    """

    def __init__(self, settings):
        self._enabled = settings.tracing_enabled
        self._client = None
        self._traceable = None
        self._tracing_context = None
        if self._enabled:
            # Importación tardía: sin clave nunca se carga langsmith.
            import langsmith  # pylint: disable=import-outside-toplevel,import-error

            # El cliente lee LANGSMITH_API_KEY del entorno; aquí no pasa la clave.
            self._client = langsmith.Client(
                hide_inputs=settings.hide_inputs,
                hide_outputs=settings.hide_outputs,
            )
            self._traceable = langsmith.traceable
            self._tracing_context = langsmith.tracing_context

    @property
    def enabled(self) -> bool:
        """Indica si las trazas se mandan a LangSmith.

        :return: ``True`` si el tracing está activo
        :rtype: bool
        """
        return self._enabled

    def wrap(self, function, name: str, run_type: str):
        """Devuelve la función envuelta como traza (o la misma si está apagado).

        :param function: Función a trazar
        :type function: callable
        :param name: Nombre de la traza
        :type name: str
        :param run_type: Tipo de corrida (``chain``, ``llm``, ``tool``)
        :type run_type: str
        :return: Función envuelta o la original
        :rtype: callable
        """
        if not self._enabled:
            return function
        decorator = self._traceable(name=name, run_type=run_type, client=self._client)
        return decorator(function)

    def request_scope(self, request_id: str, client: str | None = None):
        """Abre un contexto que agrega ``request_id`` y ``client`` a los metadatos.

        Solo viaja el nombre del cliente, nunca su clave.

        :param request_id: Id de la petición
        :type request_id: str
        :param client: Nombre del cliente autenticado; ``None`` no lo agrega
        :type client: str or None
        :return: Administrador de contexto
        :rtype: contextlib.AbstractContextManager
        """
        if not self._enabled:
            return nullcontext()
        metadata = {"request_id": request_id}
        if client is not None:
            metadata["client"] = client
        return self._tracing_context(metadata=metadata)
