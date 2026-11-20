Feature: Every answer is cheaper without getting worse
  As the person who pays for the HR assistant
  I want each answer to say which model it used, why, and what it cost
  So that I can measure every cost lever and keep only the ones that work

  Scenario: A simple question uses the small model and has a cost
    Given the HR assistant is running
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the answer used the small model because of "simple_question"
    And the cost is above 0

  Scenario: A question that asks to compare uses the large model
    Given the HR assistant is running
    When I ask "Compara a EMP-0001 con EMP-0004"
    Then the answer used the large model because of "keyword"

  Scenario: A question longer than the router limit uses the large model
    Given the HR assistant is running
    When I ask "Necesito los datos completos del empleado EMP-0004 para el expediente de su evaluacion anual"
    Then the answer used the large model because of "long_question"

  Scenario: With routing off every question uses the large model
    Given the HR assistant is running with routing off
    When I ask "¿Quién es EMP-0004?"
    Then the answer used the large model because of "routing_disabled"

  Scenario: Only the last messages of the history reach the model
    Given the HR assistant is running with a history window of 6
    When I ask "¿Quién es EMP-0004?" with a history of 10 messages
    Then the response status is 200
    And the model received the last 6 history messages plus the question

  Scenario: The metrics add up the cost of every answer
    Given the HR assistant is running
    When I ask "¿Quién es EMP-0004?"
    And I ask "Compara a EMP-0001 con EMP-0004"
    And I call GET "/metrics"
    Then the metrics cost is the sum of both answers

  Scenario: A gateway failure returns 502 with the request id
    Given the HR assistant is running with a gateway that is down
    When I ask "¿Quién es EMP-0004?" with request id down-1
    Then the response status is 502
    And the body is the model unavailable error with request id "down-1"
    And the log has an error event of type "ModelUnavailable" without the message

  Scenario: A cache hit is counted and costs nothing
    Given the HR assistant is running with a gateway whose cache answers HIT
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the answer has 1 cached call and a cost of 0
