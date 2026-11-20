Feature: Ask the HR assistant about employees
  HR staff ask questions in Spanish and the assistant answers
  using read-only tools over the employee directory.

  Scenario: Asking for an existing employee
    Given the HR assistant runs with the fake model
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the answer contains "Jorge Díaz"
    And the tools used are "get_employee"
    And the agent took 2 steps

  Scenario: Asking for an unknown employee
    Given the HR assistant runs with the fake model
    When I ask "¿Quién es EMP-9999?"
    Then the response status is 200
    And the answer contains "EMP-9999"
    And the answer contains "no existe"

  Scenario: Asking for a department lists its people
    Given the HR assistant runs with the fake model
    When I ask "¿Quiénes trabajan en Tecnología?"
    Then the response status is 200
    And the answer contains "Ana López"
    And the answer contains "Marta Ruiz"
    And the answer contains "Jorge Díaz"
    And the tools used are "search_by_department"

  Scenario: A question without employee or department gets help
    Given the HR assistant runs with the fake model
    When I ask "Hola, ¿cómo estás?"
    Then the answer is "Pregúntame por un empleado (EMP-0001) o un departamento."
    And the agent took 1 steps
    And no tools were used

  Scenario: An empty question is rejected
    Given the HR assistant runs with the fake model
    When I send an empty question
    Then the response status is 422

  Scenario: A question longer than the limit is rejected
    Given the HR assistant runs with the fake model
    When I send a question of 2001 characters
    Then the response status is 422

  Scenario: The agent stops when it reaches the step cap
    Given the HR assistant runs with a model that always asks for a tool and 2 steps
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the answer is "No pude completar la respuesta. Intenta con una pregunta más concreta."
    And the agent took 2 steps

  Scenario: The history sent by the client reaches the model
    Given the HR assistant runs with a model that records the conversation
    When I ask "¿Quién es EMP-0004?" after saying "Hola"
    Then the response status is 200
    And the model received "Hola" before "¿Quién es EMP-0004?"
