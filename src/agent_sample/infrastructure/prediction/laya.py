import asyncio
from collections.abc import Callable
from typing import Any

from agent_sample.domain.model import SUBJECTS, ClassificationFailed
from agent_sample.domain.ports import Prediction

Predict = Callable[..., dict[str, Any]]


class LayaPredictor:
    name = "laya"

    def __init__(self, predict: Predict | None = None) -> None:
        self._predict = predict

    async def predict(self, text: str) -> Prediction:
        questions = {
            "subject": {
                "type": "choice",
                "instructions": "Qual é o assunto desta mensagem?",
                "criteria": {subject.id: subject.description for subject in SUBJECTS},
            }
        }
        result = await asyncio.to_thread(self._predict_fn(), text, questions)
        try:
            answer = result["answers"]["subject"]
            confidence = answer.get("answer_confidence", answer.get("confidence"))
            return Prediction(
                subject_id=str(answer["choice"]),
                confidence=None if confidence is None else float(confidence),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ClassificationFailed(self.name, "response was not a subject choice") from exc

    def _predict_fn(self) -> Predict:
        if self._predict is not None:
            return self._predict
        try:
            from laya import Router
        except ImportError as exc:
            raise ClassificationFailed(
                self.name, "install the extra: uv sync --extra laya"
            ) from exc
        return Router().predict
