Feature: API key on the chat page
  The page asks for the client key in a password field, keeps it only for
  the browser session, sends it in X-API-Key and explains 401 and 429.

  Scenario: The API key field is a password kept only for the session
    Given the HR assistant runs with the fake model for a caller without an API key
    When I open "/"
    Then the response status is 200
    And the "api-key" field is a password field
    And the page contains "sessionStorage"
    And the page contains "X-API-Key"
    And the page does not contain "localStorage"
    And the page does not contain "tests-key-0123456789abcdef"

  Scenario: The page explains a rejected key and a rate limit
    Given the HR assistant runs with the fake model for a caller without an API key
    When I open "/"
    Then the page contains "Clave inválida"
    And the page contains "Demasiadas preguntas; espera"
    And the page contains "Retry-After"
