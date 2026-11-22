Feature: Personal data protection in questions and answers
  As the person responsible for employee privacy
  I want personal data to be hidden before it reaches the model and the client
  So that no email, phone, CURP, RFC or card number leaks through the assistant

  Scenario: A question with an email is answered without the email
    Given the assistant with the simulated model
    When I ask "mi correo es ana@example.com, ¿quién es EMP-0001?"
    Then the request succeeds
    And the redacted types are ["EMAIL"]
    And neither the answer nor the log contain "ana@example.com"

  Scenario: Employee ids and dates are not personal data
    Given the assistant with the simulated model
    When I ask "¿Quién es EMP-0001? Entró el 2019-03-04"
    Then the request succeeds
    And the redacted types are []

  Scenario: An answer that is empty after the filter gets the fallback text
    Given the assistant whose model answers "<p></p>"
    When I ask "¿Qué me puedes decir?"
    Then the request succeeds
    And the answer is "No tengo una respuesta para eso."
