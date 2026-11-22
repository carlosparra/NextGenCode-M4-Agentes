Feature: HR Assistant answers questions about employees

  Scenario: Ask about an existing employee
    When I ask "Who is EMP-0004?"
    Then the response status is 200
    And the answer starts with "Según el directorio:"
    And the answer mentions "Jorge Diaz"
    And the tools used are "get_employee"

  Scenario: Ask about an unknown employee
    When I ask "Who is EMP-9999?"
    Then the response status is 200
    And the answer mentions "EMP-9999"
    And the answer does not mention "Jorge Diaz"

  Scenario: Ask for the employees of a department
    When I ask "Who works in Tecnología?"
    Then the response status is 200
    And the answer mentions "Ana Lopez"
    And the answer mentions "Marta Ruiz"
    And the answer does not mention "Luis Perez"
    And the tools used are "search_by_department"

  Scenario: Ask without an id or a department
    When I ask "Hello there"
    Then the response status is 200
    And the answer is "Pregúntame por un empleado (EMP-0001) o un departamento."
    And no tools were used

  Scenario: The agent reaches the step limit
    Given a model that always asks for a tool
    And the step limit is 2
    When I ask "Anything"
    Then the response status is 200
    And the answer is "No pude completar la respuesta. Intenta con una pregunta más concreta."

  Scenario: Empty question is rejected
    When I ask ""
    Then the response status is 422

  Scenario: Question longer than the limit is rejected
    Given the question limit is 10 characters
    When I ask "This question is far too long"
    Then the response status is 422

  Scenario: Health check reports the process
    When I request the health endpoint
    Then the response status is 200
    And the health status is "ok"
    And the health pid is a number
