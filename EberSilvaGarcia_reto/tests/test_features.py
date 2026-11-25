"""Escenarios Gherkin (pytest-bdd) del comportamiento visible del producto."""

from pytest_bdd import given, parsers, scenarios, then, when

from app.llm.fake import FakeModel
from tests.conftest import run

scenarios(
    "features/vacations.feature",
    "features/summary.feature",
    "features/data_protection.feature",
)


class SpyModel(FakeModel):
    """Modelo simulado que recuerda lo que vio."""

    def __init__(self, directory):
        super().__init__(directory)
        self.seen = []

    async def complete(self, messages, model, max_tokens):
        self.seen.extend(m["content"] for m in messages)
        return await super().complete(messages, model, max_tokens)


@given(
    "el asistente con el modelo simulado al 24 de noviembre de 2026",
    target_fixture="world",
)
def assistant(make_service):
    service = make_service()
    spy = SpyModel(service.s.directory)
    service = make_service(model=spy)
    return {"service": service, "spy": spy}


@when(parsers.parse('pregunto "{question}"'))
def ask(world, question):
    world["body"] = run(world["service"].ask(question, []))


@when(parsers.parse('pido el resumen del área "{department}"'))
def summary(world, department):
    world["body"] = run(world["service"].summary(department))


@then(parsers.parse('el agente usa la herramienta "{tool}"'))
def uses_tool(world, tool):
    assert world["body"]["tools_used"] == [tool]


@then(parsers.parse("el saldo calculado es de {days:d} días"))
def balance(world, days):
    assert world["body"]["details"]["vacation"]["balance_days"] == days


@then(parsers.parse("el subagente razonó en {steps:d} pasos"))
def reasoning(world, steps):
    assert len(world["body"]["details"]["vacation"]["reasoning"]) == steps


@then(parsers.parse('el resumen menciona "{text}"'))
def mentions(world, text):
    assert text in world["body"]["answer"]


@then(parsers.parse("hubo {rounds:d} vuelta de reflexión"))
def rounds(world, rounds):
    assert world["body"]["reflection_rounds"] == rounds


@then("el resumen final fue aceptado por el crítico")
def accepted(world):
    assert world["body"]["accepted"] and not world["body"]["fallback"]


@then("la respuesta explica que el dato está protegido")
def protected(world):
    assert "protección de datos personales" in world["body"]["answer"]


@then("no se llamó al modelo")
def no_model(world):
    assert world["body"]["model_calls"] == 0 and not world["spy"].seen


@then(parsers.parse('se detectó PII de tipo "{kind}"'))
def pii_kind(world, kind):
    assert kind in world["body"]["pii_detected"]


@then("el modelo nunca vio el teléfono")
def never_seen(world):
    assert world["spy"].seen and not any(
        "2281234567" in text for text in world["spy"].seen
    )
