Feature: One API key per client
  Asking questions and reading the metrics need a valid X-API-Key header.
  The public pages need no key, and the key is never written to the log.

  Scenario: Asking without an API key is rejected
    Given the HR assistant runs with the fake model for a caller without an API key
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 401
    And the response body is exactly the error "invalid or missing API key"

  Scenario: Asking with a wrong API key is rejected
    Given the HR assistant runs with the fake model for a caller with the API key "not-a-real-key-000000"
    When I open "/metrics"
    Then the response status is 401
    And the response body is exactly the error "invalid or missing API key"

  Scenario: Public routes need no API key
    Given the HR assistant runs with the fake model for a caller without an API key
    When I open "/"
    Then the response status is 200
    And the page has the test ids "api-key"
    And the page does not contain "localStorage"
    And the paths "/health,/docs" answer 200

  Scenario: A valid key names the client in the log but the key is never written
    Given the HR assistant runs for the client "acme" with the API key "acme-secret-key-123456"
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the "request" log line names the client "acme"
    And no log line contains "acme-secret-key-123456"
