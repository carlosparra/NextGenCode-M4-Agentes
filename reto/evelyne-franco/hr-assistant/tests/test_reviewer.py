"""Pruebas del revisor: comprobacion contra los datos (spec 06, punto 4).

- ``directory``: un id ``EMP-dddd`` que no existe y que la persona no
  escribio reemplaza la respuesta por un mensaje fijo.
- ``policy``: cada numero completo de la respuesta debe estar en una
  politica consultada; si no, se responde con esa politica o, si no se
  consulto ninguna, con un mensaje fijo.
- Cada reemplazo deja ``security`` con ``stage=output`` y
  ``control=ungrounded``, nunca con el valor.
"""

from tests.conftest import (
    DIRECTORY_UNVERIFIED,
    POLICY_UNVERIFIED,
    VACATION_TEXT,
    SpyModel,
)
from tests.sample_data import INACTIVE_NOTE, JORGE_RESULT


def _ask(harness, question):
    """Hace una pregunta y devuelve el cuerpo, exigiendo 200.

    :param harness: Arnes de la aplicacion.
    :type harness: tests.conftest.Harness
    :param question: Texto de la pregunta.
    :type question: str
    :return: Cuerpo JSON de la respuesta.
    :rtype: dict
    """
    response = harness.client.post("/ask", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


def _ungrounded_events(harness):
    """Devuelve los eventos ``security`` con ``control=ungrounded``.

    :param harness: Arnes de la aplicacion.
    :type harness: tests.conftest.Harness
    :return: Eventos encontrados.
    :rtype: list[dict]
    """
    return [e for e in harness.events("security") if e["control"] == "ungrounded"]


def test_an_invented_employee_id_is_replaced(build_harness):
    """``EMP-0099`` no existe ni lo escribio la persona: se reemplaza."""
    spy = SpyModel(replies=[{"answer": "Su jefe es EMP-0099."}])
    harness = build_harness(model=spy)

    body = _ask(harness, "¿Quién es EMP-0001?")

    assert body["answer"] == DIRECTORY_UNVERIFIED
    events = _ungrounded_events(harness)
    assert len(events) == 1
    assert events[0]["stage"] == "output"
    assert events[0]["kinds"] == ["employee_id"]
    assert "EMP-0099" not in harness.log_text()


def test_an_unknown_id_written_by_the_person_is_kept(build_harness):
    """La respuesta puede decir que el id que escribio la persona no existe."""
    spy = SpyModel(replies=[{"answer": "EMP-0099 no existe en el directorio."}])
    harness = build_harness(model=spy)

    body = _ask(harness, "¿Quién es EMP-0099?")

    assert body["answer"] == "EMP-0099 no existe en el directorio."
    assert _ungrounded_events(harness) == []


def test_policy_numbers_are_compared_as_whole_numbers():
    """Los numeros de la politica pasan; ``5`` no cuenta dentro de ``15``."""
    # Importacion local: el modulo es nuevo en la spec 06.
    from app.reviewer import (  # pylint: disable=import-outside-toplevel
        ungrounded_numbers,
    )

    assert not ungrounded_numbers(
        "Son 12 días hábiles y se piden con 15 días.", [VACATION_TEXT]
    )
    assert ungrounded_numbers("Son 9 días.", ["Aviso con 15 días."])
    assert ungrounded_numbers("Son 30 días.", [VACATION_TEXT])


def test_a_policy_answer_without_a_consulted_policy_gets_the_fixed_message(
    build_harness,
):
    """El supervisor manda a ``policy`` por modelo y no se consulta nada."""
    spy = SpyModel(
        supervisor_reply='{"specialist": "policy"}',
        replies=[{"answer": "Te tocan 30 días."}],
    )
    harness = build_harness(model=spy)

    body = _ask(harness, "Hola, ¿qué me toca este año?")

    assert body["specialist"] == "policy"
    assert body["supervisor_route"] == "model"
    assert body["answer"] == POLICY_UNVERIFIED
    assert [e["kinds"] for e in _ungrounded_events(harness)] == [["policy_number"]]


class _ListAudit:  # pylint: disable=too-few-public-methods
    """Auditoria en memoria para probar el revisor sin la API."""

    def __init__(self):
        """Inicializa la lista de registros."""
        self.records = []

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def record(self, request_id, client, stage, control, kinds):
        """Guarda la deteccion sin valor.

        :param request_id: Id de la peticion.
        :type request_id: str
        :param client: Cliente.
        :type client: str
        :param stage: ``input`` u ``output``.
        :type stage: str
        :param control: Control que detecto algo.
        :type control: str
        :param kinds: Tipos detectados.
        :type kinds: list[str]
        """
        del request_id, client
        self.records.append((stage, control, list(kinds)))


# Adenda 1: resultados de ``vacation_days`` con el reloj en 2026-11-19
# (``JORGE_RESULT`` viene de ``tests.sample_data``).
MARTA_RESULT = {
    "employee_id": "EMP-0003",
    "name": "Marta Ruiz",
    "start_date": "2016-11-02",
    "status": "baja",
    "years_of_service": 10,
    "days": 0,
    "note": INACTIVE_NOTE,
}


def _review_policy(answer, vacation_results):
    """Revisa una respuesta de ``policy`` con la politica de vacaciones.

    :param answer: Respuesta del especialista.
    :type answer: str
    :param vacation_results: Resultados de ``vacation_days``.
    :type vacation_results: list[dict]
    :return: Revision y auditoria usada.
    :rtype: tuple[app.reviewer.Review, _ListAudit]
    """
    # Importacion local: ``vacation_results`` es nuevo en la Adenda 1.
    from app.reviewer import (  # pylint: disable=import-outside-toplevel
        Reviewer,
        ReviewInput,
    )

    audit = _ListAudit()
    reviewer = Reviewer(["EMP-0003", "EMP-0004"], audit, [], 2000)
    review = reviewer.review(
        ReviewInput(
            answer=answer,
            question="¿Cuántos días de vacaciones tiene EMP-0004?",
            specialist="policy",
            policy_texts=[VACATION_TEXT],
            vacation_results=vacation_results,
        )
    )
    return review, audit


def test_numbers_from_vacation_days_are_allowed_in_a_policy_answer():
    """A5: dias, años, fecha de ingreso e id (``0004`` y ``4``) pasan."""
    answer = (
        "Jorge Diaz (EMP-0004, empleado 4) ingresó el 2022-01-10, lleva 4 "
        "años y le corresponden 18 días hábiles."
    )

    review, audit = _review_policy(answer, [JORGE_RESULT])

    assert review.text == answer
    assert review.replaced is False
    assert not audit.records


def test_an_invented_number_is_replaced_by_the_vacation_sentence_with_its_note():
    """A5: «Le tocan 40 días.» se cambia por la frase armada en codigo."""
    review, audit = _review_policy("Le tocan 40 días.", [MARTA_RESULT])

    assert "40" not in review.text
    assert review.text.startswith(
        "Marta Ruiz (EMP-0003) tiene 10 años de servicio y le corresponden 0 "
        "días hábiles de vacaciones."
    )
    assert review.text.endswith(INACTIVE_NOTE)
    assert review.replaced is True
    assert audit.records == [("output", "ungrounded", ["policy_number"])]


def test_an_unknown_id_written_another_way_counts_as_written_by_the_person(
    build_harness,
):
    """A1: «empleado 99» llega como ``EMP-0099`` y no se reemplaza."""
    spy = SpyModel(replies=[{"answer": "EMP-0099 no existe en el directorio."}])
    harness = build_harness(model=spy)

    body = _ask(harness, "¿Quién es el empleado 99?")

    assert body["specialist"] == "directory"
    assert body["answer"] == "EMP-0099 no existe en el directorio."
    assert _ungrounded_events(harness) == []


def test_a_directory_answer_is_not_compared_against_policies(build_harness):
    """Un numero en una respuesta de ``directory`` no se revisa contra politicas."""
    answer = "Ana Lopez lleva 30 días en el proyecto."
    spy = SpyModel(replies=[{"answer": answer}])
    harness = build_harness(model=spy)

    body = _ask(harness, "¿Quién es EMP-0001?")

    assert body["specialist"] == "directory"
    assert body["answer"] == answer
    assert _ungrounded_events(harness) == []
