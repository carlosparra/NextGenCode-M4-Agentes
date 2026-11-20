"""Contrato de la spec 06: supervisor, especialistas y revisor en cada petición."""

AGENTS_DIRECTORY = ["guard", "supervisor", "directory", "reviewer"]
AGENTS_POLICY = ["guard", "supervisor", "policy", "reviewer"]


def ask(api, question):
    response = api.post("/ask", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


def test_an_employee_id_goes_to_directory_by_rule(api):
    body = ask(api, "¿Quién es EMP-0004?")
    assert body["specialist"] == "directory"
    assert body["supervisor_route"] == "rule:employee"
    assert body["agents"] == AGENTS_DIRECTORY
    assert "Jorge Díaz" in body["answer"]


def test_a_department_goes_to_directory_by_rule(api):
    body = ask(api, "¿Quiénes trabajan en finanzas?")
    assert body["specialist"] == "directory"
    assert body["supervisor_route"] == "rule:department"


def test_a_policy_question_goes_to_policy_and_quotes_it(api):
    body = ask(api, "¿Cuántos días de VACACIONES tengo el primer año?")
    assert body["specialist"] == "policy"
    assert body["supervisor_route"] == "rule:policy"
    assert body["agents"] == AGENTS_POLICY
    assert "12 días hábiles" in body["answer"]
    assert "search_policy" in body["tools_used"]


def test_a_question_without_rules_asks_the_supervisor_model(api):
    body = ask(api, "¿Qué clima hace hoy en Monterrey?")
    assert body["supervisor_route"] in {"model", "model_invalid"}
    assert body["specialist"] in {"directory", "policy"}
    assert body["input_tokens"] > 0


def test_personal_data_never_reaches_the_policy_answer(api):
    body = ask(api, "Soy ana@empresa.com, ¿cuántos días de vacaciones tengo?")
    assert body["specialist"] == "policy"
    assert "ana@empresa.com" not in body["answer"]
    assert "email" in body["redactions"]


def test_metrics_count_specialists_and_supervisor_routes(api):
    ask(api, "¿Quién es EMP-0001?")
    ask(api, "¿Cuál es la política de home office?")
    snapshot = api.get("/metrics").json()
    assert snapshot["specialists"]["directory"] >= 1
    assert snapshot["specialists"]["policy"] >= 1
    assert snapshot["supervisor"]["rule:employee"] >= 1
    assert snapshot["supervisor"]["rule:policy"] >= 1
    # Las llaves de las sesiones anteriores siguen ahí
    for key in ("requests", "error_rate", "latency_ms", "tokens", "cost_usd", "security"):
        assert key in snapshot


# -- Adenda 1: vacaciones por empleado ------------------------------------------

def expected_vacation_days(start, today):
    """Días de la política de vacaciones para ``start`` (regla de la adenda 1, A3)."""
    years = today.year - start.year - ((today.month, today.day) < (start.month, start.day))
    if years < 1:
        return years, 0
    if years <= 5:
        return years, 12 + 2 * (years - 1)
    return years, 20 + 2 * ((years - 1) // 5)


def test_vacation_rule_matches_the_policy_table():
    from datetime import date

    table = {1: 12, 2: 14, 3: 16, 4: 18, 5: 20, 6: 22, 10: 22, 11: 24, 15: 24, 16: 26}
    for years, days in table.items():
        assert expected_vacation_days(date(2000, 1, 1), date(2000 + years, 1, 1)) == (years, days)


def test_vacation_days_of_an_employee_written_another_way(api):
    from datetime import date

    years, days = expected_vacation_days(date(2022, 1, 10), date.today())
    body = ask(api, "¿Cuántos días de vacaciones tiene el empleado 004?")
    assert body["specialist"] == "policy"
    assert body["supervisor_route"] == "rule:policy_employee"
    assert {"search_policy", "vacation_days"} <= set(body["tools_used"])
    assert "Jorge Díaz" in body["answer"]
    assert f"{days} días" in body["answer"]
    assert str(years) in body["answer"]


def test_an_inactive_employee_has_no_vacation_days(api):
    body = ask(api, "¿Cuántos días de vacaciones tiene EMP-0003?")
    assert body["specialist"] == "policy"
    assert "no está activo" in body["answer"]


def test_vacations_without_an_employee_give_the_rule(api):
    body = ask(api, "¿Cuántos días de vacaciones tengo?")
    assert body["supervisor_route"] == "rule:policy"
    assert "12 días hábiles" in body["answer"]


def test_an_employee_written_another_way_still_goes_to_directory(api):
    body = ask(api, "¿Quién es el empleado 4?")
    assert body["specialist"] == "directory"
    assert body["supervisor_route"] == "rule:employee"
    assert "Jorge Díaz" in body["answer"]


def test_a_bare_year_is_not_an_employee_id(api):
    body = ask(api, "¿Quiénes entraron en 2021?")
    assert body["supervisor_route"] != "rule:employee"
