from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

from agent_sample.domain.capabilities import CapabilitySet

OPTIONS = (
    "Metadata opcional: mode (workflow|hybrid|agent), focus, language, plugins, skills, "
    "format (text|json|pr-comments), post (bool), pull_request, repository, base, head."
)


def agent_card(url: str, capabilities: CapabilitySet, version: str) -> AgentCard:
    """Anuncia a revisão e as capacidades que vêm dos plugins habilitados."""
    review = AgentSkill(
        id="code_review",
        name="Code review",
        description=(
            "Revisa um diff unificado (no texto da mensagem) ou um pull request e devolve "
            f"decisão, achados e o caminho percorrido. {OPTIONS}"
        ),
        input_modes=["text/plain"],
        output_modes=["application/json", "text/plain"],
        tags=["code-review", *(plugin.ref for plugin in capabilities.plugins)],
        examples=["diff --git a/app.py b/app.py ..."],
    )
    reviewers = [
        AgentSkill(
            id=reviewer.ref,
            name=reviewer.name,
            description=reviewer.description,
            input_modes=["text/plain"],
            output_modes=["application/json", "text/plain"],
            tags=["reviewer", reviewer.plugin, *reviewer.languages, *reviewer.focus],
        )
        for reviewer in capabilities.reviewers
    ]
    return AgentCard(
        name="Code Reviewer",
        description="Revisão de código: workflow determinístico com uma etapa agêntica limitada.",
        version=version,
        default_input_modes=["text/plain"],
        default_output_modes=["application/json", "text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=url, protocol_version="1.0")
        ],
        skills=[review, *reviewers],
    )
