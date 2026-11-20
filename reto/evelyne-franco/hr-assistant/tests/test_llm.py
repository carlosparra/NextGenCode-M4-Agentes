"""Pruebas unitarias del modelo simulado (fake LLM).

Verifica las cuatro reglas del modelo simulado y, desde la sesion 3,
que ``complete`` devuelve un ``Completion`` con sus propios tokens y
que ``build_models`` crea un modelo por cada nombre configurado.
"""

import json

import pytest

from app.config import Settings
from app.llm import Completion, FakeModel, build_models


@pytest.fixture()
def fake_model():
    """Crea una instancia del modelo simulado.

    :return: Instancia del modelo fake.
    :rtype: app.llm.FakeModel
    """
    return FakeModel()


def _decision(model, content):
    """Llama al modelo con un solo mensaje y parsea su texto.

    :param model: Modelo simulado.
    :type model: app.llm.FakeModel
    :param content: Contenido del mensaje del usuario.
    :type content: str
    :return: Decision del modelo como diccionario.
    :rtype: dict
    """
    completion = model.complete([{"role": "user", "content": content}])
    return json.loads(completion.text)


class TestFakeModelRules:
    """Reglas deterministicas del modelo simulado."""

    def test_tool_result_produces_answer(self, fake_model):
        """Regla 1: un mensaje que empieza con
        'Resultado de la herramienta:' genera una respuesta.
        """
        parsed = _decision(
            fake_model,
            'Resultado de la herramienta: {"id": "EMP-0001", "name": "Ana"}',
        )
        assert "answer" in parsed

    def test_employee_id_triggers_get_employee(self, fake_model):
        """Regla 2: un mensaje con EMP-XXXX pide get_employee."""
        parsed = _decision(fake_model, "Tell me about EMP-0004")
        assert parsed["tool"] == "get_employee"
        assert "EMP-0004" in str(parsed["args"])

    def test_department_name_triggers_search(self, fake_model):
        """Regla 3: un mensaje con un departamento conocido
        pide search_by_department.
        """
        parsed = _decision(fake_model, "Employees in Tecnologia")
        assert parsed["tool"] == "search_by_department"

    def test_generic_message_returns_help(self, fake_model):
        """Regla 4: sin id ni departamento, responde con ayuda."""
        parsed = _decision(fake_model, "Hello there")
        assert "answer" in parsed


# -- Sesion 3: Completion y un modelo simulado por nombre --------------

def test_fake_model_returns_a_completion_with_its_own_tokens():
    """El modelo simulado devuelve un ``Completion`` con texto, tokens
    positivos y ``cached`` falso, y conserva el nombre que recibio.
    """
    model = FakeModel(name="@cf/meta/llama-3.1-8b-instruct-fast")

    completion = model.complete([{"role": "user", "content": "Who is EMP-0001?"}])

    assert isinstance(completion, Completion)
    assert model.name == "@cf/meta/llama-3.1-8b-instruct-fast"
    assert json.loads(completion.text)["tool"] == "get_employee"
    assert completion.input_tokens > 0
    assert completion.output_tokens > 0
    assert completion.cached is False


def test_build_models_creates_one_fake_model_per_configured_name(directory):
    """Con ``MODEL_PROVIDER=fake`` hay dos modelos simulados que se
    llaman como ``MODEL_SMALL`` y ``MODEL_LARGE`` y responden igual.
    """
    settings = Settings(model_small="small-model", model_large="large-model")

    models = build_models(settings, directory)

    assert set(models) == {"small-model", "large-model"}
    assert models["small-model"].name == "small-model"
    assert models["large-model"].name == "large-model"
    messages = [{"role": "user", "content": "Who is EMP-0001?"}]
    small = models["small-model"].complete(messages)
    large = models["large-model"].complete(messages)
    assert small.text == large.text
