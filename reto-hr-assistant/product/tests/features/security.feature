Feature: One API key per client and a request limit
  As the owner of the HR assistant
  I want every client to use its own key and respect a limit per minute
  So that only known clients can ask and nobody can flood the service

  Background:
    Given the assistant knows the clients "alice" and "bob" with a limit of 2 questions per minute

  Scenario: A question without an API key is rejected
    When I ask "¿Quién es EMP-0004?" without an API key
    Then the response status is 401
    And the error detail is "invalid or missing API key"
    And the response has a request id
    And the log has a request event with status 401

  Scenario: A wrong API key is rejected and never written to the log
    When I ask "¿Quién es EMP-0004?" with a wrong API key
    Then the response status is 401
    And the error detail is "invalid or missing API key"
    And the log does not contain the wrong API key

  Scenario: A valid API key gets an answer and the client name is logged
    When "alice" asks "¿Quién es EMP-0004?"
    Then the response status is 200
    And the request, audit and agent_run events name the client "alice"
    And the log never contains a client API key

  Scenario: The metrics need an API key
    When I read the metrics without an API key
    Then the response status is 401
    When "alice" reads the metrics
    Then the response status is 200

  Scenario: The page, the health check and the docs do not need an API key
    When I open the page, the health check and the docs without an API key
    Then every response has status 200

  Scenario: A client over the limit must wait and can ask again later
    When "alice" asks "¿Quién es EMP-0004?"
    And the clock moves forward 20 seconds
    And "alice" asks "¿Quién es EMP-0004?" 2 times
    Then the response status is 429
    And the error detail is "rate limit exceeded"
    And the Retry-After header is "40"
    When the clock moves forward 41 seconds
    And "alice" asks "¿Quién es EMP-0004?"
    Then the response status is 200

  Scenario: The limit of one client does not affect another client
    When "alice" asks "¿Quién es EMP-0004?" 3 times
    Then the response status is 429
    When "bob" asks "¿Quién es EMP-0004?"
    Then the response status is 200
