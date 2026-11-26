"""Supervisor sobre LangGraph: reparte cada pregunta al especialista que toca.

El supervisor no responde nada: una regla en código elige entre el agente del
directorio (ReAct), el de vacaciones (ReAct) y el de resúmenes (reflexión).
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.base import AgentResult
from app.agents.react import ReactAgent
from app.agents.summary import SummaryAgent
from app.directory import Directory, NotFoundError, normalize
from app.llm import Usage

SUMMARY_WORDS = ("resume", "resumen", "resumir")
VACATION_WORDS = ("vacacion",)


class SupervisorState(TypedDict, total=False):
    """Estado del grafo del supervisor."""

    question: str
    history: list[dict]
    model: str
    specialist: str
    result: AgentResult


class Supervisor:
    """Supervisor con tres especialistas."""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, directory: Directory, directory_agent: ReactAgent,
        vacation_agent: ReactAgent, summary_agent: SummaryAgent, logger,
    ):
        self._directory = directory
        self._agents = {
            "directory_agent": directory_agent,
            "vacation_agent": vacation_agent,
        }
        self._summary = summary_agent
        self._logger = logger
        self._graph = self._build()

    def pick(self, question: str) -> str:
        """Elige al especialista con una regla en código.

        :param question: Pregunta de la persona
        :type question: str
        :return: Nombre del agente que la atiende
        :rtype: str
        """
        plain = normalize(question)
        if any(word in plain for word in VACATION_WORDS):
            return "vacation_agent"
        asks_summary = any(word in plain for word in SUMMARY_WORDS)
        if asks_summary and self._directory.find_department(question):
            return "summary_agent"
        return "directory_agent"

    def _build(self):
        def supervise(state: SupervisorState) -> dict:
            specialist = self.pick(state["question"])
            self._logger.audit("delegate", agent="supervisor", to=specialist)
            return {"specialist": specialist}

        def react(name: str):
            def node(state: SupervisorState) -> dict:
                agent = self._agents[name]
                result = agent.run(state["question"], state["history"], state["model"])
                return {"result": result}

            return node

        def summarize(state: SupervisorState) -> dict:
            department = self._directory.find_department(state["question"])
            try:
                result = self._summary.run(department, state["model"])
            except NotFoundError as error:
                result = AgentResult(
                    self._summary.name, str(error), state["model"], Usage()
                )
            return {"result": result}

        graph = StateGraph(SupervisorState)
        graph.add_node("supervisor", supervise)
        graph.add_node("directory_agent", react("directory_agent"))
        graph.add_node("vacation_agent", react("vacation_agent"))
        graph.add_node("summary_agent", summarize)
        graph.add_edge(START, "supervisor")
        names = ("directory_agent", "vacation_agent", "summary_agent")
        graph.add_conditional_edges(
            "supervisor", lambda state: state["specialist"],
            {name: name for name in names},
        )
        for name in names:
            graph.add_edge(name, END)
        return graph.compile()

    def mermaid(self) -> str:
        """Diagrama del grafo en Mermaid.

        :return: Texto Mermaid que genera LangGraph
        :rtype: str
        """
        return self._graph.get_graph().draw_mermaid()

    def run(
        self, question: str, history: list[dict], model: str, metadata: dict
    ) -> AgentResult:
        """Atiende una pregunta con el especialista que corresponde.

        :param question: Pregunta ya revisada por la guarda de entrada
        :type question: str
        :param history: Mensajes anteriores, ya recortados
        :type history: list[dict]
        :param model: Modelo elegido por el enrutador
        :type model: str
        :param metadata: Datos para la traza (``request_id``, cliente, canal)
        :type metadata: dict
        :return: Resultado del especialista
        :rtype: AgentResult
        """
        state = self._graph.invoke(
            {"question": question, "history": history, "model": model},
            {"run_name": "hr_supervisor", "metadata": metadata,
             "tags": [metadata.get("channel", "-")]},
        )
        return state["result"]
