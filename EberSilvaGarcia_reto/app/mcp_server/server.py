"""Servidor MCP del HR Assistant (adaptador delgado sobre :class:`HrService`).

Expone herramientas con esquema de entrada y de salida validados:

- ``vacation_balance``: agente LangGraph con patrón **ReAct**.
- ``department_summary``: agente LangGraph con patrón **reflection**.
- ``ask_hr``: el supervisor, que decide a qué especialista delegar.

Además publica el recurso ``hr://departments`` y el prompt
``vacation_review``. Aquí no hay lógica de agentes: solo validación del
protocolo, correlation id, auditoría y traducción de errores a ``ToolError``.
"""

import uuid
from typing import Annotated, Awaitable, Callable, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from app.domain.directory import EMPLOYEE_ID_PATTERN, NotFoundError
from app.llm.base import ModelUnavailable
from app.observability.logs import channel_var, client_var, request_id_var
from app.security.guards import GuardRejection
from app.service import HrService

INSTRUCTIONS = (
    "Herramientas de Recursos Humanos. Usa vacation_balance para saber cuántos días de "
    "vacaciones le quedan a un empleado (id EMP-0000), department_summary para "
    "resumir un área y ask_hr para preguntas libres. Los datos personales (CURP, RFC, "
    "NSS, salario, contacto) están protegidos y nunca se devuelven."
)
READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
T = TypeVar("T")


class Usage(BaseModel):
    """Costo y latencia de la llamada."""

    model: str
    model_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float


class VacationReport(BaseModel):
    """Saldo de vacaciones calculado por el agente ReAct."""

    request_id: str
    employee_id: str
    found: bool
    name: str | None = None
    status: str | None = None
    years_of_service: int | None = None
    entitled_days: int | None = None
    taken_days: int | None = None
    balance_days: int | None = None
    period_start: str | None = None
    period_end: str | None = None
    answer: str
    reasoning: list[str] = Field(description="Pensamientos del agente en cada paso")
    tools_used: list[str]
    model_answer_kept: bool = Field(
        description="False si el código corrigió la explicación del modelo"
    )
    usage: Usage


class DepartmentSummary(BaseModel):
    """Resumen de un área producido con reflexión."""

    request_id: str
    department: str
    answer: str
    facts: dict
    reflection_rounds: int
    critiques: list[list[str]] = Field(description="Críticas de cada vuelta")
    accepted: bool
    fallback: bool
    usage: Usage


class HrAnswer(BaseModel):
    """Respuesta del supervisor de RH."""

    request_id: str
    answer: str
    intent: str
    tools_used: list[str]
    reasoning: list[str]
    pii_detected: list[str]
    usage: Usage


def _fields(model: type[BaseModel]) -> set[str]:
    """Nombres de campo de un modelo de Pydantic."""
    return set(model.model_fields.keys())  # pylint: disable=no-member


def _pick(data: dict, model: type[BaseModel]) -> dict:
    """Solo las llaves que el esquema de salida declara (nada extra al host)."""
    allowed = _fields(model)
    return {key: value for key, value in data.items() if key in allowed}


def _usage(report: dict) -> Usage:
    return Usage(**_pick(report, Usage))


class McpAdapter:
    """Une el protocolo MCP con los casos de uso.

    :param service: Casos de uso del producto
    :type service: HrService
    :param default_client: Cliente para el log cuando no hay autenticación HTTP
    :type default_client: str
    """

    def __init__(self, service: HrService, default_client: str = "mcp-stdio") -> None:
        self._service = service
        self._default_client = default_client

    async def call(self, tool: str, action: Callable[[], Awaitable[T]]) -> T:
        """Corre una herramienta con correlation id, auditoría y errores claros.

        :param tool: Nombre de la herramienta
        :type tool: str
        :param action: Corutina que hace el trabajo
        :type action: Callable
        :return: Lo que devuelve ``action``
        :raises ToolError: Con un mensaje en español apto para el host
        """
        logger = self._service.s.logger
        # Por HTTP se conserva el request_id de la petición; por stdio se genera uno
        current = request_id_var.get()
        tokens = [
            request_id_var.set(current if current != "-" else str(uuid.uuid4())),
            channel_var.set("mcp"),
        ]
        if client_var.get() == "-":
            tokens.append(client_var.set(self._default_client))
        status = "ok"
        try:
            return await action()
        except GuardRejection as exc:
            status = f"rejected:{exc.reason}"
            raise ToolError(
                f"La política de seguridad rechazó la entrada ({exc.reason})."
            ) from exc
        except NotFoundError as exc:
            status = "not_found"
            raise ToolError(str(exc)) from exc
        except ModelUnavailable as exc:
            status = "model_unavailable"
            raise ToolError(
                "El modelo no está disponible; intenta en unos minutos."
            ) from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            status = "error"
            logger.event("error", error_type=type(exc).__name__, tool=tool)
            raise ToolError(
                f"Error interno. Reporta el request_id {request_id_var.get()}."
            ) from exc
        finally:
            logger.audit("mcp_tool_call", tool=tool, status=status)
            self._service.s.metrics.increment(f"mcp_{tool}_{status.split(':')[0]}")
            for token in reversed(tokens):
                token.var.reset(token)


