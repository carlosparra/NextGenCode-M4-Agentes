Feature: Personal data is masked
  Emails, CURP, RFC, card numbers, NSS and phone numbers are replaced by a
  "[<kind> oculto]" mark before the question reaches the model and before the
  answer reaches the user. The log only counts what was masked, never the value.

  Scenario: Personal data in the question never reaches the model
    Given the HR assistant runs with a model that records the conversation
    When I ask "Escribe a ana@empresa.com"
    Then the response status is 200
    And the model never received "ana@empresa.com"
    And the model received a message containing "[email oculto]"

  Scenario: Personal data in the history never reaches the model
    Given the HR assistant runs with a model that records the conversation
    When I ask "¿Me ayudas?" after saying "Mi tel es 55 1234 5678"
    Then the response status is 200
    And the model never received "55 1234 5678"
    And the model received a message containing "[phone oculto]"

  Scenario: Personal data in the answer is hidden from the user
    Given the HR assistant runs with a model that answers "Su RFC es LOPA800101AB1"
    When I ask "¿Cuál es mi RFC?"
    Then the response status is 200
    And the answer is "Su RFC es [rfc oculto]"

  Scenario: The log counts the masked data but never writes the value
    Given the HR assistant runs with a model that records the conversation
    When I ask "Escribe a ana@empresa.com y a luis@empresa.com"
    Then the response status is 200
    And the log records 2 masked "email"
    And no log line contains "ana@empresa.com"
    And no log line contains "luis@empresa.com"

  Scenario: A question without personal data reaches the model unchanged
    Given the HR assistant runs with a model that records the conversation
    When I ask "¿Quién trabaja en Tecnología?"
    Then the response status is 200
    And the model received a message containing "¿Quién trabaja en Tecnología?"
    And the model never received "oculto"
