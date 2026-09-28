import subprocess
from pathlib import Path

from agent_sample.domain.review.model import DiffUnavailable

TIMEOUT_SECONDS = 60


class GitDiffSource:
    """`git diff` entre duas referências de um repositório local (somente leitura)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def between(self, base: str, head: str) -> str:
        for ref in (base, head):
            if not ref or ref.startswith("-"):
                raise DiffUnavailable(f"invalid git reference: {ref!r}")
        command = [
            "git",
            "-C",
            str(self._root),
            "diff",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--src-prefix=a/",
            "--dst-prefix=b/",
            base,
            head,
            "--",
        ]
        try:
            result = subprocess.run(command, capture_output=True, timeout=TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DiffUnavailable(f"git diff failed: {exc}") from exc
        if result.returncode != 0:
            reason = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
            raise DiffUnavailable(f"git diff failed: {reason[0] if reason else result.returncode}")
        return result.stdout.decode("utf-8", errors="replace")
