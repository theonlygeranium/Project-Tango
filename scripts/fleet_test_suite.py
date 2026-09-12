        TestCase(
            name="guardrail_dict_format",
            description="Verify guardrail functions handle dictionary config format (not just tuples)",
            test_function=test_guardrail_dict_format,
            priority=TestPriority.CRITICAL,
            timeout_seconds=10,
        ),
