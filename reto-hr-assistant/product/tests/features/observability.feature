Feature: Observability of every request
  As a support person
  I want each request to leave an id, JSON log lines and metrics
  So that I can tell with data what happened with request X

  Scenario: Every response carries a generated request id
    Given the assistant is running as service "hr-demo"
    When I call every endpoint without a request id
    Then every response has a UUID in the X-Request-ID header

  Scenario: A request id sent by the client is returned unchanged
    Given the assistant is running as service "hr-demo"
    When I ask "¿Quién es EMP-0004?" with the request id "demo-123"
    Then the X-Request-ID header is "demo-123"
    And the body request_id matches the X-Request-ID header

  Scenario: An unsafe request id is replaced by a UUID
    Given the assistant is running as service "hr-demo"
    When I ask "¿Quién es EMP-0004?" with the request id "bad id <script>"
    Then the X-Request-ID header is a UUID
    And the body request_id matches the X-Request-ID header

  Scenario: A question leaves one event of each kind with the same request id
    Given the assistant is running as service "hr-demo"
    When I ask "¿Quién es EMP-0004?" with the request id "trace-1"
    Then the log has exactly 1 "request" event
    And the log has exactly 1 "agent_run" event
    And the log has exactly 1 "audit" event
    And every log line has request id "trace-1", a UTC timestamp and service "hr-demo"
    And the audit event records the tool "get_employee" with employee_id "EMP-0004"
    And the request event records POST /ask with status 200 and a latency

  Scenario: The log never contains the question or the answer
    Given the assistant is running as service "hr-demo"
    When I ask "¿Quién es EMP-0004? Lo pregunto por la nómina" with the request id "privacy-1"
    Then the log does not contain the question
    And the log does not contain the answer

  Scenario: The agent run reports that it hit the step cap
    Given the assistant is running with at most 1 agent step
    When I ask "¿Quién es EMP-0004?" with the request id "cap-1"
    Then the agent_run event says it stopped at "max_steps" after 1 step
    And the agent_run event counts the question characters and 0 history messages

  Scenario: A failing model returns a 500 with the request id and logs the error type
    Given the assistant is running with a model that fails with "secret failure detail"
    When I ask "¿Quién es EMP-0004?" with the request id "boom-1"
    Then the response is a 500 internal error that includes the request id
    And the log has an error event of type "RuntimeError" without the message
    And the request event records POST /ask with status 500 and a latency

  Scenario: Metrics summarize the questions answered by this process
    Given the assistant is running as service "hr-demo"
    When I ask 2 questions
    And I read the metrics
    Then the metrics count 2 requests with no errors
    And the metrics report input and output tokens
    And the metrics report p50 and p95 latencies within the SLO of 2000 ms

  Scenario: A slow process breaks the latency SLO
    Given the assistant is running with a clock that takes 3 seconds per request
    When I ask 2 questions
    And I read the metrics
    Then the metrics say the SLO is not met

  Scenario: Tracing without an API key works and never loads LangSmith
    Given LangSmith tracing is on but there is no API key
    When I ask "¿Quién es EMP-0004?" with the request id "no-key-1"
    Then the response is a normal answer

  Scenario: The web page shows the request id of each answer
    Given the assistant is running as service "hr-demo"
    When I open the home page
    Then the page has an element for the request id
