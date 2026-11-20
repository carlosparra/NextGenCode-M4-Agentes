Feature: HR Assistant answers questions about employees
  As an HR staff member
  I want to ask the assistant about employees
  So that I can find information quickly

  Scenario: Query by existing employee id
    Given the HR assistant is running
    When I ask "Who is EMP-0001?"
    Then the response status is 200
    And the answer mentions "Ana Lopez"
    And the tools used include "get_employee"

  Scenario: Query by non-existent employee id
    Given the HR assistant is running
    When I ask "Who is EMP-9999?"
    Then the response status is 200
    And the answer is not empty

  Scenario: Query by existing department
    Given the HR assistant is running
    When I ask "List employees in Tecnologia"
    Then the response status is 200
    And the tools used include "search_by_department"

  Scenario: Generic question without id or department
    Given the HR assistant is running
    When I ask "Hello, how are you?"
    Then the response status is 200
    And the answer contains the help message

  Scenario: Empty question is rejected
    Given the HR assistant is running
    When I send an empty question
    Then the response status is 422

  Scenario: Question too long is rejected
    Given the HR assistant is running
    When I send a question longer than the limit
    Then the response status is 422

  Scenario: History field is optional
    Given the HR assistant is running
    When I ask "Who is EMP-0004?" without history
    Then the response status is 200
    And the answer mentions "Jorge Diaz"

  Scenario: Step cap triggers fallback message
    Given the HR assistant is running with max steps 1
    When I ask the limited app "Who is EMP-0004?"
    Then the answer contains the fallback message
