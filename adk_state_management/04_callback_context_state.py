"""
Demo 04: CallbackContext.state — lifecycle callbacks reading and writing state.

LlmAgent supports before_agent_callback and after_agent_callback hooks.
CallbackContext provides access to session.state with the same automatic
delta-tracking as ToolContext — mutations are committed without manual wiring.

  before_agent_callback(ctx) → Optional[Content]
      Runs before the LLM call.
      Return None  → let the agent run normally.
      Return Content → skip the agent, use that as the response.

  after_agent_callback(ctx) → Optional[Content]
      Runs after the LLM response.
      Return None    → pass the original response through.
      Return Content → replace the response with this.

We run three turns and watch turn_count, turn_started_at, and
turn_completed_at accumulate in session.state.

Run:
    GOOGLE_API_KEY=<key> python 04_callback_context_state.py
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

MODEL = "gemini-2.0-flash"
APP_NAME = "callback_demo"
USER_ID = "demo_user"


def before_agent(callback_context: CallbackContext) -> Optional[types.Content]:
    """Increment turn counter and stamp start time before each LLM call."""
    turn = callback_context.state.get("turn_count", 0) + 1
    callback_context.state["turn_count"] = turn
    callback_context.state["turn_started_at"] = datetime.now(timezone.utc).isoformat()
    print(f"  [before_agent] turn={turn}")
    return None  # proceed normally


def after_agent(callback_context: CallbackContext) -> Optional[types.Content]:
    """Stamp completion time after each LLM response."""
    callback_context.state["turn_completed_at"] = datetime.now(timezone.utc).isoformat()
    print(f"  [after_agent]  completed at {callback_context.state['turn_completed_at']}")
    return None  # pass response through unchanged


async def main() -> None:
    session_service = InMemorySessionService()

    agent = LlmAgent(
        name="TalkativeAgent",
        model=MODEL,
        instruction="Respond briefly to whatever the user says.",
        before_agent_callback=before_agent,
        after_agent_callback=after_agent,
    )

    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)

    for msg in ["First message.", "Second message.", "Third message."]:
        print(f"\n--- User: {msg} ---")
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session.id,
            new_message=types.Content(
                role="user", parts=[types.Part.from_text(text=msg)]
            ),
        ):
            if event.is_final_response() and event.content:
                for part in event.content.parts:
                    if part.text:
                        print(f"  Agent: {part.text.strip()}")

    updated = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    print(f"\nFinal state:")
    print(f"  turn_count        = {updated.state.get('turn_count')}")
    print(f"  turn_started_at   = {updated.state.get('turn_started_at')}")
    print(f"  turn_completed_at = {updated.state.get('turn_completed_at')}")


if __name__ == "__main__":
    asyncio.run(main())
