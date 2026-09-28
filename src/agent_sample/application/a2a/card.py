from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill


def agent_card(url: str) -> AgentCard:
    classify = AgentSkill(
        id="classify_subject",
        name="Classify subject",
        description=(
            "Classifica o assunto de uma mensagem de texto (skill padrão). Metadata opcional: "
            "strategy (workflow|agent|hybrid|prediction), engine, agent, prompt_version."
        ),
        input_modes=["text/plain"],
        output_modes=["text/plain"],
        tags=["subject", "classification"],
        examples=["Fui cobrado duas vezes em março.", "A API retorna 500 ao abrir a configuração."],
    )
    review = AgentSkill(
        id="review_change",
        name="Review change",
        description=(
            "Revisa um diff unificado e devolve a revisão em JSON (decision, summary, findings, "
            "unreviewed, trace). Use metadata skill=review_change. Metadata opcional: strategy "
            "(workflow|agent|hybrid), engine, agent, prompt_version, skills, focus, language."
        ),
        input_modes=["text/plain"],
        output_modes=["application/json"],
        tags=["code-review", "diff"],
        examples=["diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ ..."],
    )
    return AgentCard(
        name="Agent Sample",
        description="Classifica o assunto de mensagens e revisa mudanças de código.",
        version="0.2.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=url, protocol_version="1.0")
        ],
        skills=[classify, review],
    )
