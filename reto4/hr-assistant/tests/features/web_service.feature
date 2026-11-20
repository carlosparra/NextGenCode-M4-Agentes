Feature: Web service of the HR assistant
  The API is stateless and also serves the page for HR staff.

  Scenario: The health check reports the process
    Given the HR assistant runs with the fake model
    When I open "/health"
    Then the response status is 200
    And the health status is "ok" with the current process id

  Scenario: The home page has the question form
    Given the HR assistant runs with the fake model
    When I open "/"
    Then the response status is 200
    And the page has the test ids "question, send, answer"

  Scenario: The home page never paints answers as HTML
    Given the HR assistant runs with the fake model
    When I open "/"
    Then the response status is 200
    And the page does not contain "innerHTML"

  Scenario: A history entry with an unknown role is rejected
    Given the HR assistant runs with the fake model
    When I ask "Hola" with a history entry from "system"
    Then the response status is 422
