"""Modelos y metadatos de la documentación OpenAPI del HR Assistant.

Solo describen la API: no cambian el comportamiento de ninguna ruta.
"""

from typing import Any, List, Literal, Optional

from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

API_KEY_HEADER = "X-API-Key"

API_TITLE = "HR Assistant"
API_SUMMARY = "Asistente de recursos humanos que consulta el directorio de empleados."
API_VERSION = "1.0.0"
API_DESCRIPTION = (
    "API sin estado que responde preguntas sobre empleados con un agente "
    "de herramientas de solo lectura.\n\n"
    "La documentación (`/docs`, `/redoc` y `/openapi.json`) es pública a "
    "propósito: no contiene secretos. Las rutas `/ask` y `/metrics` piden "
    "el encabezado `X-API-Key`; use el botón *Authorize* para probarlas."
)
TAG_APP = "Aplicación"
TAG_STATUS = "Estado"
TAG_ASSISTANT = "Asistente"
TAG_OPS = "Operación"
OPENAPI_TAGS = [
    {"name": TAG_APP, "description": "Página web del asistente."},
    {"name": TAG_STATUS, "description": "Comprobación de que el proceso vive."},
    {"name": TAG_ASSISTANT, "description": "Preguntas al agente de RR. HH."},
    {"name": TAG_OPS, "description": "Métricas del proceso para operación."},
]

api_key_scheme = APIKeyHeader(
    name=API_KEY_HEADER, auto_error=False,
    description="Clave del cliente. La validación real ocurre en el servicio.",
)


class HistoryMessage(BaseModel):
    """Un mensaje previo de la conversación.

    :param role: Autor del mensaje, ``user`` o ``assistant``
    :type role: str
    :param content: Texto del mensaje
    :type content: str
    """

    role: Literal["user", "assistant"] = Field(
        description="Autor del mensaje.", examples=["user"]
    )
    content: str = Field(
        description="Texto del mensaje.", examples=["Quién es EMP-0004?"]
    )


class AskRequest(BaseModel):
    """Cuerpo de ``POST /ask``.

    :param question: Pregunta de la persona usuaria
    :type question: str
    :param history: Mensajes previos de la conversación; opcional
    :type history: list[HistoryMessage] or None
    """

    question: str = Field(
        description="Pregunta sobre empleados.",
        examples=["¿En qué departamento trabaja EMP-0004?"],
    )
    history: Optional[List[HistoryMessage]] = Field(
        default=None, description="Mensajes previos; el servicio no guarda estado."
    )


class AskResponse(BaseModel):
    """Respuesta de ``POST /ask`` (solo para documentar su forma real).

    :param model: Modelo que respondió
    :type model: str
    :param route: Motivo del enrutador
    :type route: str
    :param cached_calls: Llamadas al modelo atendidas desde la caché
    :type cached_calls: int
    :param cost_usd: Costo de la petición en dólares
    :type cost_usd: float
    :param answer: Respuesta del asistente. Con la configuración por omisión
        mide como máximo 1500 caracteres; si se pasa, se recorta y termina en
        ``…``. El límite es ``MAX_ANSWER_CHARS``
    :type answer: str
    :param steps: Vueltas del bucle del agente
    :type steps: int
    :param tools_used: Herramientas ejecutadas
    :type tools_used: list[str]
    :param input_tokens: Tokens de entrada
    :type input_tokens: int
    :param output_tokens: Tokens de salida
    :type output_tokens: int
    :param request_id: Identificador de la petición
    :type request_id: str
    """

    model: str = Field(description="Modelo que respondió.")
    route: str = Field(description="Motivo por el que el enrutador eligió el modelo.")
    cached_calls: int = Field(description="Llamadas al modelo servidas desde caché.")
    cost_usd: float = Field(description="Costo de la petición en dólares.")
    answer: str = Field(
        description="Respuesta del asistente. Con la configuración por omisión "
        "mide como máximo 1500 caracteres; si se pasa, se recorta y termina "
        "en …. El límite es MAX_ANSWER_CHARS.",
        examples=["EMP-0004 trabaja en Ventas."],
    )
    steps: int = Field(description="Vueltas del bucle del agente.")
    tools_used: List[str] = Field(description="Herramientas ejecutadas con éxito.")
    input_tokens: int = Field(description="Tokens de entrada.")
    output_tokens: int = Field(description="Tokens de salida.")
    request_id: str = Field(description="Valor de X-Request-ID de esta petición.")


class ErrorDetail(BaseModel):
    """Cuerpo de error con solo ``detail``.

    :param detail: Motivo del error
    :type detail: typing.Any
    """

    detail: Any = Field(description="Motivo del error.")


class UpstreamError(BaseModel):
    """Cuerpo del 502.

    :param detail: Motivo del error
    :type detail: str
    :param request_id: Identificador de la petición
    :type request_id: str
    """

    detail: str = Field(examples=["model unavailable"])
    request_id: str


_RETRY_AFTER = {
    "Retry-After": {
        "description": "Segundos que hay que esperar antes de reintentar.",
        "schema": {"type": "string"},
    }
}
_UNAUTHORIZED = {
    "model": ErrorDetail,
    "description": "Clave ausente o inválida.",
    "content": {
        "application/json": {"example": {"detail": "invalid or missing API key"}}
    },
}
_RATE_LIMITED = {
    "model": ErrorDetail,
    "description": "El cliente superó su límite de peticiones por minuto.",
    "headers": _RETRY_AFTER,
    "content": {
        "application/json": {"example": {"detail": "rate limit exceeded"}}
    },
}

ASK_RESPONSES = {
    200: {"model": AskResponse, "description": "Respuesta del asistente."},
    401: _UNAUTHORIZED,
    422: {
        "model": ErrorDetail,
        "description": "Pregunta vacía o demasiado larga, o cuerpo inválido.",
        "content": {
            "application/json": {"example": {"detail": "Invalid question length"}}
        },
    },
    429: _RATE_LIMITED,
    502: {
        "model": UpstreamError,
        "description": "El modelo no está disponible.",
        "content": {
            "application/json": {
                "example": {"detail": "model unavailable", "request_id": "req-1"}
            }
        },
    },
}
METRICS_RESPONSES = {
    200: {"description": "Foto actual de las métricas del proceso."},
    401: _UNAUTHORIZED,
    429: _RATE_LIMITED,
}
