Feature: Compliance as code
  With ENVIRONMENT=production the HR assistant refuses to start with an
  unsafe configuration, and the error never reveals a key.

  Scenario Outline: Production refuses an unsafe setting
    Given a production configuration that is otherwise valid
    When "<name>" is set to "<value>"
    And the HR assistant starts
    Then startup fails mentioning "<mention>"
    And the startup error does not reveal "<secret>"

    Examples:
      | name           | value            | mention        | secret                   |
      | MODEL_PROVIDER | fake             | MODEL_PROVIDER | acme-production-key-0001 |
      | API_KEYS       |                  | API_KEYS       | acme-production-key-0001 |
      | API_KEYS       | acme:short-key-1 | acme           | short-key-1              |
      | HIDE_OUTPUTS   | false            | HIDE_OUTPUTS   | acme-production-key-0001 |
      | HIDE_INPUTS    | false            | HIDE_INPUTS    | acme-production-key-0001 |

  Scenario: Production starts with a safe configuration
    Given a production configuration that is otherwise valid
    When the HR assistant starts
    Then startup succeeds and "/health" answers 200
