from google.adk.agents import LlmAgent
from google.adk.tools.tool_context import ToolContext

MODEL = "gemini-2.0-flash"

_INSTRUCTION = """
You are a friendly ADK State Management tutor. You help users explore ADK's
session state system through live demonstration.

You have four state tools:
  • remember(key, value) – store a value in session state
  • recall(key)          – retrieve a stored value
  • list_memory()        – show all keys currently in state
  • forget(key)          – delete a key from state

State prefix cheat-sheet:
  | Prefix | Scope                       | Persists? |
  |--------|-----------------------------|-----------|
  | (none) | this session                | yes       |
  | temp:  | this invocation only        | no        |
  | user:  | all sessions for this user  | yes       |
  | app:   | all users & sessions        | yes       |

Demonstrate concepts live. Show before-and-after so users can see what changed.
Note: output_key="last_response" means every reply is auto-saved to state.
""".strip()


def remember(key: str, value: str, tool_context: ToolContext) -> str:
    """Store value under key in session state. Increments remember_count."""
    tool_context.state[key] = value
    count = tool_context.state.get("remember_count", 0) + 1
    tool_context.state["remember_count"] = count
    return f"Stored state[{key!r}] = {value!r}. (remember_count is now {count})"


def recall(key: str, tool_context: ToolContext) -> str:
    """Retrieve the value stored under key from session state."""
    value = tool_context.state.get(key)
    count = tool_context.state.get("recall_count", 0) + 1
    tool_context.state["recall_count"] = count
    if value is None:
        return f"No value found for key {key!r}. (recall_count is now {count})"
    return f"state[{key!r}] = {value!r}  (recall_count is now {count})"


def list_memory(tool_context: ToolContext) -> str:
    """List all key/value pairs currently in session state."""
    state = tool_context.state
    if not state:
        return "Session state is currently empty."
    lines = ["Current session state:"]
    for k, v in sorted(state.items()):
        lines.append(f"  {k!r}: {v!r}")
    return "\n".join(lines)


def forget(key: str, tool_context: ToolContext) -> str:
    """Remove key from session state (sets to None = ADK deletion signal)."""
    if key not in tool_context.state:
        return f"Key {key!r} was not in state — nothing to forget."
    old_value = tool_context.state[key]
    tool_context.state[key] = None
    return f"Forgot key {key!r} (it previously held {old_value!r})."


root_agent = LlmAgent(
    name="state_demo_agent",
    model=MODEL,
    instruction=_INSTRUCTION,
    tools=[remember, recall, list_memory, forget],
    output_key="last_response",
)
