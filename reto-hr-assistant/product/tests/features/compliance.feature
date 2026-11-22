Feature: Compliance rules checked at startup
  As the person who publishes the HR assistant
  I want production to refuse an insecure configuration
  So that a mistake stops the deploy instead of reaching real users

  Scenario Outline: Production refuses to start with an insecure setting
    Given a production configuration that is otherwise safe
    And the variable "<name>" is set to "<value>"
    When the assistant starts
    Then it refuses to start with an error that mentions "<name>"
    And the error does not reveal any API key

    Examples:
      | name           | value         |
      | MODEL_PROVIDER | fake          |
      | API_KEYS       | (empty)       |
      | API_KEYS       | ops:short-key |
      | HIDE_OUTPUTS   | false         |
      | PII_REDACTION  | false         |

  Scenario: A safe production configuration starts
    Given a production configuration that is otherwise safe
    When the assistant starts
    Then it starts and answers the health check
