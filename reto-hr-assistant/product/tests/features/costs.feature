Feature: Cost levers
  The assistant picks a model per question, trims the history, uses the gateway
  cache and reports what each answer cost, without losing quality.

  Scenario: A simple question goes to the small model
    Given the assistant runs with the default configuration
    When I ask "¿Quién es EMP-0004?"
    Then the answer comes from the model "@cf/meta/llama-3.1-8b-instruct-fast"
    And the route is "default_small"
    And the answer cost is greater than zero

  Scenario: A question with a keyword goes to the large model
    Given the assistant runs with the default configuration
    When I ask "Compara los departamentos de la empresa"
    Then the answer comes from the model "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    And the route is "keyword:compara"

  Scenario: A question longer than the router limit goes to the large model
    Given the variable "ROUTER_MAX_CHARS" is set to "20"
    When I ask "¿Quién es EMP-0004 en la empresa?"
    Then the answer comes from the model "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    And the route is "long_question"

  Scenario: With routing disabled every question goes to the large model
    Given the variable "ROUTING" is set to "false"
    When I ask "¿Quién es EMP-0004?"
    Then the answer comes from the model "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    And the route is "routing_disabled"

  Scenario: The history window limits what the model receives
    Given the variable "HISTORY_WINDOW" is set to "2"
    And a scripted model that answers directly
    When I ask "¿Y su departamento?" after a history of four messages
    Then the model receives only the last 2 history messages

  Scenario: A cached gateway reply is counted and costs nothing
    Given the gateway answers from its cache
    When I ask "¿Quién es EMP-0004?"
    Then the answer reports 1 cached call
    And the answer cost is zero

  Scenario: A gateway failure is reported as model unavailable
    Given the gateway is failing
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 502
    And the error says "model unavailable" with the request id

  Scenario: The metrics add up the cost of every answer
    Given the assistant runs with the default configuration
    When I ask "¿Quién es EMP-0004?"
    And I ask "¿Quién es EMP-0001?"
    Then the metrics cost is the sum of both answers
