Feature: Vacation balance and department summary tools
  As an HR person
  I want the assistant to give me vacation balances and department summaries
  So that the numbers are calculated in code and never guessed by the model

  Scenario: The vacation balance of an active employee is calculated in code
    Given the employee directory
    When I ask the vacation balance of "EMP-0004"
    Then the balance of "Jorge Díaz" shows 16 total days, 4 taken and 12 available

  Scenario: An employee who left has no vacation balance
    Given the employee directory
    When I ask the vacation balance of "EMP-0003"
    Then the tool says the employee no longer has a vacation balance

  Scenario: An unknown employee gets the same message as get_employee
    Given the employee directory
    When I ask the vacation balance of "EMP-9999"
    Then the message is the same one get_employee gives for "EMP-9999"

  Scenario: The department summary ignores case and accents
    Given the employee directory
    When I ask the summary of the department "tecnologia"
    Then the summary shows 3 employees, 2 active and 1 inactive
    And the average available vacation days of the active employees is 13.5

  Scenario: An unknown department lists the valid departments
    Given the employee directory
    When I ask the summary of the department "Marketing"
    Then the tool lists every valid department
