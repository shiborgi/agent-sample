from agent_sample.domain.review.change import prepare_change
from agent_sample.domain.review.model import Review
from agent_sample.domain.review.ports import ChangeReviewer


async def review_change(
    text: str,
    reviewer: ChangeReviewer,
    focus: tuple[str, ...] = (),
    language: str | None = None,
) -> Review:
    """Lê e valida o diff antes de revisar: diff vazio ou ilegível é erro, nunca revisão vazia."""
    return await reviewer.review(prepare_change(text, focus, language))
