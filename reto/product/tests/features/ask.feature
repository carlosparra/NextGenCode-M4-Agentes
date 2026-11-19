Feature: Ask the HR assistant about employees
  As a member of the HR staff
  I want to ask questions about employees
  So that I get answers from the employee directory

  Scenario: Asking for an existing employee returns their data
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the answer mentions "Jorge Díaz"
    And the tools used are "get_employee"
    And the agent took 2 steps
    And the response reports the token usage

  Scenario: Asking for an unknown employee says it does not exist
    When I ask "¿Quién es EMP-0099?"
    Then the response status is 200
    And the answer mentions "EMP-0099"
    And the answer does not mention "Jorge Díaz"
    And the tools used are "get_employee"

  Scenario: Asking for a department lists its employees
    When I ask "¿Quiénes trabajan en Tecnología?"
    Then the response status is 200
    And the answer mentions "Ana López"
    And the answer mentions "Marta Ruiz"
    And the answer mentions "Jorge Díaz"
    And the tools used are "search_by_department"

  Scenario: A question without employee or department gets the help message
    When I ask "¿Qué tiempo hace hoy?"
    Then the response status is 200
    And the answer is "Pregúntame por un empleado (EMP-0001) o un departamento."
    And no tools were used
    And the agent took 1 steps

  Scenario: The step cap stops a model that never answers
    Given a model that always asks for a tool and a cap of 2 steps
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the answer is "No pude completar la respuesta. Intenta con una pregunta más concreta."
    And the agent took 2 steps

  Scenario: An empty question is rejected
    When I ask "   "
    Then the response status is 422

  Scenario: A question longer than the limit is rejected
    When I ask a question of 2001 characters
    Then the response status is 422

  Scenario: A history entry with an invalid role is rejected
    When I ask "¿Quién es EMP-0004?" with a history entry from role "system"
    Then the response status is 422
