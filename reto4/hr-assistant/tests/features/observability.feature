Feature: Observability of the HR assistant
  Every request can be followed by its id, in the JSON log and in the metrics.

  Scenario: A request without an id gets a generated one
    Given the HR assistant runs with the fake model
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the response has a generated request id in the header and the body

  Scenario: The request id sent by the client is kept
    Given the HR assistant runs with the fake model
    When I ask "¿Quién es EMP-0004?" with the request id "support-ticket-7"
    Then the response status is 200
    And the request id is "support-ticket-7" in the header and the body

  Scenario: The metrics report every field of the process
    Given the HR assistant runs with the fake model
    When I ask "¿Quién es EMP-0004?"
    And I open "/metrics"
    Then the response status is 200
    And the metrics report requests, error rate, latency, tokens, SLO and cost

  Scenario: An internal error answers 500 with the request id
    Given the HR assistant runs with a model that crashes with "secret crash detail"
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 500
    And the error is "internal error" with a request id
    And the "error" log line does not contain "secret crash detail"

  Scenario: The agent_run log never contains the question
    Given the HR assistant runs with the fake model
    When I ask "¿Cuál es el estado de EMP-0004?"
    Then the response status is 200
    And the "agent_run" log line does not contain "¿Cuál es el estado de EMP-0004?"
