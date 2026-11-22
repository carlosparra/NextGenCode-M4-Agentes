Feature: PII masking
  A CURP or an email written by a person never comes back out of the
  server: the model, the answer and the log only see the markers [CURP]
  and [EMAIL]. The request is still served.

  Scenario: A question with a CURP and an email is masked before the model
    Given a scripted model that answers "Done."
    When I ask the question "My CURP is <CURP> and my email is <EMAIL>"
    Then the response status is 200
    And the model never receives the CURP or the email
    And the model receives the markers "[CURP]" and "[EMAIL]"
    And the log has no CURP and no email

  Scenario: History messages of both roles are masked before the model
    Given a scripted model that answers "Done."
    When I ask the question "And now?" with the CURP in a user message and the email in an assistant message
    Then the response status is 200
    And the model never receives the CURP or the email
    And the log has no CURP and no email

  Scenario: An answer invented by the model is masked
    Given a scripted model that answers with the CURP and the email
    When I ask the question "Hello"
    Then the answer is "Your data is [CURP] and [EMAIL]"
    And the log has no CURP and no email

  Scenario: Tool arguments chosen by the model are masked in the audit log
    Given a scripted model that asks for the email as employee id and the CURP as department
    When I ask the question "Hello"
    Then the response status is 200
    And the tool audit events show the arguments "[EMAIL]" and "[CURP]"
    And the log has no CURP and no email

  Scenario: Each place that was masked has one audit event with counts only
    Given a scripted model that answers with the email
    When I ask the question "My CURP is <CURP>" with the email in a user message and in an assistant message
    Then there are exactly 3 pii_masked events
    And the pii_masked event for "question" counts 1 CURP and 0 email
    And the pii_masked event for "history" counts 0 CURP and 2 email
    And the pii_masked event for "answer" counts 0 CURP and 1 email
    And the pii_masked events carry no value

  Scenario: Production refuses to start with PII masking off
    Given the production setup has PII_MASKING false
    When the app starts
    Then the start is refused mentioning "PII_MASKING"

  Scenario: Production starts when PII masking is not set
    Given the production setup does not set PII_MASKING
    When the app starts
    Then the app is running
