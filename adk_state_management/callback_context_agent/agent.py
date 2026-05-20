"""
CallbackContext.state demo agent.

LlmAgent supports before_agent_callback and after_agent_callback.
Both receive a CallbackContext whose .state mutations are committed
as a state_delta automatically — same as ToolContext.

This agent tracks turn_count, started_at, and completed_at per turn.
Use show_lifecycle() to inspect what was recorded.

Run with:
    adk web    (from adk_state_management/)
    adk run callback_context_agent
"""

from datetime import datetime, timezone
from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.tool_context import ToolContext
from google.genai import types

MODEL = "gemini-2.0-flash"

_INSTRUCTION = """
You are an ADK callback demo agent.

Before every response the before_agent_callback increments turn_count and
records turn_started_at. After every response the after_agent_callback
records turn_completed_at. These happen without any code in this instruction.

Use show_lifecycle() to show the user what was captured, then explain how
before_agent_callback and after_agent_callback work.
""".strip()


def _before_agent(ctx: CallbackContext) -> Optional[types.Content]:
    turn = ctx.state.get("turn_count", 0) + 1
    ctx.state["turn_count"] = turn
    ctx.state["turn_started_at"] = datetime.now(timezone.utc).isoformat()
    return None  # let the agent run normally


def _after_agent(ctx: CallbackContext) -> Optional[types.Content]:
    ctx.state["turn_completed_at"] = datetime.now(timezone.utc).isoformat()
    return None  # pass the original response through


def show_lifecycle(tool_context: ToolContext) -> str:
    """Show the lifecycle timestamps and turn counter from session state."""
    lines = ["Lifecycle state captured by callbacks:"]
    lines.append(f"  turn_count        = {tool_context.state.get('turn_count', 0)}")
    lines.append(
        f"  turn_started_at   = {tool_context.state.get('turn_started_at', '(not set)')}"
    )
    lines.append(
        f"  turn_completed_at = {tool_context.state.get('turn_completed_at', '(not set yet — after callback runs after response)')}"
    )
    return "".join(lines)


root_agent = LlmAgent(
    name="callback_context_agent",
    model=MODEL,
    instruction=_INSTRUCTION,
    tools=[show_lifecycle],
    before_agent_callback=_before_agent,
    after_agent_callback=_after_agent,
    output_key="last_response",
)
