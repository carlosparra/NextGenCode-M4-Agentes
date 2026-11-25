"""Modelo simulado: determinista, sin red y sin costo real.

Sigue reglas sobre el último mensaje según el agente que lo llama (lo indica
una marca en el mensaje de sistema). Sirve para pruebas, CI y para medir las
palancas de costo sin gastar cuota: el costo se calcula con el precio del
nombre del modelo que se le pide.
"""

from __future__ import annotations

import json
import re

from app.agents.protocol import TOOL_RESULT
from app.domain.directory import Directory, normalize
from app.llm.base import Completion

_EMPLOYEE_ID = re.compile(r"EMP-\d{4}", re.IGNORECASE)
_VACATION_WORDS = ("vacacion", "dias libres", "descanso")
_SUMMARY_WORDS = ("resumen", "resume", "resumir", "panorama", "como esta el area")
DEFAULT_ANSWER = "Pregúntame por un empleado (EMP-0001) o un departamento."


def _words(text: str) -> int:
    return len(text.split())


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _observations(messages: list[dict]) -> dict:
    """Junta los resultados de herramientas que ya están en la conversación."""
    seen: dict = {}
    for message in messages:
        content = message["content"]
        if message["role"] == "user" and content.startswith(TOOL_RESULT):
            try:
                payload = json.loads(content[len(TOOL_RESULT) :])
            except ValueError:
                continue
            if isinstance(payload, dict) and "tool" in payload:
                seen[payload["tool"]] = payload.get("result")
    return seen


class FakeModel:
    """Modelo de reglas para los tres agentes del producto.

    :param directory: Directorio, para reconocer departamentos en las preguntas
    :type directory: Directory
    """

    def __init__(self, directory: Directory) -> None:
        self._directory = directory

    async def complete(
        self, messages: list[dict], model: str, max_tokens: int
    ) -> Completion:
        """Responde con la regla que toca al agente que llama.

        :param messages: Conversación (el primero es el de sistema)
        :type messages: list[dict]
        :param model: Nombre del modelo pedido (define el precio)
        :type model: str
        :param max_tokens: Tope de salida (se respeta cortando palabras)
        :type max_tokens: int
        :return: Respuesta simulada
        :rtype: Completion
        """
        system = messages[0]["content"] if messages else ""
        if "[agent:vacation]" in system:
            text = self._vacation(messages)
        elif "[agent:summary]" in system:
            text = self._summary(messages)
        else:
            text = self._hr(messages[-1]["content"])
        words = text.split()
        if len(words) > max_tokens:
            text = " ".join(words[:max_tokens])
        tokens_in = sum(_words(m["content"]) for m in messages)
        return Completion(text, tokens_in, _words(text), model)

    def _hr(self, last: str) -> str:
        if last.startswith(TOOL_RESULT):
            payload = last[len(TOOL_RESULT) :]
            try:
                data = json.loads(payload)
                result = data.get("result", data) if isinstance(data, dict) else data
                if isinstance(result, dict) and "answer" in result:
                    payload = result["answer"]
                elif isinstance(result, str):
                    payload = result
                else:
                    payload = json.dumps(result, ensure_ascii=False)
            except ValueError:
                pass
            return _json({"answer": f"Según el directorio: {payload}"})
        flat = normalize(last)
        found = _EMPLOYEE_ID.search(last)
        department = self._directory.resolve_department(last)
        if found and any(word in flat for word in _VACATION_WORDS):
            return _json(
                {
                    "thought": (
                        "Piden vacaciones de un empleado: delego al agente de "
                        "vacaciones."
                    ),
                    "tool": "vacation_balance",
                    "args": {"employee_id": found.group(0).upper()},
                }
            )
        if department and any(word in flat for word in _SUMMARY_WORDS):
            return _json(
                {
                    "thought": (
                        "Piden un resumen de un área: delego al agente de " "resumen."
                    ),
                    "tool": "department_summary",
                    "args": {"department": department},
                }
            )
        if found:
            return _json(
                {
                    "thought": "Hay un id de empleado: lo busco.",
                    "tool": "get_employee",
                    "args": {"employee_id": found.group(0).upper()},
                }
            )
        if department:
            return _json(
                {
                    "thought": "Mencionan un departamento: listo a su gente.",
                    "tool": "search_by_department",
                    "args": {"department": department},
                }
            )
        return _json({"answer": DEFAULT_ANSWER})

    @staticmethod
    def _vacation(messages: list[dict]) -> str:
        seen = _observations(messages)
        question = messages[1]["content"] if len(messages) > 1 else ""
        found = _EMPLOYEE_ID.search(question)
        employee_id = found.group(0).upper() if found else "EMP-0000"
        if "get_employee" not in seen:
            return _json(
                {
                    "thought": (
                        "Primero confirmo que el empleado existe y sigue " "activo."
                    ),
                    "tool": "get_employee",
                    "args": {"employee_id": employee_id},
                }
            )
        employee = seen["get_employee"]
        if not isinstance(employee, dict) or employee.get("status") != "activo":
            return _json(
                {
                    "answer": "El empleado no existe o ya no está activo; "
                    "no tiene saldo de vacaciones."
                }
            )
        if "compute_entitlement" not in seen:
            return _json(
                {
                    "thought": (
                        "Calculo los días que le tocan por antigüedad (LFT " "art. 76)."
                    ),
                    "tool": "compute_entitlement",
                    "args": {"employee_id": employee_id},
                }
            )
        entitlement = seen["compute_entitlement"]
        if not entitlement.get("entitled_days"):
            return _json(
                {
                    "answer": f"{employee['name']} aún no cumple un año de "
                    "servicio: todavía no tiene días de vacaciones."
                }
            )
        if "get_taken_days" not in seen:
            return _json(
                {
                    "thought": "Reviso cuántos días ya tomó en el periodo vigente.",
                    "tool": "get_taken_days",
                    "args": {
                        "employee_id": employee_id,
                        "period_start": entitlement["period_start"],
                        "period_end": entitlement["period_end"],
                    },
                }
            )
        taken = seen["get_taken_days"]["taken_days"]
        entitled = entitlement["entitled_days"]
        return _json(
            {
                "answer": (
                    f"{employee['name']} tiene {entitlement['years_of_service']} "
                    "años de "
                    f"servicio, le corresponden {entitled} días, ha tomado {taken} y "
                    "le "
                    f"quedan {entitled - taken} días en el periodo vigente."
                )
            }
        )

    @staticmethod
    def _summary(messages: list[dict]) -> str:
        facts_text = messages[1]["content"] if len(messages) > 1 else "{}"
        facts = json.loads(facts_text[facts_text.find("{") :])
        roles = ", ".join(f"{name} ({count})" for name, count in facts["roles"].items())
        base = (
            f"El área de {facts['department']} tiene {facts['headcount']} personas: "
            f"{facts['active']} activas y {facts['inactive']} de baja. "
            f"Puestos activos: {roles or 'ninguno'}."
        )
        if "Crítica:" not in messages[-1]["content"]:
            # Primer borrador deliberadamente incompleto: ejercita la reflexión
            return base
        return (
            f"{base} La antigüedad promedio del personal activo es de "
            f"{facts['avg_tenure_years']} años."
        )
