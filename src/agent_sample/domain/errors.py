from agent_sample.domain.trace import Step


class DomainError(Exception):
    """Erro esperado, com mensagem pronta para quem usa."""


class ModelUnavailable(DomainError, RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"model unavailable: {reason}")


class UnknownOption(DomainError, ValueError):
    def __init__(self, kind: str, value: str, choices: tuple[str, ...]) -> None:
        super().__init__(f"unknown {kind}: {value} (choose from {', '.join(choices)})")


class ContentError(DomainError, ValueError):
    """Prompt ou skill inválido, inexistente ou alterado depois de publicado."""


class AgentFailed(DomainError, RuntimeError):
    """O agente terminou sem uma resposta utilizável."""

    def __init__(self, source: str, reason: str) -> None:
        self.source = source
        self.reason = reason
        super().__init__(f"{source}: {reason}")


class AgentAttemptFailed(DomainError):
    """Falha de um agente, com o passo que a registra no caminho."""

    def __init__(self, step: Step, cause: Exception) -> None:
        self.step = step
        super().__init__(f"{step.kind}:{step.name} failed: {cause}")
