"""
Demo 02: State scopes and key prefixes.

ADK recognises four state scopes via key prefix:

  (no prefix)   session scope  — persisted in the session by SessionService
  temp:          invocation scope — NOT persisted; discarded after this runner call
  user:          user scope     — shared across all sessions for this user
  app:           app scope      — shared across all users and all sessions

We write all four in a single state_delta via a custom BaseAgent, then
re-fetch the session to see which keys survived.

Run:
    python 02_state_prefixes.py
"""

import asyncio

from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

APP_NAME = "state_prefix_demo"
USER_ID = "demo_user"


class StateScopeAgent(BaseAgent):
    """Writes one key per scope and yields a final text response."""

    async def _run_async_impl(self, ctx):
        # Single state_delta covering all four scopes
        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "session_key": "I am session-scoped",
                    "temp:scratch": "I am temp-scoped (discarded after this invocation)",
                    "user:preferred_language": "English",
                    "app:feature_flag_v2": True,
                }
            ),
        )

        yield Event(
            author=self.name,
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text="State written across all four scopes.")],
            ),
        )


async def main() -> None:
    session_service = InMemorySessionService()
    agent = StateScopeAgent(name="StateScopeAgent")
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)

    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
    print(f"Before run — state: {session.state}")

    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text="Go")]
        ),
    ):
        if event.actions and event.actions.state_delta:
            print(f"  state_delta: {event.actions.state_delta}")

    updated = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    print(f"\nAfter run — state: {updated.state}")
    print("\nKey-by-key:")
    print(f"  session_key             = {updated.state.get('session_key')!r}")
    print(f"  temp:scratch            = {updated.state.get('temp:scratch')!r}  ← None (invocation-local)")
    print(f"  user:preferred_language = {updated.state.get('user:preferred_language')!r}")
    print(f"  app:feature_flag_v2     = {updated.state.get('app:feature_flag_v2')!r}")


if __name__ == "__main__":
    asyncio.run(main())
