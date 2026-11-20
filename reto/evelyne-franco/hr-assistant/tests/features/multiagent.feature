Feature: Multi-agent answers
  Every question goes through guard, supervisor, one specialist and reviewer.
  The supervisor sends employee questions to the directory specialist and
  HR policy questions to the policy specialist.

  Scenario: A vacation question is answered by the policy specialist
    Given the HR assistant is running
    When I ask "¿Cuántos días de vacaciones tengo?"
    Then the response status is 200
    And the specialist is "policy" with supervisor route "rule:policy"
    And the agents are "guard, supervisor, policy, reviewer"
    And the answer mentions "12 días hábiles"
    And the policy was looked up in code with an audit event

  Scenario: A policy number that is not in the policy is replaced by the policy text
    Given the HR assistant is running with a policy specialist that answers "El aguinaldo es de 30 días de salario." without tools
    When I ask "¿De cuánto es el aguinaldo?"
    Then the response status is 200
    And the answer does not mention "30 días"
    And the answer mentions "15 días de salario"
    And there is an output security event "ungrounded" with kinds "policy_number"

  Scenario: An employee question still goes to the directory specialist
    Given the HR assistant is running
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the specialist is "directory" with supervisor route "rule:employee"
    And the agents are "guard, supervisor, directory, reviewer"
    And the answer mentions "Jorge Diaz"

  Scenario: Metrics count specialists and supervisor routes
    Given the HR assistant is running
    When I ask "¿Quién es EMP-0004?"
    And I ask "¿Cuántos días de vacaciones tengo?"
    Then the metrics count 1 answer from "directory" and 1 from "policy"
    And the metrics count 1 supervisor route "rule:employee" and 1 "rule:policy"
    And the metrics keep the keys "requests, error_rate, latency_ms, tokens, cost_usd, slo, security"

  # Adenda 1: vacaciones por empleado, con el reloj fijo en 2026-11-19.

  Scenario: Vacation days of an employee written another way are computed in code
    Given the HR assistant is running on "2026-11-19"
    When I ask "¿Cuántos días de vacaciones tiene el empleado 004?"
    Then the response status is 200
    And the specialist is "policy" with supervisor route "rule:policy_employee"
    And the tools used are "search_policy, vacation_days"
    And the answer mentions "Jorge Diaz"
    And the answer mentions "18 días"

  Scenario: An inactive employee gets no vacation days
    Given the HR assistant is running on "2026-11-19"
    When I ask "¿Cuántos días de vacaciones tiene EMP-0003?"
    Then the response status is 200
    And the specialist is "policy" with supervisor route "rule:policy_employee"
    And the answer mentions "no está activo"

  Scenario: A vacation question without an employee id gets the whole rule
    Given the HR assistant is running on "2026-11-19"
    When I ask "¿Cuántos días de vacaciones tengo?"
    Then the response status is 200
    And the specialist is "policy" with supervisor route "rule:policy"
    And the tools used are "search_policy"
    And the answer mentions "12 días hábiles"

  Scenario: An invented number of vacation days is replaced by the computed sentence
    Given the HR assistant is running on "2026-11-19" with a policy specialist that answers "Le tocan 40 días."
    When I ask "¿Cuántos días de vacaciones tiene el empleado 004?"
    Then the response status is 200
    And the answer does not mention "40"
    And the answer is "Jorge Diaz (EMP-0004) tiene 4 años de servicio y le corresponden 18 días hábiles de vacaciones."
    And there is an output security event "ungrounded" with kinds "policy_number"

  Scenario: A question about an employee written another way still goes to the directory
    Given the HR assistant is running on "2026-11-19"
    When I ask "¿Quién es el empleado 4?"
    Then the response status is 200
    And the specialist is "directory" with supervisor route "rule:employee"
    And the answer mentions "Jorge Diaz"
