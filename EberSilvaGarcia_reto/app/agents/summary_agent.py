"""Agente de resumen por área (patrón reflection con LangGraph).

::

    START -> gather_facts -> draft -> critique --ok--> finalize -> END
                                        |   ^
                              cambios   |   | nuevo borrador
                                        v   |
                                       revise
                                (máx. REFLECTION_MAX_ROUNDS)

- ``gather_facts`` calcula por código los hechos del área (sin modelo).
- ``draft`` y ``revise`` los redacta el modelo.
- ``critique`` lo hace el **código**: comprueba que el borrador cite los números
  correctos, no nombre a personas de otras áreas, no traiga PII y no sea largo.
  Es determinista y no cuesta tokens.
- Si se agotan las vueltas, ``finalize`` usa una plantilla segura.
"""

from __future__ import annotations

import json
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.runtime import RunContext
from app.domain.departments import DepartmentFacts, department_facts
from app.domain.directory import Directory
from app.security import pii

SYSTEM_PROMPT = (
    "[agent:summary] HRA-SYSTEM-PROMPT. Eres analista de RH. Redacta en español un "
    "resumen de máximo 80 palabras del área usando SOLO los hechos dados. Incluye "
    "cuántas personas hay, cuántas activas y de baja, los puestos y la antigüedad "
    "promedio del personal activo. No incluyas datos personales. Responde solo el "
    "texto."
)
VERBOSE_SUFFIX = (
    " Recuerda que eres un analista profesional, cuidadoso y amable. Escribe con un "
    "tono "
    "cálido y claro, revisa la ortografía y asegúrate de mencionar cada dato. "
    "Antes de responder, verifica que todo sea correcto y que el resumen sea útil."
)
MAX_SUMMARY_CHARS = 900


class SummaryState(TypedDict, total=False):
    """Estado del grafo de reflexión."""

    department: str
    facts: dict
    messages: list[dict]
    draft: str
    critique: list[str]
    critiques: list[list[str]]
    rounds: int
    accepted: bool
    fallback: bool


def critique_draft(draft: str, facts: dict, other_names: list[str]) -> list[str]:
    """El crítico: lista lo que el borrador hace mal (vacía si está bien).

    :param draft: Borrador del modelo
    :type draft: str
    :param facts: Hechos del área
    :type facts: dict
    :param other_names: Nombres de personas de otras áreas
    :type other_names: list[str]
    :return: Observaciones concretas para corregir
    :rtype: list[str]
    """
    issues = []
    numbers = set(re.findall(r"\d+(?:[.,]\d+)?", draft))
    numbers |= {n.replace(",", ".") for n in numbers}
    for key, label in (
        ("headcount", "total de personas"),
        ("active", "personas activas"),
    ):
        if str(facts[key]) not in numbers:
            issues.append(f"Falta o es incorrecto el {label}: debe ser {facts[key]}.")
    if facts["active"] and str(facts["avg_tenure_years"]) not in numbers:
        issues.append(
            f"Falta la antigüedad promedio del personal activo: "
            f"{facts['avg_tenure_years']} años."
        )
    leaked = [name for name in other_names if name in draft]
    if leaked:
        issues.append("Menciona a personas que no son del área; quítalas.")
    if pii.scan(draft, include_amounts=True).found:
        issues.append("Incluye datos personales; quítalos.")
    if len(draft) > MAX_SUMMARY_CHARS:
        issues.append("Es demasiado largo; resume en menos de 80 palabras.")
    if not draft.strip():
        issues.append("El resumen está vacío.")
    return issues


def template_summary(facts: dict) -> str:
    """Resumen seguro por plantilla, para cuando el modelo no converge.

    :param facts: Hechos del área
    :type facts: dict
    :return: Resumen
    :rtype: str
    """
    roles = ", ".join(f"{role} ({count})" for role, count in facts["roles"].items())
    return (
        f"El área de {facts['department']} tiene {facts['headcount']} personas: "
        f"{facts['active']} activas y {facts['inactive']} de baja. Puestos activos: "
        f"{roles or 'ninguno'}. Antigüedad promedio del personal activo: "
        f"{facts['avg_tenure_years']} años."
    )


