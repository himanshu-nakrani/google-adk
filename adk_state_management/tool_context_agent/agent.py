"""
ToolContext.state demo agent.

Shows that tool functions can read and write session.state via the
injected ToolContext parameter. ADK tracks mutations as a state_delta
automatically — no EventActions needed.

Run with:
    adk web    (from adk_state_management/)
    adk run tool_context_agent
"""

from google.adk.agents import LlmAgent
from google.adk.tools.tool_context import ToolContext

MODEL = "gemini-2.0-flash"

_INSTRUCTION = """
You are an ADK ToolContext demo agent.

You have three tools that read/write session.state automatically:
  • search(query)  – simulates a search, tracks call count and last query
  • calculate(expr) – simulates a calculation, tracks call count
  • show_stats()   – shows accumulated counters from state

Every tool mutation is committed by ADK as a state_delta without any
manual EventActions wiring. Demonstrate this by calling tools and then
showing the updated stats.
""".strip()


def search(query: str, tool_context: ToolContext) -> str:
    """Simulate a web search. Increments search_count and records last_query."""
    count = tool_context.state.get("search_count", 0) + 1
    tool_context.state["search_count"] = count
    tool_context.state["last_query"] = query
    return f"Mock results for {query!r}: [result_1, result_2, result_3] (call #{count})"


def calculate(expression: str, tool_context: ToolContext) -> str:
    """Simulate a calculation. Increments calc_count."""
    count = tool_context.state.get("calc_count", 0) + 1
    tool_context.state["calc_count"] = count
    tool_context.state["last_expression"] = expression
    try:
        result = eval(expression, {"__builtins__": {}})  # noqa: S307
    except Exception as e:
        result = f"error: {e}"
    return f"{expression} = {result}  (calc call #{count})"


def show_stats(tool_context: ToolContext) -> str:
    """Show all tool-usage counters from session state."""
    lines = ["Tool usage stats from session.state:"]
    lines.append(f"  search_count    = {tool_context.state.get('search_count', 0)}")
    lines.append(f"  last_query      = {tool_context.state.get('last_query', '(none)')!r}")
    lines.append(f"  calc_count      = {tool_context.state.get('calc_count', 0)}")
    lines.append(f"  last_expression = {tool_context.state.get('last_expression', '(none)')!r}")
    return "\n".join(lines)


root_agent = LlmAgent(
    name="tool_context_agent",
    model=MODEL,
    instruction=_INSTRUCTION,
    tools=[search, calculate, show_stats],
    output_key="last_response",
)
