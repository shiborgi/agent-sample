from agent_sample.domain.model import SUBJECTS


def classify_prompt() -> str:
    lines = [
        "Classifique a mensagem do usuário em exatamente um assunto.",
        'Responda somente com JSON: {"subject_id": "...", "confidence": 0.0, "rationale": "..."}.',
        "confidence fica entre 0 e 1.",
        "Assuntos permitidos:",
    ]
    lines.extend(f"- {subject.id}: {subject.description}" for subject in SUBJECTS)
    lines.append("Se houver dúvida, chame list_subjects antes de responder.")
    return "\n".join(lines)
