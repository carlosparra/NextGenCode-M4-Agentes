"""Agente de reflexión sobre LangGraph: resume un departamento y se corrige.

Flujo: ``gather_facts`` (código) -> ``draft`` (modelo) -> ``critique`` (código)
-> ``revise`` (modelo, con tope) -> ``finalize``. El crítico es un programa: el
modelo redacta, pero las cifras y los nombres los decide el código.
"""

import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app import pii
from app.agents.base import AgentResult
from app.directory import Directory, NotFoundError
from app.llm import (DRAFT_PREFIX, FACTS_END, FACTS_START, REVISE_PREFIX,
                     ModelCaller, Usage)
from app.vacations import years_of_service

MAX_REVISIONS = 2
SYSTEM = (
    "Eres analista de Recursos Humanos. Redactas resúmenes breves en español usando "
    "solo los hechos que recibes. No agregues cifras, nombres ni datos personales."
)
NUMBER = re.compile(r"\d+(?:\.\d+)?")


class SummaryState(TypedDict, total=False):
    """Estado que viaja por el grafo de reflexión."""

    department: str
    facts: list[str]
    names: list[str]
    draft: str
    problems: list[str]
    revisions: int
    reasoning: list[str]
    answer: str
    verified: bool


def department_facts(directory: Directory, department: str, today) -> dict:
    """Hechos de un departamento, calculados en código.

    :param directory: Directorio de empleados
    :type directory: Directory
    :param department: Nombre del departamento
    :type department: str
    :param today: Fecha de consulta, para la antigüedad
    :type today: datetime.date
    :return: ``department``, ``lines`` (los hechos) y ``names`` (activos)
    :rtype: dict
    :raises NotFoundError: Si el departamento no existe
    """
    people = directory.by_department(department)
    active = [person for person in people if person.active]
    seniority = [years_of_service(person.start_date, today) for person in active]
    average = round(sum(seniority) / len(seniority), 1) if seniority else 0
    roster = "; ".join(f"{person.name} ({person.role})" for person in active)
    official = people[0].department
    return {
        "department": official,
        "names": [person.name for person in active],
        "lines": [
            f"El departamento de {official} tiene {len(active)} personas activas "
            f"y {len(people) - len(active)} de baja.",
            f"Personas activas: {roster or 'ninguna'}.",
            f"Antigüedad promedio de las personas activas: {average} años.",
        ],
    }


def critique(draft: str, facts: list[str], names: list[str]) -> list[str]:
    """Crítico en código: qué le falta o le sobra al borrador.

    :param draft: Borrador del modelo
    :type draft: str
    :param facts: Hechos verificados
    :type facts: list[str]
    :param names: Personas que el resumen debe mencionar
    :type names: list[str]
    :return: Un texto por problema; vacía si el borrador pasa
    :rtype: list[str]
    """
    problems = [f"falta mencionar a {name}" for name in names if name not in draft]
    allowed = set(NUMBER.findall(" ".join(facts)))
    extra = sorted(set(NUMBER.findall(draft)) - allowed)
    if extra:
        problems.append(f"cifras que no están en los hechos: {', '.join(extra)}")
    if not set(NUMBER.findall(draft)) & allowed:
        problems.append("falta el número de personas activas")
    if pii.scan(draft):
        problems.append("contiene datos personales")
    return problems


