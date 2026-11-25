"""Agente principal de RH: supervisor ReAct que delega en especialistas.

Tiene dos herramientas propias de consulta (``get_employee`` y
``search_by_department``) y dos que delegan en subagentes:

- ``vacation_balance`` → :class:`~app.agents.vacation_agent.VacationAgent` (ReAct).
- ``department_summary`` → :class:`~app.agents.summary_agent.SummaryAgent` (reflection).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.agents.react import ReactAgent, Tool
from app.agents.runtime import RunContext
from app.agents.summary_agent import SummaryAgent
from app.agents.vacation_agent import VacationAgent
from app.domain.directory import EMPLOYEE_ID_PATTERN, Directory

GIVE_UP = "No pude completar la respuesta. Intenta con una pregunta más concreta."
SYSTEM_PROMPT = (
    "[agent:hr] HRA-SYSTEM-PROMPT. Eres el asistente de Recursos Humanos. Respondes "
    "SOLO "
    "con UN objeto JSON y nada más. Herramienta: "
    '{"thought":"<por qué>","tool":"<nombre>","args":{...}}. Respuesta final: '
    '{"answer":"<respuesta breve en español>"}. Herramientas: '
    'get_employee{"employee_id"}; search_by_department{"department"}; '
    'vacation_balance{"employee_id"}; department_summary{"department"}. '
    "Departamentos: {departments}. Si la pregunta menciona un id EMP-#### o un "
    "departamento, SIEMPRE usa una herramienta antes de responder; nunca respondas "
    "datos de memoria. Tras un Resultado de la herramienta responde con answer usando "
    "solo ese resultado. Nunca des CURP, RFC, NSS, salario, correo ni teléfono. "
    "Marcadores como [EMAIL] o [PHONE] son datos que el sistema ocultó por "
    "privacidad: ignóralos y responde la pregunta. "
    "Ejemplos: ¿Quién es EMP-0002? -> "
    '{"thought":"Busco al '
    'empleado","tool":"get_employee","args":{"employee_id":"EMP-0002"}} '
    "¿Vacaciones de EMP-0003? -> "
    '{"thought":"Delego","tool":"vacation_balance","args":{"employee_id":"EMP-0003"}} '
    "¿Quiénes están en Ventas? -> "
    '{"thought":"Listo el '
    'área","tool":"search_by_department","args":{"department":"Ventas"}} '
    "Resume el área de Ventas -> "
    '{"thought":"Delego","tool":"department_summary","args":{"department":"Ventas"}} '
    "¿Qué hora es? -> "
    '{"answer":"Solo atiendo preguntas de RH: pregúntame por un empleado o un área."}'
)
VERBOSE_SUFFIX = (
    " Eres un asistente profesional, amable y muy cuidadoso. Piensa paso a paso antes "
    "de elegir una herramienta, explica tu razonamiento en el campo thought con "
    "detalle "
    'y revisa que el JSON sea válido. Ejemplos: {"thought":"Piden a un empleado",'
    '"tool":"get_employee","args":{"employee_id":"EMP-0001"}} y '
    '{"answer":"Ana López es Analista de datos en Tecnología"}. Si el resultado de '
    "una herramienta no basta, usa otra. Responde siempre en español neutro."
)


class EmployeeArgs(BaseModel):
    """Argumentos con un id de empleado."""

    employee_id: str = Field(pattern=EMPLOYEE_ID_PATTERN.pattern)


class DepartmentArgs(BaseModel):
    """Argumentos con un departamento."""

    department: str = Field(min_length=2, max_length=60)


class HrAgent:
    """Supervisor que responde preguntas de RH.

    :param directory: Directorio de empleados
    :type directory: Directory
    :param vacations: Subagente de vacaciones
    :type vacations: VacationAgent
    :param summaries: Subagente de resumen
    :type summaries: SummaryAgent
    """

    def __init__(
        self, directory: Directory, vacations: VacationAgent, summaries: SummaryAgent
    ) -> None:
        self._directory = directory
        self._vacations = vacations
        self._summaries = summaries
        self._agent = ReactAgent(
            "hr_agent",
            [
                Tool("get_employee", EmployeeArgs, self._get_employee),
                Tool("search_by_department", DepartmentArgs, self._search),
                Tool(
                    "vacation_balance", EmployeeArgs, self._vacation, return_direct=True
                ),
                Tool(
                    "department_summary",
                    DepartmentArgs,
                    self._summary,
                    return_direct=True,
                ),
            ],
            GIVE_UP,
            requires_tool=self._mentions_directory,
        )

    def _mentions_directory(self, messages: list[dict]) -> bool:
        """Regla de código: la última pregunta menciona un empleado o un área."""
        question = next(
            (
                m["content"]
                for m in reversed(messages)
                if m["role"] == "user" and not m["content"].startswith("Recordatorio")
            ),
            "",
        )
        return bool(
            re.search(r"EMP-\d{4}", question, re.IGNORECASE)
            or self._directory.resolve_department(question)
        )

    @property
    def graph(self):
        """Grafo compilado de LangGraph."""
        return self._agent.graph

    def system_prompt(self, compact: bool) -> str:
        """Mensaje de sistema con los departamentos vigentes.

        :param compact: Sin el texto extra de la línea base
        :type compact: bool
        :return: Mensaje de sistema
        :rtype: str
        """
        text = SYSTEM_PROMPT.replace(
            "{departments}", ", ".join(self._directory.departments())
        )
        return text if compact else text + VERBOSE_SUFFIX

    async def _get_employee(self, args: EmployeeArgs, ctx: RunContext):
        del ctx
        employee = self._directory.get(args.employee_id)
        if employee is None:
            return f"No existe un empleado con id {args.employee_id}."
        return employee.public_dict()

    def _department_or_error(self, text: str) -> tuple[str | None, str]:
        name = self._directory.resolve_department(text)
        if name is None:
            known = ", ".join(self._directory.departments())
            return None, f"No hay un departamento '{text}'. Existen: {known}."
        return name, ""

    async def _search(self, args: DepartmentArgs, ctx: RunContext):
        del ctx
        name, error = self._department_or_error(args.department)
        if name is None:
            return error
        return [e.public_dict() for e in self._directory.by_department(name)]

    async def _vacation(self, args: EmployeeArgs, ctx: RunContext):
        report = await self._vacations.run(args.employee_id, "saldo de vacaciones", ctx)
        ctx.details["vacation"] = report
        return {"answer": report["answer"], "balance_days": report.get("balance_days")}

    async def _summary(self, args: DepartmentArgs, ctx: RunContext):
        name, error = self._department_or_error(args.department)
        if name is None:
            return error
        report = await self._summaries.run(name, ctx)
        ctx.details["summary"] = report
        return {"answer": report["answer"]}

    async def run(
        self, question: str, history: list[dict], ctx: RunContext, max_steps: int
    ) -> dict:
        """Responde una pregunta.

        :param question: Pregunta ya revisada (sin PII)
        :type question: str
        :param history: Historial ya recortado a la ventana
        :type history: list[dict]
        :param ctx: Contexto de la corrida
        :type ctx: RunContext
        :param max_steps: Tope de pasos
        :type max_steps: int
        :return: ``answer``, ``steps``, ``tools_used``, ``thoughts``, ``stopped``
        :rtype: dict
        """
        messages = (
            [{"role": "system", "content": self.system_prompt(ctx.compact)}]
            + history
            + [{"role": "user", "content": question}]
        )
        state = await self._agent.run(messages, ctx, max_steps)
        return {
            "answer": state.get("answer", ""),
            "steps": state.get("steps", 0),
            "tools_used": state.get("tools_used", []),
            "thoughts": state.get("thoughts", []),
            "stopped": state.get("stopped", False),
            "parse_errors": state.get("parse_errors", 0),
        }
