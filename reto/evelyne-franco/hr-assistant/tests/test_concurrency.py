"""Prueba de concurrencia: 20 peticiones ``/ask`` al mismo tiempo.

Cubre el punto 9 de ``spec/05-security-hardening.md``. Veinte hilos,
sincronizados con una barrera para que las peticiones se traslapen,
mandan ``POST /ask`` con el modelo simulado: diez con la clave de
``tester`` y diez con la de ``other``. Cada pregunta trae un correo.

El limite es de 11 por minuto porque ``GET /metrics`` tambien gasta
cupo. Antes de las 20 no se hace ninguna peticion, porque ``requests``
de ``/metrics`` cuenta todas las rutas.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from tests.conftest import KEYS_BY_CLIENT, OTHER_CLIENT, TEST_CLIENT

PARALLEL_REQUESTS = 20
RATE_LIMIT = 11
TIMEOUT_SECONDS = 30


def test_twenty_simultaneous_questions_are_all_answered_and_counted(build_harness):
    """Las 20 responden 200, con ids distintos, y el limite cuenta bien."""
    harness = build_harness(rate_limit=RATE_LIMIT, tick_seconds=0.01)
    barrier = threading.Barrier(PARALLEL_REQUESTS, timeout=TIMEOUT_SECONDS)
    clients = [TEST_CLIENT, OTHER_CLIENT] * (PARALLEL_REQUESTS // 2)

    def ask(index):
        # Cada hilo usa su propio TestClient sobre la misma aplicacion.
        http = TestClient(harness.app, raise_server_exceptions=False)
        # Spec 06: la mitad va a ``directory`` y la otra mitad a ``policy``.
        if index < PARALLEL_REQUESTS // 2:
            question = f"Escribe a persona{index}@empresa.com, ¿quién es EMP-0001?"
        else:
            question = (
                f"Escribe a persona{index}@empresa.com, "
                "¿cuántos días de vacaciones tengo?"
            )
        headers = {"X-API-Key": KEYS_BY_CLIENT[clients[index]]}
        barrier.wait()
        return http.post("/ask", json={"question": question}, headers=headers)

    with ThreadPoolExecutor(max_workers=PARALLEL_REQUESTS) as pool:
        futures = [pool.submit(ask, i) for i in range(PARALLEL_REQUESTS)]
        responses = [f.result(timeout=TIMEOUT_SECONDS) for f in futures]

    # 1. Todas responden 200.
    assert [r.status_code for r in responses] == [200] * PARALLEL_REQUESTS

    # 2. Cada una tiene un request_id distinto, en el cuerpo y en el encabezado.
    body_ids = {r.json()["request_id"] for r in responses}
    header_ids = {r.headers["X-Request-ID"] for r in responses}
    assert len(body_ids) == PARALLEL_REQUESTS
    assert body_ids == header_ids

    # 3. /metrics (peticion 11 de tester) cuenta exactamente las 20.
    metrics = harness.anonymous.get(
        "/metrics", headers={"X-API-Key": KEYS_BY_CLIENT[TEST_CLIENT]}
    )
    assert metrics.status_code == 200
    assert metrics.json()["requests"] == PARALLEL_REQUESTS
    assert metrics.json()["security"]["pii"] == PARALLEL_REQUESTS
    half = PARALLEL_REQUESTS // 2
    assert metrics.json()["specialists"] == {"directory": half, "policy": half}
    assert all(
        r.json()["specialist"] == ("directory" if i < half else "policy")
        for i, r in enumerate(responses)
    )

    # 4. tester ya gasto sus 11: la peticion 12 se rechaza.
    question = {"question": "¿Quién es EMP-0001?"}
    assert harness.post_as(TEST_CLIENT, "/ask", json=question).status_code == 429

    # 5. other conto aparte: su peticion 11 pasa y la 12 se rechaza.
    assert harness.post_as(OTHER_CLIENT, "/ask", json=question).status_code == 200
    assert harness.post_as(OTHER_CLIENT, "/ask", json=question).status_code == 429
