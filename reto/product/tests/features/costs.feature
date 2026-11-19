Feature: Make every answer cheaper without making it worse
  As the owner of the HR Assistant budget
  I want each answer to use the cheapest suitable model and report its cost
  So that I can lower the bill without losing quality

  Scenario: A simple question goes to the small model and has a cost
    Given the product runs with the simulated models
    When I ask "¿Quién es EMP-0004?"
    Then the answer used the small model with route "default_small"
    And the answer cost is above 0

  Scenario: A comparison goes to the large model
    Given the product runs with the simulated models
    When I ask "Compara a los empleados del departamento de Finanzas"
    Then the answer used the large model with route "keyword:compara"

  Scenario: The same question costs less with the small model and the answer is the same
    Given the product runs once with routing and once without routing
    When I ask "¿Quién es EMP-0004?" to both
    Then the small model answer costs less than the large model answer
    And both answers say the same

  Scenario: A long question goes to the large model
    Given the product runs with the simulated models
    When I ask a question of 81 characters without keywords
    Then the answer used the large model with route "long_question"

  Scenario: With routing disabled every question goes to the large model
    Given the product runs with the simulated models and routing disabled
    When I ask "¿Quién es EMP-0004?"
    Then the answer used the large model with route "routing_disabled"

  Scenario: Only the latest history messages reach the model
    Given a spy model that records what it receives
    When I ask "¿Quién es EMP-0004?" with 10 history messages
    Then the model received only the last 6 history messages

  Scenario: Metrics add up the cost of every answer
    Given the product runs with the simulated models
    When I ask "¿Quién es EMP-0004?" and then "Compara a los empleados de Finanzas"
    Then the metrics cost is the sum of both answer costs

  Scenario: A failing gateway returns model unavailable with the request id
    Given a gateway that answers with status 500
    When I ask "¿Quién es EMP-0004?" with the request id "gw-down-1"
    Then the response status is 502
    And the error body says "model unavailable" and carries "gw-down-1"
    And the log has an "error" event for "gw-down-1" with type "ModelUnavailable"

  Scenario: A cached gateway answer is counted and costs nothing
    Given a gateway that answers from its cache
    When I ask "¿Quién es EMP-0004?"
    Then the answer has 1 cached call and costs 0
