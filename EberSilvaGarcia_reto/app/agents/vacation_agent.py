"""Agente de vacaciones (patrón ReAct con LangGraph).

Razona paso a paso con tres herramientas de solo lectura: confirma que el
empleado existe y está activo, calcula los días que le corresponden según la
LFT y consulta los días tomados en el periodo vigente.

Los números del reporte los pone el **código** a partir de las observaciones;
el modelo solo los explica. Si la explicación no cuadra con el saldo
calculado, se reemplaza por una plantilla (guarda contra alucinaciones).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.agents.react import ReactAgent, Tool
from app.agents.runtime import RunContext
from app.domain.directory import EMPLOYEE_ID_PATTERN, Directory
from app.domain.vacations import (
    VacationLedger,
    current_period,
    entitled_days,
    years_between,
)

SYSTEM_PROMPT = (
    "[agent:vacation] HRA-SYSTEM-PROMPT. Eres el especialista en vacaciones de RH "
    "(LFT México, art. 76). Respondes SOLO con UN objeto JSON. Cada paso DEBE incluir "
    '"thought" con tu razonamiento en una frase. Herramienta: '
    '{"thought":"<por qué>","tool":"<nombre>","args":{...}}. Final: '
    '{"thought":"<conclusión>","answer":"<explicación breve con los números>"}. '
    "Herramientas, en este orden: get_employee{employee_id}; "
    "compute_entitlement{employee_id}; get_taken_days{employee_id,period_start,"
    "period_end} con el period_start y period_end de compute_entitlement. No inventes "
    "números. Si el empleado no existe o está de baja, responde de inmediato. Ejemplo: "
    '{"thought":"Primero confirmo que el empleado existe y está activo",'
    '"tool":"get_employee","args":{"employee_id":"EMP-0002"}} -> '
    '{"thought":"Está activo; calculo los días que le tocan por antigüedad",'
    '"tool":"compute_entitlement","args":{"employee_id":"EMP-0002"}} -> '
    '{"thought":"Le tocan 20 días; reviso los tomados en el periodo vigente",'
    '"tool":"get_taken_days","args":{"employee_id":"EMP-0002",'
    '"period_start":"2026-07-19","period_end":"2027-07-19"}} -> '
    '{"thought":"Tomó 4 de 20; el saldo es 16","answer":"Le quedan 16 días."}'
)
VERBOSE_SUFFIX = (
    " Recuerda: eres un asistente cuidadoso, profesional y amable. Explica cada paso "
    "con detalle, revisa dos veces tu razonamiento y sigue siempre el formato JSON. "
    'Ejemplo de herramienta: {"thought":"Necesito el empleado","tool":'
    '"get_employee","args":{"employee_id":"EMP-0001"}}. Ejemplo de respuesta: '
    '{"answer":"Le quedan 5 días"}.'
)
GIVE_UP = "No pude calcular el saldo de vacaciones. Intenta de nuevo."


class EmployeeArgs(BaseModel):
    """Argumentos con un id de empleado.

    Si el modelo lo omite, se usa el empleado del alcance del subagente: lo que
    el código ya sabe no se le pide al modelo.
    """

    employee_id: str | None = Field(default=None, pattern=EMPLOYEE_ID_PATTERN.pattern)


class TakenArgs(EmployeeArgs):
    """Argumentos para consultar días tomados; sin periodo, se usa el vigente."""

    period_start: date | None = None
    period_end: date | None = None


class VacationAgent:
    """Especialista en saldo de vacaciones.

    :param directory: Directorio de empleados
    :type directory: Directory
    :param ledger: Registro de días tomados
    :type ledger: VacationLedger
    :param max_steps: Tope de pasos del bucle ReAct
    :type max_steps: int
    """

    def __init__(
        self, directory: Directory, ledger: VacationLedger, max_steps: int
    ) -> None:
        self._directory = directory
        self._ledger = ledger
        self._max_steps = max_steps
        self._agent = ReactAgent(
            "vacation_agent",
            [
                Tool("get_employee", EmployeeArgs, self._get_employee),
                Tool("compute_entitlement", EmployeeArgs, self._entitlement),
                Tool("get_taken_days", TakenArgs, self._taken),
            ],
            GIVE_UP,
        )

    @property
    def graph(self):
        """Grafo compilado de LangGraph (para inspeccionarlo o dibujarlo)."""
        return self._agent.graph

    @staticmethod
    def _scoped_id(args: EmployeeArgs, ctx: RunContext) -> tuple[str, str | None]:
        """Id a consultar y, si se sale del alcance, el mensaje de rechazo."""
        # Mínimo privilegio: el subagente solo puede consultar al empleado pedido
        allowed = ctx.scope_employee
        wanted = args.employee_id or allowed or ""
        if allowed and wanted != allowed:
            ctx.audit("tool_rejected", agent="vacation_agent", reason="out_of_scope")
            return wanted, f"Solo puedes consultar al empleado {allowed}."
        return wanted, None

    async def _get_employee(self, args: EmployeeArgs, ctx: RunContext):
        employee_id, error = self._scoped_id(args, ctx)
        if error:
            return error
        employee = self._directory.get(employee_id)
        if employee is None:
            return f"No existe un empleado con id {employee_id}."
        return employee.public_dict()

    async def _entitlement(self, args: EmployeeArgs, ctx: RunContext):
        employee_id, error = self._scoped_id(args, ctx)
        if error:
            return error
        employee = self._directory.get(employee_id)
        if employee is None:
            return f"No existe un empleado con id {employee_id}."
        years = years_between(employee.start_date, ctx.as_of)
        period = current_period(employee.start_date, ctx.as_of)
        return {
            "years_of_service": years,
            "entitled_days": entitled_days(years),
            "period_start": period.start.isoformat() if period else None,
            "period_end": period.end.isoformat() if period else None,
        }

    async def _taken(self, args: TakenArgs, ctx: RunContext):
        employee_id, error = self._scoped_id(args, ctx)
        if error:
            return error
        start, end = args.period_start, args.period_end
        if start is None or end is None:
            employee = self._directory.get(employee_id)
            period = employee and current_period(employee.start_date, ctx.as_of)
            if not period:
                return {"taken_days": 0}
            start, end = period.start, period.end
        return {"taken_days": self._ledger.taken_between(employee_id, start, end)}

    def _ground_truth(self, employee_id: str, as_of: date) -> dict:
        """Calcula por código el reporte que el agente debió obtener."""
        employee = self._directory.get(employee_id)
        if employee is None:
            return {"employee_id": employee_id, "found": False}
        report = {
            "employee_id": employee.id,
            "found": True,
            "name": employee.name,
            "status": employee.status,
            "years_of_service": years_between(employee.start_date, as_of),
        }
        period = current_period(employee.start_date, as_of)
        if not employee.is_active or period is None:
            return {
                **report,
                "entitled_days": 0,
                "taken_days": 0,
                "balance_days": 0,
                "period_start": None,
                "period_end": None,
            }
        entitled = entitled_days(report["years_of_service"])
        taken = self._ledger.taken_between(employee.id, period.start, period.end)
        return {
            **report,
            "entitled_days": entitled,
            "taken_days": taken,
            "balance_days": entitled - taken,
            "period_start": period.start.isoformat(),
            "period_end": period.end.isoformat(),
        }

    @staticmethod
    def _template(report: dict) -> str:
        if not report["found"]:
            return f"No existe un empleado con id {report['employee_id']}."
        if report["status"] != "activo":
            return f"{report['name']} ya no está activo; no tiene saldo de vacaciones."
        if not report["entitled_days"]:
            return (
                f"{report['name']} aún no cumple un año: todavía no tiene vacaciones."
            )
        return (
            f"{report['name']} tiene {report['years_of_service']} años de servicio, le "
            f"corresponden {report['entitled_days']} días, ha tomado "
            f"{report['taken_days']} y le quedan {report['balance_days']} días."
        )

    @staticmethod
    def _verify(answer: str, report: dict) -> bool:
        """El código decide si la explicación del modelo es fiel al cálculo.

        Solo se acepta texto libre del modelo cuando hay un saldo que citar; los
        casos sin saldo (no existe, baja, menos de un año) usan la plantilla.
        """
        if not report.get("found") or report.get("status") != "activo":
            return False
        if not report.get("entitled_days"):
            return False
        return str(report["balance_days"]) in answer

    async def run(self, employee_id: str, question: str, ctx: RunContext) -> dict:
        """Calcula el saldo de vacaciones de un empleado razonando con ReAct.

        :param employee_id: Id del empleado
        :type employee_id: str
        :param question: Pregunta original (ya sin PII)
        :type question: str
        :param ctx: Contexto de la corrida
        :type ctx: RunContext
        :return: Reporte con números calculados por código, la explicación,
            los pasos de razonamiento y si hubo que corregir al modelo
        :rtype: dict
        """
        employee_id = employee_id.strip().upper()
        ctx.scope_employee = employee_id
        system = SYSTEM_PROMPT if ctx.compact else SYSTEM_PROMPT + VERBOSE_SUFFIX
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Empleado: {employee_id}. Fecha de corte: "
                    f"{ctx.as_of.isoformat()}. "
                    f"Pregunta: {question}"
                ),
            },
        ]
        try:
            state = await self._agent.run(messages, ctx, self._max_steps)
        finally:
            ctx.scope_employee = None
        report = self._ground_truth(employee_id, ctx.as_of)
        answer = state.get("answer", "")
        verified = self._verify(answer, report)
        if not verified:
            ctx.audit(
                "output_corrected", agent="vacation_agent", reason="numbers_mismatch"
            )
            answer = self._template(report)
        return {
            **report,
            "answer": answer,
            "verified_by_code": True,
            "model_answer_kept": bool(verified),
            "reasoning": state.get("thoughts", [])
            + (
                []
                if verified
                else [
                    "Verificación por código: la conclusión del modelo no cuadraba "
                    f"con el cálculo; se entrega el saldo verificado "
                    f"({report.get('balance_days', 0)} días)."
                ]
            ),
            "tools_used": state.get("tools_used", []),
            "steps": state.get("steps", 0),
            "stopped": state.get("stopped", False),
        }
