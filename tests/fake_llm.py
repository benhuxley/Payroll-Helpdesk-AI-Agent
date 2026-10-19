"""A scripted stand-in for the Anthropic client, so the agent loop can be tested offline and for free.

Each script step is either text (the model answers) or a list of tool calls. The fake records every
request it receives, so tests can assert on what the agent sent to the model.
"""

import itertools

from anthropic.types.beta import BetaMessage

_ids = itertools.count(1)


def text(reply: str) -> dict:
    return {"text": reply}


def tools(*calls: tuple[str, dict]) -> dict:
    return {"tools": list(calls)}


def _message(step: dict) -> BetaMessage:
    if "text" in step:
        content, stop = [{"type": "text", "text": step["text"]}], "end_turn"
    else:
        content = [{"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": name, "input": args}
                   for name, args in step["tools"]]
        stop = "tool_use"
    return BetaMessage.model_validate({
        "id": f"msg_{next(_ids)}", "type": "message", "role": "assistant", "model": "fake-model",
        "content": content, "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    })


class _Messages:
    def __init__(self, script: list[dict]):
        self.script = list(script)
        self.requests: list[dict] = []

    def create(self, **params):
        self.requests.append({**params, "messages": list(params["messages"])})  # snapshot, like a real request
        if not self.script:
            raise AssertionError("FakeLLM script ran out of steps")
        step = self.script.pop(0)
        if "raise" in step:
            raise step["raise"]
        return _message(step)


def fail(exc: Exception) -> dict:
    return {"raise": exc}


class FakeLLM:
    def __init__(self, script: list[dict]):
        self.beta = type("Beta", (), {})()
        self.beta.messages = _Messages(script)
