"""Scripted chat model for testing the agents without an API key.

It is a real LangChain BaseChatModel, so `with_structured_output` and
`create_agent` tool calling run through LangChain's own code paths. The
`responder` decides each reply from the messages and the tools bound to the call
(for structured output, the bound tool is the pydantic schema, e.g. "Plan").
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

_ids = itertools.count(1)


class ScriptedChatModel(BaseChatModel):
    responder: Callable[[list[BaseMessage], list[str]], AIMessage]
    calls: list[dict] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        tools = [t["function"]["name"] for t in kwargs.get("tools", [])]
        self.calls.append({"messages": messages, "tools": tools})
        return ChatResult(generations=[ChatGeneration(message=self.responder(messages, tools))])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], **kwargs)

    def calls_with(self, tool: str) -> list[dict]:
        return [c for c in self.calls if tool in c["tools"]]


def tool_call(name: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{next(_ids)}"}])


def prompt_text(messages: list[BaseMessage]) -> str:
    return "\n".join(m.text for m in messages)


def passages(messages: list[BaseMessage]) -> dict[int, str]:
    """Parse the grader prompt's numbered passages: {1: text, 2: text, ...}."""
    text = prompt_text(messages)
    parts = re.split(r"\n\[(\d+)\] ", "\n" + text.split("Passages", 1)[-1])
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()
