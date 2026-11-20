Feature: Cheaper answers through measurable cost levers
  Each answer says which model produced it, why, and how much it cost.
  A rule picks a small or a large model, the history is trimmed,
  and answers served from the gateway cache are free.

  Scenario: A simple question goes to the small model and has a cost
    Given the HR assistant runs with the fake model
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the answer comes from the small model
    And the route is "simple_question"
    And the cost is greater than zero

  Scenario: A question with a keyword goes to the large model
    Given the HR assistant runs with the fake model
    When I ask "Compara a las personas de Ventas y Finanzas"
    Then the response status is 200
    And the answer comes from the large model
    And the route is "keyword:compara"

  Scenario: A question longer than the router limit goes to the large model
    Given the HR assistant runs with the fake model
    When I send a question of 81 characters
    Then the response status is 200
    And the answer comes from the large model
    And the route is "long_question"

  Scenario: With routing turned off every question goes to the large model
    Given the HR assistant runs with the fake model and "ROUTING" set to "false"
    When I ask "¿Quién es EMP-0004?"
    Then the answer comes from the large model
    And the route is "routing_disabled"

  Scenario: Only the last messages of the history reach the model
    Given the HR assistant runs with a model that records the conversation
    When I ask "¿Quién es EMP-0004?" after 10 history messages
    Then the response status is 200
    And the model received the last 6 history messages and the question

  Scenario: An answer served from the gateway cache is free
    Given the HR assistant runs behind a gateway that answers from its cache
    When I ask "Hola"
    Then the response status is 200
    And the cached calls are 1
    And the cost is zero

  Scenario: A gateway that is down gives a clear error
    Given the HR assistant runs behind a gateway that is down
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 502
    And the error is "model unavailable" with a request id

  Scenario: The metrics add up the cost of every answer
    Given the HR assistant runs with the fake model
    When I ask "¿Quién es EMP-0004?" and then "Compara Ventas y Finanzas"
    And I open "/metrics"
    Then the metrics cost is the sum of both answers

  Scenario: A keyword hidden inside another word does not change the model
    Given the HR assistant runs with the fake model
    When I ask "¿Qué métodos de pago hay?"
    Then the response status is 200
    And the answer comes from the small model
    And the route is "simple_question"

  Scenario: A derived form of a keyword goes to the large model
    Given the HR assistant runs with the fake model
    When I ask "Explícame el organigrama"
    Then the response status is 200
    And the answer comes from the large model
    And the route is "keyword:explica"

  Scenario: The gateway is asked to cache answers when the cache is on
    Given the HR assistant runs behind a recording gateway with "CACHE_TTL_SECONDS" set to "60"
    When I ask "Hola"
    Then the response status is 200
    And the gateway received the header "cf-aig-cache-ttl" with "60"

  Scenario: Every gateway call carries the output cap
    Given the HR assistant runs behind a recording gateway with "MODEL_MAX_TOKENS" set to "120"
    When I ask "Hola"
    Then the response status is 200
    And the gateway received "max_tokens" equal to 120

  Scenario: An answer that misses the gateway cache is charged
    Given the HR assistant runs behind a recording gateway with "CACHE_TTL_SECONDS" set to "60"
    When I ask "Hola"
    Then the cached calls are 0
    And the cost is greater than zero
