"""
State scope/prefix demo agent.

Demonstrates all four ADK state scopes via tools:
  (no prefix) → session scope  (persists in the session)
  temp:        → invocation scope (discarded after this runner call)
  user:        → user scope   (shared across sessions for this user)
  app:         → app scope    (shared across all users and sessions)

Run with:
    adk web    (from adk_state_management/)
    adk run state_prefixes_agent
"""

from google.adk.agents import LlmAgent
from google.adk.tools.tool_context import ToolContext

MODEL = "gemini-2.0-flash"

_INSTRUCTION = """
You are an ADK state-scope tutor. You demonstrate the four key prefixes.

State prefix cheat-sheet:
  | Prefix | Scope                       | Persists? |
  |--------|-----------------------------|-----------|
  | (none) | this session                | yes       |
  | temp:  | this invocation only        | no        |
  | user:  | all sessions for this user  | yes       |
  | app:   | all users & sessions        | yes       |

Tools you have:
  write_scoped(key, value) – write a value (key must include prefix if desired)
  read_key(key)            – read a single key
  dump_state()             – show all current state keys
  demo_all_scopes()        – write one key per scope, then show state

Walk the user through each scope and explain what persists vs. what vanishes.
""".strip()


def write_scoped(key: str, value: str, tool_context: ToolContext) -> str:
    """Write value under key. Prefix the key yourself (e.g. temp:foo, user:bar)."""
    tool_context.state[key] = value
    return f"Wrote state[{key!r}] = {value!r}"


def read_key(key: str, tool_context: ToolContext) -> str:
    """Read a single key from state."""
    val = tool_context.state.get(key)
    if val is None:
        return f"state[{key!r}] is not set (or was temp-scoped and discarded)."
    return f"state[{key!r}] = {val!r}"


def dump_state(tool_context: ToolContext) -> str:
    """List all key/value pairs in session state."""
    state = tool_context.state
    if not state:
        return "Session state is empty."
    lines = ["Current session state:"]
    for k, v in sorted(state.items()):
        lines.append(f"  {k!r}: {v!r}")
    return "\n".join(lines)


def demo_all_scopes(tool_context: ToolContext) -> str:
    """Write one key per scope then return a summary."""
    tool_context.state["session_demo"] = "I am session-scoped"
    tool_context.state["temp:scratch"] = "I am temp-scoped (will vanish)"
    tool_context.state["user:preferred_language"] = "English"
    tool_context.state["app:feature_flag"] = True
    return (
        "Wrote four keys:\n"
        "  session_demo              → session scope\n"
        "  temp:scratch              → invocation scope (discarded after this call)\n"
        "  user:preferred_language   → user scope\n"
        "  app:feature_flag          → app scope\n"
        "Call dump_state() to see what survived."
    )


root_agent = LlmAgent(
    name="state_prefixes_agent",
    model=MODEL,
    instruction=_INSTRUCTION,
    tools=[write_scoped, read_key, dump_state, demo_all_scopes],
    output_key="last_response",
)
