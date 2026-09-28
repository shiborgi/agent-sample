import logging

from agent_sample.domain.content import AgentAnswer, AgentRequest, PromptVersion, SkillVersion
from agent_sample.domain.errors import AgentAttemptFailed
from agent_sample.domain.model import SAFE_SUBJECT, ClassificationFailed, Verdict, subject_by_id
from agent_sample.domain.ports import Agent, Predictor, WorkflowEngine
from agent_sample.domain.rules import RuleOutcome
from agent_sample.domain.tools import TOOLS, RunContext, Toolbox
from agent_sample.domain.trace import Outcome, Step
from agent_sample.domain.workflow import WORKFLOW, WorkflowState

logger = logging.getLogger(__name__)


class WorkflowStrategy:
    """Regras explícitas e reproduzíveis; empate ou falta de evidência resulta em `other`."""

    def __init__(self, engine: WorkflowEngine) -> None:
        self._engine = engine
        self.name = f"workflow:{engine.name}"

    async def evaluate(self, text: str) -> tuple[RuleOutcome, Step]:
        state = await self._engine.run(WORKFLOW, WorkflowState(text))
        if state.outcome is None:
            raise ClassificationFailed(self.name, "workflow ended without a decision")
        outcome: Outcome = "undecided" if state.outcome.subject_id is None else "decided"
        return state.outcome, Step("workflow", self._engine.name, outcome, state.outcome.detail)

    async def classify(self, text: str) -> Verdict:
        outcome, step = await self.evaluate(text)
        subject_id = outcome.subject_id or SAFE_SUBJECT
        return Verdict(subject_id, outcome.detail, self.name, (step,))


class AgentStrategy:
    """Um agente decide, guiado por uma versão de prompt e pelas skills que escolher carregar."""

    def __init__(
        self,
        agent: Agent[AgentAnswer],
        prompt: PromptVersion,
        skills: tuple[SkillVersion, ...],
    ) -> None:
        self._agent = agent
        self._prompt = prompt
        self._skills = skills
        self.name = f"agent:{agent.name}"

    async def consult(self, text: str) -> tuple[str, str, Step]:
        toolbox = Toolbox(RunContext(self._skills), TOOLS)
        try:
            answer = await self._agent.run(AgentRequest(text, self._prompt, self._skills), toolbox)
            subject_by_id(answer.subject_id)
        except Exception as exc:
            raise AgentAttemptFailed(self._step("failed", str(exc), toolbox), exc) from exc
        return answer.subject_id, answer.rationale, self._step("decided", answer.rationale, toolbox)

    async def classify(self, text: str) -> Verdict:
        subject_id, rationale, step = await self.consult(text)
        return Verdict(subject_id, rationale, self.name, (step,))

    def _step(self, outcome: Outcome, detail: str, toolbox: Toolbox[RunContext]) -> Step:
        return Step(
            "agent",
            self._agent.name,
            outcome,
            detail,
            prompt=self._prompt.ref,
            skills=toolbox.loaded_skills,
        )


class HybridStrategy:
    """Regras primeiro; agente só quando as regras não decidem; `other` se o agente falhar."""

    def __init__(self, workflow: WorkflowStrategy, agent: AgentStrategy) -> None:
        self._workflow = workflow
        self._agent = agent
        self.name = f"hybrid({workflow.name}->{agent.name})"

    async def classify(self, text: str) -> Verdict:
        outcome, rules = await self._workflow.evaluate(text)
        if outcome.subject_id is not None:
            return Verdict(outcome.subject_id, outcome.detail, self._workflow.name, (rules,))
        try:
            subject_id, rationale, step = await self._agent.consult(text)
        except AgentAttemptFailed as exc:
            logger.warning("hybrid fell back to %s: %s", SAFE_SUBJECT, exc)
            fallback = Step(
                "fallback", "safe-subject", "decided", "assunto seguro após falha do agente"
            )
            rationale = f"{outcome.detail}; agente falhou, usando assunto seguro"
            return Verdict(SAFE_SUBJECT, rationale, "fallback", (rules, exc.step, fallback))
        return Verdict(subject_id, rationale, self._agent.name, (rules, step))


class PredictionStrategy:
    """Predição de passo único (não agêntica): um forward pass escolhe o assunto."""

    def __init__(self, predictor: Predictor) -> None:
        self._predictor = predictor
        self.name = f"prediction:{predictor.name}"

    async def classify(self, text: str) -> Verdict:
        prediction = await self._predictor.predict(text)
        detail = "predição de passo único"
        step = Step("prediction", self._predictor.name, "decided", detail)
        return Verdict(prediction.subject_id, detail, self.name, (step,), prediction.confidence)