def build_mcp_server(
    service: HrService, default_client: str = "mcp-stdio"
) -> MCPServer:
    """Crea el servidor MCP con sus herramientas, recurso y prompt.

    :param service: Casos de uso del producto
    :type service: HrService
    :param default_client: Nombre del cliente cuando no hay clave (stdio)
    :type default_client: str
    :return: Servidor listo para ``run()`` o para montarlo en la API
    :rtype: MCPServer
    """
    adapter = McpAdapter(service, default_client)
    server = MCPServer(
        name="hr-assistant",
        title="HR Assistant",
        instructions=INSTRUCTIONS,
        version="1.0.0",
    )

    @server.tool(title="Saldo de vacaciones", annotations=READ_ONLY)
    async def vacation_balance(
        employee_id: Annotated[
            str,
            Field(
                pattern=EMPLOYEE_ID_PATTERN.pattern,
                description="Id del empleado, por ejemplo EMP-0004",
            ),
        ],
        context: Annotated[
            str, Field(max_length=500, description="Contexto opcional de la consulta")
        ] = "",
    ) -> VacationReport:
        """Calcula cuántos días de vacaciones le quedan a un empleado (LFT art. 76).

        Un agente ReAct confirma al empleado, calcula los días por antigüedad y
        revisa los días tomados en el periodo vigente.
        """

        async def action() -> VacationReport:
            report = await service.vacation(employee_id, context)
            return VacationReport(
                request_id=request_id_var.get(),
                usage=_usage(report),
                **_pick(report, VacationReport),
            )

        return await adapter.call("vacation_balance", action)

    @server.tool(title="Resumen por área", annotations=READ_ONLY)
    async def department_summary(
        department: Annotated[
            str,
            Field(
                min_length=2,
                max_length=60,
                description="Departamento, por ejemplo Tecnología, Ventas o Finanzas",
            ),
        ],
    ) -> DepartmentSummary:
        """Resume un área: plantilla, activos, bajas, puestos y antigüedad promedio.

        Un agente con reflexión redacta, un crítico por código revisa los números
        y el agente corrige hasta que el resumen es fiel a los datos.
        """

        async def action() -> DepartmentSummary:
            report = await service.summary(department)
            return DepartmentSummary(
                request_id=request_id_var.get(),
                usage=_usage(report),
                **_pick(report, DepartmentSummary),
            )

        return await adapter.call("department_summary", action)

    @server.tool(title="Pregunta libre a RH", annotations=READ_ONLY)
    async def ask_hr(
        question: Annotated[
            str,
            Field(
                min_length=1,
                max_length=service.s.settings.max_question_chars,
                description="Pregunta en español sobre empleados, áreas o vacaciones",
            ),
        ],
    ) -> HrAnswer:
        """Responde una pregunta libre; el supervisor delega en el especialista."""

        async def action() -> HrAnswer:
            body = await service.ask(question, [])
            return HrAnswer(
                request_id=request_id_var.get(),
                usage=_usage(body),
                **_pick(body, HrAnswer),
            )

        return await adapter.call("ask_hr", action)

    @server.resource(
        "hr://departments",
        name="departments",
        mime_type="application/json",
        description="Departamentos que existen en el directorio",
    )
    def departments() -> list[str]:
        """Lista de departamentos."""
        return service.s.directory.departments()

    @server.prompt(name="vacation_review", title="Revisar vacaciones de un empleado")
    def vacation_review(employee_id: str) -> str:
        """Plantilla para pedir al host un análisis de vacaciones."""
        return (
            f"Usa la herramienta vacation_balance con employee_id={employee_id} y "
            "explica "
            "el resultado a la persona de RH en tres viñetas: días que le "
            "corresponden, "
            "días tomados y saldo."
        )

    return server
