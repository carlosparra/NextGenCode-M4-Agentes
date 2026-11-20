Feature: Trace and measure every request
  As a support engineer
  I want every request to carry an id, a JSON log and metrics
  So that I can answer what happened with request X

  Scenario: Every response carries a generated request id
    When I call the health check without a request id
    Then the response carries a new UUID request id

  Scenario: The client request id is kept in the header and the body
    When I ask "¿Quién es EMP-0004?" with the request id "demo-123"
    Then the response header request id is "demo-123"
    And the response body request id is "demo-123"

  Scenario: An invalid client request id is replaced by a UUID
    When I call the health check with a request id of 200 characters
    Then the response carries a new UUID request id

  Scenario: A question leaves a correlated log without personal text
    When I ask "¿Quién es EMP-0004?" with the request id "trace-42"
    Then the log has a "request" event for "trace-42"
    And the log has an "audit" event for "trace-42" with tool "get_employee"
    And the log has an "agent_run" event for "trace-42" that stopped with "answer"
    And no log line contains "¿Quién es EMP-0004?"
    And no log line contains "Jorge Díaz"

  Scenario: A failing model returns a generic error with the request id
    Given a model that fails with a secret message
    When I ask "¿Quién es EMP-0004?" with the request id "boom-1"
    Then the response status is 500
    And the error body is generic and carries "boom-1"
    And the log has an "error" event for "boom-1" with type "RuntimeError"
    And no log line contains "secret"
    And the metrics report an error rate above 0

  Scenario: Metrics report traffic, tokens, latency and the SLO
    When I ask "¿Quién es EMP-0004?" 3 times
    Then the metrics count 3 requests
    And the metrics report input tokens above 0
    And the metrics report the p50 and p95 latency
    And the SLO is met

  Scenario: Slow requests break the SLO
    Given a clock that advances 3 seconds per reading
    When I ask "¿Quién es EMP-0004?" 1 time
    Then the SLO is not met
