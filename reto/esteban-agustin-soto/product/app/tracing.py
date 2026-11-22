"""Trazas opcionales en LangSmith, apagadas salvo clave y activación."""

from app.observability import DEFAULT_REQUEST_ID, client_var, request_id_var

try:
    from langsmith import traceable
except ImportError:  # pragma: no cover - depende del entorno
    traceable = None


def _hide(_data):
    """Reemplaza entradas o salidas por un diccionario vacío.

    :param _data: Datos originales (se descartan)
    :return: Diccionario vacío
    :rtype: dict
    """
    return {}


def traced(  # pylint: disable=too-many-arguments
    func, name, *, enabled, api_key, hide_inputs, hide_outputs
):
    """Envuelve ``func`` con ``@traceable`` solo si hay activación y clave.

    Sin ``enabled`` o sin ``api_key`` devuelve la misma función y no usa
    ``langsmith``. El ``request_id`` y el nombre del cliente (nunca su clave)
    viajan en los metadatos de la traza.

    :param func: Función a trazar
    :type func: collections.abc.Callable
    :param name: Nombre de la traza
    :type name: str
    :param enabled: Valor de ``LANGSMITH_TRACING``
    :type enabled: bool
    :param api_key: Clave de LangSmith (nunca se registra)
    :type api_key: str or None
    :param hide_inputs: No mandar las entradas
    :type hide_inputs: bool
    :param hide_outputs: No mandar las salidas
    :type hide_outputs: bool
    :return: La función original o su versión trazada
    :rtype: collections.abc.Callable
    """
    if not enabled or not api_key or traceable is None:
        return func
    options = {"name": name}
    if hide_inputs:
        options["process_inputs"] = _hide
    if hide_outputs:
        options["process_outputs"] = _hide
    decorated = traceable(**options)(func)

    def wrapper(*args, **kwargs):
        metadata = {}
        request_id = request_id_var.get()
        if request_id != DEFAULT_REQUEST_ID:
            metadata["request_id"] = request_id
        client = client_var.get()
        if client is not None:
            metadata["client"] = client
        if metadata:
            kwargs["langsmith_extra"] = {"metadata": metadata}
        return decorated(*args, **kwargs)

    return wrapper
