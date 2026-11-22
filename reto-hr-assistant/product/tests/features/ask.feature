Feature: HR staff ask the assistant about employees
  The HR Assistant answers questions about employees through a stateless web API,
  using a single agent with read-only tools and a capped loop.

  Scenario: Asking for an employee by id uses get_employee
    Given the assistant is running with the default settings
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the answer mentions "Jorge Díaz"
    And the tools used are "get_employee"
    And the agent took 2 steps

  Scenario: Asking for an unknown employee says it does not exist
    Given the assistant is running with the default settings
    When I ask "¿Quién es EMP-9999?"
    Then the response status is 200
    And the answer mentions "EMP-9999"
    And the answer says the employee was not found

  Scenario: Asking for a department lists its people
    Given the assistant is running with the default settings
    When I ask "¿Quiénes trabajan en Finanzas?"
    Then the response status is 200
    And the answer mentions "Sofía Gómez"
    And the tools used are "search_by_department"

  Scenario: A question without an id or department gets the help answer
    Given the assistant is running with the default settings
    When I ask "¿Qué tal el clima?"
    Then the response status is 200
    And the answer is "Pregúntame por un empleado (EMP-0001) o un departamento."
    And no tools were used
    And the agent took 1 steps

  Scenario Outline: Invalid questions are rejected
    Given the assistant is running with the default settings
    When I send a question that is <kind>
    Then the response status is 422

    Examples:
      | kind     |
      | empty    |
      | blank    |
      | too long |

  Scenario: The step cap stops the loop with the fallback answer
    Given the assistant is running with AGENT_MAX_STEPS set to 1
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the answer is "No pude completar la respuesta. Intenta con una pregunta más concreta."
    And the agent took 1 steps

  Scenario: The history comes from the client and is not stored
    Given the assistant is running with the default settings
    When I ask "¿Quién es EMP-0004?" with a previous turn in the history
    And I ask "¿Qué tal el clima?"
    Then every response has status 200
    And the answer is "Pregúntame por un empleado (EMP-0001) o un departamento."
    And no tools were used

  Scenario: The service reports its health and serves the page
    Given the assistant is running with the default settings
    Then the health check reports ok with the process id
    And the home page has the question, send and answer elements
