"""Pruebas unitarias de la aplicación web y de la página."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app

PAGE = Path(__file__).resolve().parent.parent / "app" / "static" / "index.html"


class BrokenModel:
    """Modelo que siempre falla con un detalle interno que no debe filtrarse."""

    def complete(self, messages):
        """Lanza siempre un error.

        :param messages: Conversación recibida
        :type messages: list[dict]
        :raises RuntimeError: Siempre
        """
        raise RuntimeError("secret internal detail")


def test_internal_error_returns_500_without_details(directory, api_key):
    settings = load_settings({"API_KEYS": f"qa-tester:{api_key}"})
    app = create_app(settings=settings, model=BrokenModel(), directory=directory)
    client = TestClient(
        app, raise_server_exceptions=False, headers={"X-API-Key": api_key}
    )

    response = client.post("/ask", json={"question": "¿Quién es EMP-0004?"})

    assert response.status_code == 500
    assert "secret internal detail" not in response.text


def test_page_never_paints_with_inner_html():
    page = PAGE.read_text(encoding="utf-8")

    assert "textContent" in page
    assert "innerHTML" not in page
