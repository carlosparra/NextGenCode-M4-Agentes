Feature: The HR assistant is safe to publish
  As the team that publishes the HR assistant
  I want every client to use its own key, a limit per minute and compliance rules
  So that only known clients use it, nobody abuses it and production is never unsafe

  Scenario Outline: A request without a valid key is rejected
    Given the HR assistant is running with API keys
    When I call <method> "<path>" with the key "<key>"
    Then the response status is 401
    And the body is exactly the invalid or missing key error
    And the key that was sent appears nowhere in the log

    Examples:
      | method | path     | key                     |
      | POST   | /ask     | none                    |
      | POST   | /ask     | wrong-key-0123456789abc |
      | GET    | /metrics | none                    |

  Scenario: A client with a valid key gets an answer and is named in the log
    Given the HR assistant is running with API keys
    When client "tester" asks "¿Quién es EMP-0004?"
    Then the response status is 200
    And the request log and the agent run name the client "tester"
    And the key that was sent appears nowhere in the log

  Scenario: The page, the health check and the docs need no key
    Given the HR assistant is running with API keys
    When I open "/", "/health" and "/docs" without a key
    Then every response status is 200

  Scenario: A client over the limit waits until the minute is over
    Given the HR assistant is running with a limit of 2 requests per minute
    When client "tester" asks 3 times
    Then the response status is 429
    And the body is exactly the rate limit error
    And the response says how many seconds to wait
    When one minute passes
    And client "tester" asks 1 times
    Then the response status is 200

  Scenario: Two clients do not share the limit
    Given the HR assistant is running with a limit of 2 requests per minute
    When client "tester" asks 2 times
    And client "other" asks 1 times
    Then the response status is 200

  Scenario Outline: Production refuses to start with unsafe settings
    Given a production configuration with <problem>
    When the HR assistant starts
    Then it refuses to start with a compliance error
    And the error shows no secret value

    Examples:
      | problem                          |
      | the fake model                   |
      | no API keys                      |
      | a key shorter than 16 characters |
      | traces that show the inputs      |

  Scenario: A well configured production starts and accepts its key
    Given a production configuration with nothing wrong
    When the HR assistant starts
    Then it answers client "acme" with status 200
