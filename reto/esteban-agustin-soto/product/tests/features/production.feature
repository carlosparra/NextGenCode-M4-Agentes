Feature: Safe production access
  The HR Assistant asks for an API key, limits requests per client and
  refuses to start in production with an unsafe configuration.

  Scenario: A request without a key is rejected
    Given the app has the clients "ana" and "bob"
    When a request to "/ask" has no key
    Then the status is 401
    And the detail is "invalid or missing API key"

  Scenario: A wrong key is rejected on the metrics endpoint
    Given the app has the clients "ana" and "bob"
    When a request to "/metrics" uses the key "wrong-key-value-123456"
    Then the status is 401
    And the detail is "invalid or missing API key"

  Scenario: A valid key is accepted
    Given the app has the clients "ana" and "bob"
    When "ana" asks "Who is EMP-0001?"
    Then the status is 200

  Scenario: Public pages need no key
    Given the app has the clients "ana" and "bob"
    Then the public paths answer 200 without a key

  Scenario: The client name is logged and the key never is
    Given the app has the clients "ana" and "bob"
    When "ana" asks "Who is EMP-0001?"
    Then the request, audit and agent_run events carry the client "ana"
    And the key of "ana" is not in the log, the metrics or an error body

  Scenario: The third request in a minute is limited
    Given the app has the clients "ana" and "bob"
    And the limit is 2 requests per minute
    When "ana" asks "Who is EMP-0001?" 3 times
    Then the last status is 429
    And the detail is "rate limit exceeded"
    And the Retry-After header is between 1 and 60

  Scenario: Another client is not affected by the limit
    Given the app has the clients "ana" and "bob"
    And the limit is 2 requests per minute
    When "ana" asks "Who is EMP-0001?" 3 times
    And "bob" asks "Who is EMP-0001?"
    Then the status is 200

  Scenario: The limit is released after a minute
    Given the app has the clients "ana" and "bob"
    And the limit is 2 requests per minute
    When "ana" asks "Who is EMP-0001?" 3 times
    And the clock advances 61 seconds
    And "ana" asks "Who is EMP-0001?"
    Then the status is 200

  Scenario: Production refuses the fake model
    Given the production setup uses the fake model
    When the app starts
    Then the start is refused mentioning "MODEL_PROVIDER"

  Scenario: Production refuses an empty key list
    Given the production setup has no API keys
    When the app starts
    Then the start is refused mentioning "API_KEYS"

  Scenario: Production refuses a key of 15 characters
    Given the production setup has a key of 15 characters for "ana"
    When the app starts
    Then the start is refused mentioning "ana"
    And the refusal does not contain the key

  Scenario: Production refuses traces that expose the inputs
    Given the production setup has tracing on and HIDE_INPUTS false
    When the app starts
    Then the start is refused mentioning "HIDE_INPUTS"

  Scenario: Production starts with a safe configuration
    Given the production setup is correct
    When the app starts
    Then the app is running

  Scenario: A malformed key list does not start and does not leak
    Given the key list is "ana:secret-value-12345678,broken-entry"
    When the app starts
    Then the start is refused mentioning "API_KEYS"
    And the refusal mentions the length 12
    And the refusal does not contain "secret-value-12345678"
