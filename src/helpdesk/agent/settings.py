"""Agent version settings, loaded from a YAML file in configs/.

An "agent version" is the full set of things that change behaviour: model, effort, prompt.
Evals always record which version they ran, so two versions can be compared like a parallel run.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from helpdesk.config import REPO_ROOT

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class AgentSettings:
    name: str
    model: str
    effort: str = "medium"
    max_tokens: int = 16000
    system_prompt_file: str = "system_v1.md"
    fallbacks: bool = True  # server-side refusal fallback (not available on Haiku)
    max_steps: int = 10  # model calls per user turn

    @property
    def system_prompt(self) -> str:
        return (PROMPTS_DIR / self.system_prompt_file).read_text(encoding="utf-8")


def load_settings(path: str | Path) -> AgentSettings:
    path = Path(path)
    if not path.is_absolute() and not path.exists():
        path = REPO_ROOT / path
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AgentSettings(**data)
