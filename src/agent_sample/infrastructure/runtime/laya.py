import asyncio
from collections.abc import Callable
from typing import Any

from agent_sample.domain.model import SUBJECTS, ClassificationFailed, Verdict

Predict = Callable[..., dict[str, Any]]


class LayaSubjectClassifier:
    runtime = "laya"

    def __init__(self, predict: Predict | None = None) -> None:
        self._predict = predict

    async def classify(self, text: str) -> Verdict:
        questions = {
            "subject": {
                "type": "choice",
                "instructions": "Qual é o assunto desta mensagem?",
                "criteria": {subject.id: subject.description for subject in SUBJECTS},
            }
        }
        try:
            result = await asyncio.to_thread(self._predict_fn(), text, questions)
            answer = result["answers"]["subject"]
            confidence = answer.get("answer_confidence", answer.get("confidence"))
            return Verdict(
                subject_id=str(answer["choice"]),
                confidence=None if confidence is None else float(confidence),
                rationale="laya choice",
                runtime=self.runtime,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ClassificationFailed(self.runtime, "response was not a subject choice") from exc

    def _predict_fn(self) -> Predict:
        if self._predict is not None:
            return self._predict
        from laya import Router

        return Router().predict
