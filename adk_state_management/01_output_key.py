"""
Demo 01: output_key — simplest way to save an LLM response into session.state.

LlmAgent.output_key automatically stores the agent's final text response
into session.state[output_key] after the turn completes. No EventActions
wiring needed — ADK handles the state_delta internally.

Run:
    GOOGLE_API_KEY=<key> python 01_output_key.py
"""

import asyncio

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

MODEL = "gemini-2.0-flash"
APP_NAME = "output_key_demo"
USER_ID = "demo_user"


async def main() -> None:
    session_service = InMemorySessionService()

    # output_key="greeting" → after the run, session.state["greeting"] holds
    # whatever text the LLM produced.
    greeter = LlmAgent(
        name="Greeter",
        model=MODEL,
        instruction="Greet the user warmly in exactly one sentence.",
        output_key="greeting",
    )

    runner = Runner(
        agent=greeter,
        app_name=APP_NAME,
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
    )
    print(f"Before run — state: {session.state}")

    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text="Hello!")],
        ),
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if part.text:
                    print(f"Agent response: {part.text}")

    updated = await session_service.get_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session.id,
    )
    print(f"\nAfter run — state: {updated.state}")
    print(f"  session.state['greeting'] = {updated.state.get('greeting')}")


if __name__ == "__main__":
    asyncio.run(main())
