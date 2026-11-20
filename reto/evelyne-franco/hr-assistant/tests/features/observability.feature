Feature: Every request can be traced from the browser to the log
  As a support engineer
  I want each request to carry an id that appears in the log and the metrics
  So that I can answer what happened with request X

  Scenario Outline: Every response carries a generated request id
    Given the HR assistant is running
    When I call GET "<path>" without a request id
    Then the response has a generated UUID in the X-Request-ID header

    Examples:
      | path     |
      | /health  |
      | /metrics |

  Scenario: The client request id is kept in the header and the body
    Given the HR assistant is running
    When I ask "Who is EMP-0001?" with request id "demo-123"
    Then the response status is 200
    And the X-Request-ID header is "demo-123"
    And the body request_id is "demo-123"

  Scenario: An invalid client request id is replaced by a UUID
    Given the HR assistant is running
    When I ask "Who is EMP-0001?" with a request id of 200 characters
    Then the response has a generated UUID in the X-Request-ID header
    And the body request_id matches the X-Request-ID header

  Scenario: One question writes one request, one agent_run and one audit per tool
    Given the HR assistant is running
    When I ask "Who is EMP-0001?" with request id "trace-1"
    Then the log has exactly 1 "request" event
    And the log has exactly 1 "agent_run" event
    And the log has exactly 1 "audit" event for tool "get_employee"
    And every log event has ts, service, event and request_id "trace-1"
    And the request event reports POST /ask with status 200 and 250 ms

  Scenario: The log never contains the question or the answer
    Given the HR assistant is running
    When I ask "Who is EMP-0004? my-private-note" with request id "privacy-1"
    Then the log does not contain "my-private-note"
    And the log does not contain the answer text

  Scenario: A validation error still carries the request id and is logged
    Given the HR assistant is running
    When I send an empty question
    Then the response status is 422
    And the response has a generated UUID in the X-Request-ID header
    And the request event reports status 422

  Scenario: An internal error returns 500 with the request id and logs only the type
    Given the HR assistant is running with a model that fails
    When I ask "Who is EMP-0001?" with request id "boom-1"
    Then the response status is 500
    And the body is the internal error with request id "boom-1"
    And the log has an error event of type "RuntimeError" without the message

  Scenario: Metrics report requests, latency, tokens and the SLO
    Given the HR assistant is running
    When I ask "Who is EMP-0001?" with request id "metrics-1"
    And I call GET "/metrics" without a request id
    Then the metrics report at least 1 request
    And the metrics report p50 and p95 latency
    And the metrics report input and output tokens above 0
    And the SLO is met with target 2000 ms

  Scenario: Slow requests break the latency SLO
    Given the HR assistant is running with requests that take 3 seconds
    When I ask "Who is EMP-0001?" with request id "slow-1"
    And I call GET "/metrics" without a request id
    Then the SLO is not met with target 2000 ms

  Scenario: The web page shows the request id of each answer
    Given the HR assistant is running
    When I call GET "/" without a request id
    Then the response has a generated UUID in the X-Request-ID header
    And the page shows the request_id using textContent
