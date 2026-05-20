"""
Demo 08: ParallelAgent — concurrent fan-out with distinct state keys.

ParallelAgent runs sub-agents concurrently. All branches share the same
session.state, so each branch MUST write to a unique output_key.
Writing to the same key from multiple branches is a race condition.

Pattern:
    ParallelAgent (fan-out)  — 3 researchers, each → unique output_key
    SequentialAgent wraps    — runs ParallelAgent first, then a merger agent

The merger reads all three state keys via instruction templates and
synthesises them into a final report.

Run:
    GOOGLE_API_KEY=<key> python 08_parallel_agent.py
"""

import asyncio

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

MODEL = "gemini-2.0-flash"
APP_NAME = "parallel_demo"
USER_ID = "demo_user"


async def main() -> None:
    session_service = InMemorySessionService()

    # ── Fan-out: three independent researchers, each with a unique key ────
    # IMPORTANT: unique output_key per branch avoids race conditions.
    climate_researcher = LlmAgent(
        name="ClimateResearcher",
        model=MODEL,
        instruction="Write 2 sentences about the current state of climate change research.",
        output_key="climate_result",          # unique key
    )

    ai_researcher = LlmAgent(
        name="AIResearcher",
        model=MODEL,
        instruction="Write 2 sentences about recent advances in artificial intelligence.",
        output_key="ai_result",               # unique key
    )

    space_researcher = LlmAgent(
        name="SpaceResearcher",
        model=MODEL,
        instruction="Write 2 sentences about current space exploration missions.",
        output_key="space_result",            # unique key
    )

    parallel = ParallelAgent(
        name="ResearchFanOut",
        sub_agents=[climate_researcher, ai_researcher, space_researcher],
    )

    # ── Fan-in: merger reads all three keys from shared state ─────────────
    merger = LlmAgent(
        name="Merger",
        model=MODEL,
        instruction=(
            "Combine the three research summaries below into one cohesive paragraph "
            "(4-5 sentences). Do not introduce new facts.\n\n"
            "Climate: {climate_result}\n\n"
            "AI:      {ai_result}\n\n"
            "Space:   {space_result}"
        ),
        output_key="final_report",
    )

    # Root: fan-out then fan-in in sequence
    root = SequentialAgent(
        name="ResearchWorkflow",
        sub_agents=[parallel, merger],
    )

    runner = Runner(agent=root, app_name=APP_NAME, session_service=session_service)
    session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)

    async for _ in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text="Research all three topics.")]
        ),
    ):
        pass

    updated = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    print("=== Parallel research results ===\n")
    print(f"Climate:\n  {updated.state.get('climate_result')}\n")
    print(f"AI:\n  {updated.state.get('ai_result')}\n")
    print(f"Space:\n  {updated.state.get('space_result')}\n")
    print(f"=== Merged report ===\n{updated.state.get('final_report')}")


if __name__ == "__main__":
    asyncio.run(main())
