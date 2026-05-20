"""
Demo 03: ToolContext.state — tools reading and writing session state.

Any ADK tool function can declare a ToolContext parameter. ADK automatically
injects it at call time. Mutations to tool_context.state are tracked and
committed as a state_delta on the resulting event — no manual EventActions needed.

We build a "search" tool that increments a call counter and records the
last query each time it is invoked.

Run:
    GOOGLE_API_KEY=<key> python 03_tool_context_state.py
"""

import asyncio

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.tool_context import ToolContext
from google.genai import types

MODEL = "gemini-2.0-flash"
APP_NAME = "tool_context_demo"
USER_ID = "demo_user"


def search_web(query: str, tool_context: ToolContext) -> str:
    """Simulate a web search. Tracks call count and last query in state."""
    count = tool_context.state.get("search_count", 0)
    tool_context.state["search_count"] = count + 1       # ADK commits this delta
    tool_context.state["last_query"] = query             # ADK commits this delta
    return f"Mock results for '{query}': [result_1, result_2, result_3]"


async def main() -> None:
    session_service = InMemorySessionService()

    agent = LlmAgent(
        name="Researcher",
        model=MODEL,
        instruction=(
            "You are a research assistant. Use search_web to find information. "
            "Call it exactly twice with different queries."
        ),
        tools=[search_web],
    )

    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
    print(f"Before run — state: {session.state}")

    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text="Research quantum computing and neural networks.")],
        ),
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if part.text:
                    print(f"\nAgent: {part.text}")

    updated = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    print(f"\nAfter run — state: {updated.state}")
    print(f"  search_count = {updated.state.get('search_count')}")
    print(f"  last_query   = {updated.state.get('last_query')!r}")


if __name__ == "__main__":
    asyncio.run(main())
