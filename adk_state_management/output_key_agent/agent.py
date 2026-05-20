"""
output_key demo agent.

Every reply from this LlmAgent is automatically saved into
session.state["last_response"] via output_key. No EventActions wiring needed.

Run with:
    adk web    (from adk_state_management/)
    adk run output_key_agent
"""

from google.adk.agents import LlmAgent
from google.adk.tools.tool_context import ToolContext

MODEL = "gemini-2.0-flash"

_INSTRUCTION = """
You are a friendly assistant demonstrating ADK output_key.

Every response you give is automatically saved into session.state["last_response"]
because this agent was created with output_key="last_response".

When the user asks you anything:
1. Answer the question.
2. Remind them that your response is being auto-saved to state["last_response"].
Use show_state() to prove it.
""".strip()


def show_state(tool_context: ToolContext) -> str:
    """Show the current value of last_response in session state."""
    val = tool_context.state.get("last_response")
    if val is None:
        return "state[last_response] is not set yet (this is the first turn)."
    return f"state[last_response] = {val!r}"


root_agent = LlmAgent(
    name="output_key_agent",
    model=MODEL,
    instruction=_INSTRUCTION,
    tools=[show_state],
    output_key="last_response",
)
