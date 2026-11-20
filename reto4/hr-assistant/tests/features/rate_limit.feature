Feature: Rate limit per client
  A client that sends more than RATE_LIMIT_PER_MINUTE requests in a minute
  gets 429 with Retry-After. The clock is injected, so nobody waits.

  Scenario: A client over the limit must wait until the window moves
    Given the HR assistant runs with a limit of 2 requests per minute and a fake clock
    When I send 3 questions
    Then the response status is 429
    And the response body is exactly the error "rate limit exceeded"
    And the response asks to retry after 60 seconds
    When the clock moves forward 61 seconds
    And I ask "¿Quién es EMP-0004?"
    Then the response status is 200

  Scenario: Clients do not share their limit
    Given the HR assistant runs for the clients "acme,globex" with a limit of 1 request per minute
    When the client "acme" sends 2 questions
    And the client "globex" sends 1 question
    Then the last response for "acme" has status 429
    And the last response for "globex" has status 200
