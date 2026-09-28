from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill


def agent_card(url: str) -> AgentCard:
    skill = AgentSkill(
        id="classify_subject",
        name="Classify subject",
        description=(
            "Classifica o assunto de uma mensagem de texto. Metadata opcional da requisição: "
            "strategy (workflow|agent|hybrid|prediction), engine, agent, prompt_version."
        ),
        input_modes=["text/plain"],
        output_modes=["text/plain"],
        tags=["subject", "classification"],
        examples=["Fui cobrado duas vezes em março.", "A API retorna 500 ao abrir a configuração."],
    )
    return AgentCard(
        name="Subject Classifier",
        description="Avalia o assunto de uma mensagem.",
        version="0.1.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=url, protocol_version="1.0")
        ],
        skills=[skill],
    )