class SummaryAgent:
    """Agente que resume un departamento con un ciclo de reflexión acotado."""

    name = "summary_agent"

    def __init__(self, directory: Directory, caller: ModelCaller, clock, logger):
        self._directory = directory
        self._caller = caller
        self._clock = clock
        self._logger = logger

    def _build(self, model: str, usage: Usage):
        def facts_block(state: SummaryState) -> str:
            lines = "\n".join(f"- {line}" for line in state["facts"])
            return f"{FACTS_START}\n{lines}\n{FACTS_END}"

        def gather_facts(state: SummaryState) -> dict:
            self._logger.audit(
                "tool_call", agent=self.name, tool="department_facts",
                args={"department": state["department"]},
            )
            facts = department_facts(
                self._directory, state["department"], self._clock.now().date()
            )
            return {"facts": facts["lines"], "names": facts["names"],
                    "department": facts["department"]}

        def draft(state: SummaryState) -> dict:
            prompt = (
                f"{DRAFT_PREFIX} un resumen de máximo cuatro frases del departamento "
                f"de {state['department']}.\n{facts_block(state)}"
            )
            text = self._caller.call(
                [{"role": "system", "content": SYSTEM},
                 {"role": "user", "content": prompt}], model, usage,
            )
            return {"draft": text.strip()}

        def critique_node(state: SummaryState) -> dict:
            problems = critique(state["draft"], state["facts"], state["names"])
            verdict = "; ".join(problems) if problems else "sin observaciones"
            return {"problems": problems,
                    "reasoning": state["reasoning"] + [f"Crítica: {verdict}."]}

        def revise(state: SummaryState) -> dict:
            prompt = (
                f"{REVISE_PREFIX} el borrador. Problemas: "
                f"{'; '.join(state['problems'])}.\nBorrador: {state['draft']}\n"
                f"{facts_block(state)}"
            )
            text = self._caller.call(
                [{"role": "system", "content": SYSTEM},
                 {"role": "user", "content": prompt}], model, usage,
            )
            return {"draft": text.strip(), "revisions": state["revisions"] + 1}

        def finalize(state: SummaryState) -> dict:
            if not state["problems"]:
                return {"answer": state["draft"], "verified": True}
            self._logger.audit("summary_fallback", agent=self.name)
            note = "El borrador no pasó la crítica: se entregan los hechos verificados."
            return {"answer": " ".join(state["facts"]), "verified": False,
                    "reasoning": state["reasoning"] + [note]}

        def after_critique(state: SummaryState) -> str:
            if state["problems"] and state["revisions"] < MAX_REVISIONS:
                return "revise"
            return "finalize"

        graph = StateGraph(SummaryState)
        graph.add_node("gather_facts", gather_facts)
        graph.add_node("draft", draft)
        graph.add_node("critique", critique_node)
        graph.add_node("revise", revise)
        graph.add_node("finalize", finalize)
        graph.add_edge(START, "gather_facts")
        graph.add_edge("gather_facts", "draft")
        graph.add_edge("draft", "critique")
        graph.add_conditional_edges(
            "critique", after_critique, {"revise": "revise", "finalize": "finalize"}
        )
        graph.add_edge("revise", "critique")
        graph.add_edge("finalize", END)
        return graph.compile()

    def mermaid(self) -> str:
        """Diagrama del grafo en Mermaid.

        :return: Texto Mermaid que genera LangGraph
        :rtype: str
        """
        return self._build("", Usage()).get_graph().draw_mermaid()

    def run(self, department: str, model: str) -> AgentResult:
        """Resume un departamento.

        :param department: Nombre del departamento
        :type department: str
        :param model: Modelo elegido por el enrutador
        :type model: str
        :return: Resumen verificado, con la crítica en ``reasoning``
        :rtype: AgentResult
        :raises NotFoundError: Si el departamento no existe
        """
        if self._directory.find_department(department) is None:
            raise NotFoundError(
                f"No existe el departamento {department}. Departamentos: "
                f"{', '.join(self._directory.departments())}."
            )
        usage = Usage()
        state = self._build(model, usage).invoke(
            {"department": department, "revisions": 0, "reasoning": []},
            {"recursion_limit": 6 + 2 * MAX_REVISIONS, "run_name": self.name},
        )
        reasoning = state["reasoning"] + [f"Revisiones: {state['revisions']}."]
        return AgentResult(
            self.name, state["answer"], model, usage, ["department_facts"], reasoning
        )
