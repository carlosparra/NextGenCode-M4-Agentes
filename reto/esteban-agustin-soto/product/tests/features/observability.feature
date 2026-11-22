Feature: Every request can be traced from its request id

  Scenario: A request without an id gets a generated one
    When I ask "Who is EMP-0004?"
    Then the X-Request-ID header is a UUID
    And the body request_id equals the header

  Scenario: A supplied request id is used everywhere
    Given the client sends the request id "abc-123"
    When I ask "Who is EMP-0004?"
    Then the X-Request-ID header is "abc-123"
    And the body request_id equals the header
    And every log line has the request id "abc-123"

  Scenario: Health checks and rejected questions also return the id
    When I request the health endpoint
    Then the X-Request-ID header is a UUID
    When I ask ""
    Then the response status is 422
    And the X-Request-ID header is a UUID

  Scenario: One question with a tool leaves request, agent_run and audit events
    When I ask "Who is EMP-0004?"
    Then the log has the events "request, agent_run, audit"
    And all log lines share one request id
    And all log timestamps are ISO 8601 in UTC

  Scenario: The log never contains the question or the answer
    When I ask "Who is EMP-0004?"
    Then the log does not contain "Who is EMP-0004"
    And the log does not contain "Según el directorio"
    And the log does not contain "Jorge Diaz"

  Scenario: An internal failure returns a 500 with the request id
    Given a model that crashes with the message "secret detail"
    When I ask "Hello"
    Then the response status is 500
    And the body is "internal error" with the request id
    And the log has an error event of type "RuntimeError"
    And the log does not contain "secret detail"

  Scenario: Metrics report the traffic of this process
    When I ask "Who is EMP-0004?"
    And I request the health endpoint
    And I request the metrics
    Then the metrics show at least 2 requests
    And the metrics have latency, token and SLO figures
    And the SLO is met

  Scenario: Slow requests break the SLO
    Given a clock that advances 5000 milliseconds per reading
    And the SLO target is 2000 milliseconds
    When I ask "Who is EMP-0004?"
    And I request the metrics
    Then the SLO is not met

  Scenario: Without a LangSmith key the product works and does not connect
    Given there is no LangSmith key
    And the tracing library fails if it is used
    When I ask "Who is EMP-0004?"
    Then the response status is 200

  Scenario: The web page has a place for the request id
    When I open the web page
    Then the page has the request id slot
    And the page does not use innerHTML