class SummaryAgent:
    """Especialista en resumir un área con autocrítica.

    :param directory: Directorio de empleados
    :type directory: Directory
    :param max_rounds: Vueltas máximas de revisión
    :type max_rounds: int
    """

    def __init__(self, directory: Directory, max_rounds: int) -> None:
        self._directory = directory
        self._max_rounds = max_rounds
        self.graph = self._build()

    def _build(self):
        graph = StateGraph(SummaryState)
        graph.add_node("gather_facts", self._gather)
        graph.add_node("draft", self._draft)
        graph.add_node("critique", self._critique)
        graph.add_node("revise", self._revise)
        graph.add_node("finalize", self._finalize)
        graph.add_edge(START, "gather_facts")
        graph.add_edge("gather_facts", "draft")
        graph.add_edge("draft", "critique")
        graph.add_conditional_edges(
            "critique",
            self._after_critique,
            {"revise": "revise", "finalize": "finalize"},
        )
        graph.add_edge("revise", "critique")
        graph.add_edge("finalize", END)
        return graph.compile(name="summary_agent")

    async def _gather(self, state: SummaryState, config) -> SummaryState:
        ctx: RunContext = config["configurable"]["ctx"]
        employees = self._directory.by_department(state["department"])
        facts: DepartmentFacts = department_facts(
            state["department"], employees, ctx.as_of
        )
        ctx.audit(
            "tool_call",
            agent="summary_agent",
            tool="department_facts",
            args={"department": state["department"]},
        )
        data = facts.as_dict()
        payload = {k: v for k, v in data.items() if k != "active_names"}
        text = json.dumps(
            payload,
            ensure_ascii=False,
            **({"separators": (",", ":")} if ctx.compact else {"indent": 2}),
        )
        system = SYSTEM_PROMPT if ctx.compact else SYSTEM_PROMPT + VERBOSE_SUFFIX
        return {
            "facts": data,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Hechos: {text}"},
            ],
        }

    @staticmethod
    async def _draft(state: SummaryState, config) -> SummaryState:
        ctx: RunContext = config["configurable"]["ctx"]
        draft = (
            await ctx.llm.chat(state["messages"], agent="summary_agent.draft")
        ).strip()
        return {"draft": draft, "rounds": 0, "critiques": []}

    async def _critique(self, state: SummaryState) -> SummaryState:
        department = state["department"]
        others = [
            employee.name
            for name in self._directory.departments()
            if name != department
            for employee in self._directory.by_department(name)
        ]
        issues = critique_draft(state["draft"], state["facts"], others)
        return {"critique": issues, "critiques": state.get("critiques", []) + [issues]}

    def _after_critique(self, state: SummaryState) -> str:
        if not state["critique"] or state.get("rounds", 0) >= self._max_rounds:
            return "finalize"
        return "revise"

    @staticmethod
    async def _revise(state: SummaryState, config) -> SummaryState:
        ctx: RunContext = config["configurable"]["ctx"]
        messages = state["messages"] + [
            {"role": "assistant", "content": state["draft"]},
            {
                "role": "user",
                "content": "Crítica: "
                + " ".join(state["critique"])
                + " Reescribe el resumen corrigiendo todo.",
            },
        ]
        draft = (await ctx.llm.chat(messages, agent="summary_agent.revise")).strip()
        return {
            "draft": draft,
            "rounds": state.get("rounds", 0) + 1,
            "messages": messages,
        }

    @staticmethod
    def _finalize(state: SummaryState) -> SummaryState:
        if state["critique"]:
            return {
                "draft": template_summary(state["facts"]),
                "accepted": False,
                "fallback": True,
            }
        return {"accepted": True, "fallback": False}

    async def run(self, department: str, ctx: RunContext) -> dict:
        """Resume un área con el ciclo borrador, crítica y corrección.

        :param department: Nombre oficial del departamento
        :type department: str
        :param ctx: Contexto de la corrida
        :type ctx: RunContext
        :return: Resumen final, hechos, vueltas de reflexión y críticas
        :rtype: dict
        """
        config = {
            "configurable": {"ctx": ctx},
            "recursion_limit": 4 * self._max_rounds + 10,
            "run_name": "summary_agent",
            "metadata": {"request_id": ctx.request_id, "agent": "summary_agent"},
        }
        state = await self.graph.ainvoke({"department": department}, config=config)
        facts = {k: v for k, v in state["facts"].items() if k != "active_names"}
        return {
            "department": department,
            "answer": state["draft"],
            "facts": facts,
            "reflection_rounds": state.get("rounds", 0),
            "critiques": state.get("critiques", []),
            "accepted": state.get("accepted", False),
            "fallback": state.get("fallback", False),
        }
