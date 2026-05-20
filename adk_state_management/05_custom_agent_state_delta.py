"""
Demo 05: Custom BaseAgent with manual EventActions.state_delta.

When you subclass BaseAgent and implement _run_async_impl, you control the
event stream directly. To commit state changes you must yield Event objects
whose actions.state_delta contains the key/value pairs to store.

This is the lowest-level, most explicit state mechanism in ADK and is the
foundation that output_key, ToolContext, and CallbackContext all build on top of.

Pattern: a three-step workflow where each step commits state atomically and
the next step reads what the previous step wrote.

Run:
    python 05_custom_agent_state_delta.py
"""

import asyncio

from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

APP_NAME = "custom_agent_demo"
USER_ID = "demo_user"


class WorkflowAgent(BaseAgent):
    """
    Three-step workflow.  Each step:
      1. reads the state committed so far via ctx.session.state
      2. yields an Event carrying its own state_delta
    The Runner calls SessionService.append_event() after each yield,
    so the next resume point sees the newly committed values.
    """

    async def _run_async_impl(self, ctx):
        # ── Step 1: initialise ────────────────────────────────────────────
        print("  step 1: initialising")
        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "workflow_status": "started",
                    "step": 1,
                }
            ),
        )

        # ── Step 2: process (reads step committed above) ──────────────────
        current_step = ctx.session.state.get("step", 0)
        print(f"  step 2: processing (read step={current_step} from state)")
        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "step": current_step + 1,
                    "workflow_status": "processing",
                    "temp:intermediate_result": "raw_data_123",   # invocation-local
                }
            ),
        )

        # ── Step 3: complete ──────────────────────────────────────────────
        current_step = ctx.session.state.get("step", 0)
        print(f"  step 3: completing  (read step={current_step} from state)")
        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "step": current_step + 1,
                    "workflow_status": "completed",
                    "final_result": "processed_data_456",
                }
            ),
        )

        # ── Final text response ───────────────────────────────────────────
        yield Event(
            author=self.name,
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text="Workflow complete. See session.state for results.")],
            ),
        )


async def main() -> None:
    session_service = InMemorySessionService()
    agent = WorkflowAgent(name="WorkflowAgent")
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)

    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
    print(f"Before run — state: {session.state}\n")

    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text="Run workflow")]
        ),
    ):
        if event.actions and event.actions.state_delta:
            print(f"  → state_delta committed: {event.actions.state_delta}")
        if event.is_final_response() and event.content:
            for part in event.content.parts:
                if part.text:
                    print(f"\nAgent: {part.text}")

    updated = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    print(f"\nFinal state: {updated.state}")
    print(f"  workflow_status          = {updated.state.get('workflow_status')!r}")
    print(f"  step                     = {updated.state.get('step')}")
    print(f"  final_result             = {updated.state.get('final_result')!r}")
    print(f"  temp:intermediate_result = {updated.state.get('temp:intermediate_result')!r}  ← None (temp scope)")


if __name__ == "__main__":
    asyncio.run(main())
