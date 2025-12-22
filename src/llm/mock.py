class MockLLM:
    """Deterministic mock used in CI to avoid outbound OpenAI calls."""

    def invoke(self, prompt):
        return "resposta mockada"
