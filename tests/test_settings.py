from pathlib import Path

import pytest

from helpdesk.agent.settings import load_settings

CONFIGS = sorted(Path("configs").glob("*.yaml"))


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.stem)
def test_every_agent_version_loads_with_pay_rules_filled_in(path):
    settings = load_settings(path)
    prompt = settings.system_prompt
    assert "{{" not in prompt
    assert "Sunday: 175%" in prompt
    if settings.model.startswith("claude-haiku"):
        assert settings.fallbacks is False  # Haiku has no server-side refusal fallback
