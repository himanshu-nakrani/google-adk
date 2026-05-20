"""
Demo 07: LoopAgent — iterative refinement with shared state.

LoopAgent repeatedly runs its sub-agents, passing the same InvocationContext
(and therefore the same session.state) across every iteration. Agents can
improve their output each cycle by reading what the previous cycle produced.

The loop terminates when:
  - max_iterations is reached, OR
  - a sub-agent yields an Event with actions.escalate=True

Cycle per iteration:
    Writer (LlmAgent)       →  writes/improves draft → output_key="draft"
    Critic (LlmAgent)       →  reviews draft         → output_key="critic_output"
    CriticParser (BaseAgent) →  parses score + feedback into state
    QualityChecker (BaseAgent) → escalates when score >= 8

Run:
    GOOGLE_API_KEY=<key> python 07_loop_agent.py
"""

import asyncio

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

MODEL = "gemini-2.0-flash"
APP_NAME = "loop_demo"
USER_ID = "demo_user"
PASS_SCORE = 8


class CriticParser(BaseAgent):
    """Parse the Critic's raw text output into structured state keys."""

    async def _run_async_impl(self, ctx):
        raw = ctx.session.state.get("critic_output", "SCORE: 5\nFEEDBACK: Keep improving.")
        score, feedback = 5, "Keep improving."
        for line in raw.splitlines():
            line = line.strip()
            if line.upper().startswith("SCORE:"):
                try:
                    score = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif line.upper().startswith("FEEDBACK:"):
                feedback = line.split(":", 1)[1].strip()

        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={"quality_score": score, "critic_feedback": feedback}
            ),
        )


class QualityChecker(BaseAgent):
    """Stop the loop when quality_score >= PASS_SCORE; otherwise continue."""

    async def _run_async_impl(self, ctx):
        score = ctx.session.state.get("quality_score", 0)
        iteration = ctx.session.state.get("iteration", 0) + 1
        should_stop = score >= PASS_SCORE
        print(f"  [QualityChecker] iteration={iteration}, score={score}, stop={should_stop}")

        yield Event(
            author=self.name,
            actions=EventActions(
                escalate=should_stop,
                state_delta={"iteration": iteration},
            ),
        )


async def main() -> None:
    session_service = InMemorySessionService()

    writer = LlmAgent(
        name="Writer",
        model=MODEL,
        instruction=(
            "You are a writer. Write or improve a short paragraph (3-4 sentences) "
            "about machine learning. "
            "Current draft (empty on first run): {draft}\n"
            "Critic feedback (empty on first run): {critic_feedback}\n\n"
            "If feedback exists, address it. Output ONLY the paragraph text."
        ),
        output_key="draft",
    )

    critic = LlmAgent(
        name="Critic",
        model=MODEL,
        instruction=(
            "You are a strict writing critic. Review this paragraph:\n\n{draft}\n\n"
            "Reply with EXACTLY two lines and nothing else:\n"
            "SCORE: <integer 1-10>\n"
            "FEEDBACK: <one sentence of constructive feedback>"
        ),
        output_key="critic_output",
    )

    loop = LoopAgent(
        name="RefinementLoop",
        sub_agents=[
            writer,
            critic,
            CriticParser(name="CriticParser"),
            QualityChecker(name="QualityChecker"),
        ],
        max_iterations=6,
    )

    runner = Runner(agent=loop, app_name=APP_NAME, session_service=session_service)

    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        state={"draft": "", "critic_feedback": "", "quality_score": 0, "iteration": 0},
    )

    async for _ in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text="Start iterative refinement.")],
        ),
    ):
        pass

    updated = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    print(f"\n=== Refinement complete ===")
    print(f"Iterations run : {updated.state.get('iteration')}")
    print(f"Final score    : {updated.state.get('quality_score')}")
    print(f"Final feedback : {updated.state.get('critic_feedback')}")
    print(f"\nFinal draft:\n{updated.state.get('draft')}")


if __name__ == "__main__":
    asyncio.run(main())
