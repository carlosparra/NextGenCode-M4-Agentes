Feature: Cost of each answer
  The assistant picks a model per question, reports what each answer cost
  and fails clearly when the real model is not available.

  Scenario: A short simple question uses the small model and has a cost
    Given the app uses the fake models
    When the user asks "Tell me about EMP-0001"
    Then the response uses the model "small-model" with route "simple"
    And the cost of the response is greater than zero

  Scenario Outline: A question that needs reasoning uses the large model
    Given the app uses the fake models
    When the user asks "<question>"
    Then the response uses the model "large-model" with route "<route>"

    Examples:
      | question                      | route           |
      | Compara EMP-0001 con EMP-0002 | keyword:compara |
      | Por qué EMP-0003 esta de baja | keyword:por qué |

  Scenario: With routing off every question uses the large model
    Given the app uses the fake models
    And routing is off
    When the user asks "Tell me about EMP-0001"
    Then the response uses the model "large-model" with route "routing_off"

  Scenario: A cache HIT from the gateway costs nothing
    Given the gateway answers with a cache HIT
    When the user asks "Tell me about EMP-0001"
    Then the response has 1 cached call
    And the cost of the response is 0

  Scenario: A gateway failure becomes a 502 with the request id
    Given the gateway fails with status 500
    When the user asks "Tell me about EMP-0001"
    Then the status is 502
    And the detail is "model unavailable" and a request id is present

  Scenario: The Cloudflare token never appears in logs or metrics
    Given the gateway answers normally
    When the user asks "Tell me about EMP-0001"
    Then neither the log nor the metrics contain the token

  Scenario: Metrics add up the cost of every response
    Given the app uses the fake models
    When the user asks "Tell me about EMP-0001"
    And the user asks "Compara EMP-0001 con EMP-0002"
    Then the metrics cost equals the sum of the response costs
