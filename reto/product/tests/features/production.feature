Feature: Safe production access
  Only clients with a valid API key can ask, nobody can flood the service,
  and the product refuses to start in production with an unsafe configuration.

  Background:
    Given the product runs with the client "tests" and a limit of 2 requests per minute

  Scenario: Asking without a key is rejected
    When I ask "¿Quién es EMP-0004?" without a key
    Then the response status is 401
    And the error detail is "invalid or missing API key"
    And the key never appears in the log or the traces

  Scenario: Asking with a wrong key is rejected
    When I ask "¿Quién es EMP-0004?" with the key "wrong-key-value-123456"
    Then the response status is 401
    And the error detail is "invalid or missing API key"
    And the text "wrong-key-value-123456" never appears in the log or the traces

  Scenario: A valid key answers and logs only the client name
    When I ask "¿Quién es EMP-0004?" with the valid key
    Then the response status is 200
    And the "request" event of the log has the client "tests"
    And the traces carry the client "tests"
    And the key never appears in the log or the traces

  Scenario: Public pages need no key but metrics do
    Then "/", "/health" and "/docs" answer 200 without a key
    And "/metrics" answers 401 without a key and 200 with the valid key

  Scenario: Too many requests are rejected until the minute passes
    When I ask 2 questions with the valid key
    And 20 seconds pass
    And I ask "¿Quién es EMP-0004?" with the valid key
    Then the response status is 429
    And the error detail is "rate limit exceeded"
    And the header "Retry-After" is "40"
    When 40 seconds pass
    And I ask "¿Quién es EMP-0004?" with the valid key
    Then the response status is 200

  Scenario: The rate limit is counted per client
    Given a second client "other" with its own key
    When I ask 3 questions with the valid key
    And I ask "¿Quién es EMP-0004?" as the client "other"
    Then the response status is 200

  Scenario Outline: Production refuses to start with an unsafe configuration
    When the product starts in production with <setting>
    Then it refuses to start with an error that names "<variable>"
    And the error never contains a key

    Examples:
      | setting                                | variable       |
      | the fake model                         | MODEL_PROVIDER |
      | no API keys                            | API_KEYS       |
      | a key of 15 characters                 | API_KEYS       |
      | traces on and outputs not hidden       | HIDE_OUTPUTS   |

  Scenario: Production starts with a safe configuration
    When the product starts in production with a safe configuration
    Then it starts and "/health" answers 200

  Scenario: A malformed API_KEYS names the entry and its length but not its value
    When the product reads API_KEYS "tests:tests-key-0123456789abcd,secret-value-without-client"
    Then it refuses to start with an error that names "2"
    And the error mentions the length 27
    And the error does not contain "secret-value-without-client"
