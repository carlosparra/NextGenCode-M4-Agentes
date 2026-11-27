"""Servidor MCP del HR Assistant.

Cada herramienta ejecuta por dentro un agente LangGraph:

- ``ask_hr``: supervisor que delega en especialistas (ReAct).
- ``vacation_balance``: agente ReAct de vacaciones, con cifras verificadas.
- ``department_summary``: agente de reflexión (borrador, crítica y revisión).

Transportes: ``stdio`` (``python -m app.mcp_server``) y HTTP en ``/mcp``, montado
en la misma aplicación FastAPI.
"""

import sys

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from app.config import load_settings
from app.directory import NotFoundError
from app.guards import GuardBlocked
from app.llm import ModelUnavailable
from app.logs import JsonLogger, channel_var, client_var, request_id_var
from app.clock import SystemClock
from app.service import HRService

INSTRUCTIONS = (
    "Herramientas de Recursos Humanos. Usa ask_hr para preguntas generales, "
    "vacation_balance para el saldo de vacaciones de un empleado (EMP-0001) y "
    "department_summary para el resumen de un departamento. Ninguna herramienta "
    "entrega datos personales."
)
LOCAL_HOSTS = ["127.0.0.1:*", "localhost:*", "127.0.0.1", "localhost"]


class AgentAnswer(BaseModel):
    """Respuesta de un agente, con su razonamiento y su costo."""

    answer: str = Field(description="Respuesta en español")
    agent: str = Field(description="Agente LangGraph que respondió")
    reasoning: list[str] = Field(description="Pasos de razonamiento del agente")
    tools_used: list[str] = Field(description="Herramientas internas que usó")
    steps: int = Field(description="Llamadas al modelo")
    model: str = Field(description="Modelo elegido por el enrutador")
    cost_usd: float = Field(description="Costo de la respuesta en USD")
    request_id: str = Field(description="Id para buscar la traza y los logs")


class VacationAnswer(AgentAnswer):
    """Saldo de vacaciones con las cifras calculadas en código."""

    eligible: bool = Field(description="Si el empleado genera vacaciones")
    years_of_service: int = Field(description="Años cumplidos")
    entitled_days: int = Field(description="Días que marca la LFT")
    taken_days: int = Field(description="Días tomados en el periodo")
    remaining_days: int = Field(description="Días que le quedan")
    period_start: str = Field(description="Inicio del periodo vigente")
    period_end: str = Field(description="Fin del periodo vigente")


COMMON_FIELDS = tuple(AgentAnswer.model_fields.keys())
BALANCE_FIELDS = tuple(
    name for name in VacationAnswer.model_fields.keys() if name not in COMMON_FIELDS
)


def _common(response: dict) -> dict:
    return {name: response[name] for name in COMMON_FIELDS}


async def _run(service: HRService, operation, *args) -> dict:
    """Corre una operación del servicio en un hilo y traduce sus errores."""
    try:
        return await anyio.to_thread.run_sync(operation, *args)
    except GuardBlocked as blocked:
        raise ToolError(f"Petición bloqueada: {blocked.reason}") from None
    except (NotFoundError, ValueError) as error:
        raise ToolError(str(error)) from None
    except ModelUnavailable:
        service.logger.event("error", error_type="ModelUnavailable")
        raise ToolError("El modelo no está disponible. Intenta más tarde.") from None


def build_mcp(service: HRService) -> MCPServer:
    """Crea el servidor MCP sobre un servicio ya construido.

    :param service: Servicio con los agentes
    :type service: HRService
    :return: Servidor con tres herramientas, un recurso y un prompt
    :rtype: MCPServer
    """
    server = MCPServer("hr-assistant", instructions=INSTRUCTIONS)

    @server.tool(description="Pregunta de RH; un supervisor la reparte a un agente.")
    async def ask_hr(question: str) -> AgentAnswer:
        """Responde una pregunta sobre empleados, vacaciones o departamentos."""
        limit = service.settings.max_question_chars
        if not question.strip() or len(question) > limit:
            raise ToolError(f"question debe tener entre 1 y {limit} caracteres")
        return AgentAnswer(**_common(await _run(service, service.ask, question)))

    @server.tool(description="Saldo de vacaciones (LFT) de un empleado, por id.")
    async def vacation_balance(employee_id: str) -> VacationAnswer:
        """Calcula el saldo de vacaciones con el agente ReAct de vacaciones."""
        response = await _run(service, service.vacation_balance, employee_id)
        balance = response["balance"]
        fields = {name: balance[name] for name in BALANCE_FIELDS}
        return VacationAnswer(**_common(response), **fields)

    @server.tool(description="Resumen verificado de un departamento (reflexión).")
    async def department_summary(department: str) -> AgentAnswer:
        """Resume un departamento con borrador, crítica y revisión."""
        response = await _run(service, service.department_summary, department)
        return AgentAnswer(**_common(response))

    @server.resource("hr://departments", mime_type="application/json")
    def departments() -> list[str]:
        """Departamentos que existen en el directorio."""
        return service.directory.departments()

    @server.prompt(description="Revisión del saldo de vacaciones de un empleado.")
    def vacation_review(employee_id: str) -> str:
        """Prompt listo para revisar las vacaciones de un empleado."""
        return (
            f"Usa vacation_balance con {employee_id}. Explica cuántos días le "
            "corresponden por ley, cuántos ha tomado y cuántos le quedan, y sugiere "
            "cuándo conviene programarlos."
        )

    return server


def http_app(server: MCPServer, allowed_hosts: tuple):
    """Aplicación ASGI del MCP por HTTP, sin estado.

    :param server: Servidor MCP
    :type server: MCPServer
    :param allowed_hosts: Hosts públicos permitidos, además de los locales
    :type allowed_hosts: tuple
    :return: Aplicación Starlette que atiende ``/mcp``
    """
    hosts = LOCAL_HOSTS + [h for host in allowed_hosts for h in (host, f"{host}:*")]
    origins = [f"{scheme}://{host}" for host in hosts for scheme in ("http", "https")]
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=origins,
        ),
    )


def main() -> None:
    """Corre el servidor por stdio; el log va a stderr para no romper el protocolo."""
    settings = load_settings()
    clock = SystemClock()
    logger = JsonLogger(settings.service_name, clock, stream=sys.stderr)
    service = HRService(settings, clock=clock, logger=logger)
    channel_var.set("mcp-stdio")
    client_var.set("local-stdio")
    request_id_var.set("stdio-session")
    build_mcp(service).run("stdio")


if __name__ == "__main__":
    main()
