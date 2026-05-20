"""
LoopAgent iterative-refinement demo.

LoopAgent repeats its sub-agents, preserving session.state across every
iteration. A QualityChecker agent escalates (actions.escalate=True) once
quality_score >= 8, stopping the loop early.

Cycle per iteration:
    Writer → Critic → CriticParser → QualityChecker

Use start_refinement() to trigger the loop and show_results() to see the
final draft, score, and how many iterations it took.

Run with:
    adk web    (from adk_state_management/)
    adk run loop_agent_demo
"""

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.tool_context import ToolContext
from google.genai import types

MODEL = "gemini-2.0-flash"
PASS_SCORE = 8

_INSTRUCTION = """
You are a LoopAgent demo agent for ADK.

You coordinate an iterative writing-refinement loop:
  Writer → Critic → CriticParser → QualityChecker

The loop keeps running until the critic gives a score >= 8 or max 6 iterations.

Tools:
  start_refinement(topic) – run the loop on a topic and return the final draft
  show_results()          – show draft, score, iteration count from state

Explain how LoopAgent preserves session.state across iterations, and how
the QualityChecker uses escalate=True to stop the loop.
""".strip()


class _CriticParser(BaseAgent):
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
            actions=EventActions(state_delta={"quality_score": score, "critic_feedback": feedback}),
        )


class _QualityChecker(BaseAgent):
    async def _run_async_impl(self, ctx):
        score = ctx.session.state.get("quality_score", 0)
        iteration = ctx.session.state.get("iteration", 0) + 1
        should_stop = score >= PASS_SCORE
        yield Event(
            author=self.name,
            actions=EventActions(escalate=should_stop, state_delta={"iteration": iteration}),
        )


async def start_refinement(topic: str, tool_context: ToolContext) -> str:
    """Run the iterative refinement loop on topic. Returns the final draft."""
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="loop_inner",
        user_id="inner_user",
        state={
            "topic": topic,
            "draft": "",
            "critic_feedback": "",
            "quality_score": 0,
            "iteration": 0,
        },
    )

    writer = LlmAgent(
        name="Writer",
        model=MODEL,
        instruction=(
            "Write or improve a short paragraph (3-4 sentences) about {topic}. "
            "Current draft: {draft}\n"
            "Critic feedback: {critic_feedback}\n"
            "If feedback exists, address it. Output ONLY the paragraph text."
        ),
        output_key="draft",
    )
    critic = LlmAgent(
        name="Critic",
        model=MODEL,
        instruction=(
            "Review this paragraph:\n\n{draft}\n\n"
            "Reply with EXACTLY two lines:\n"
            "SCORE: <integer 1-10>\n"
            "FEEDBACK: <one sentence of constructive feedback>"
        ),
        output_key="critic_output",
    )
    loop = LoopAgent(
        name="RefinementLoop",
        sub_agents=[writer, critic, _CriticParser(name="CriticParser"), _QualityChecker(name="QualityChecker")],
        max_iterations=6,
    )
    runner = Runner(agent=loop, app_name="loop_inner", session_service=session_service)
    async for _ in runner.run_async(
        user_id="inner_user",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part.from_text(text="start")]),
    ):
        pass

    updated = await session_service.get_session(
        app_name="loop_inner", user_id="inner_user", session_id=session.id
    )
    tool_context.state["loop_draft"] = updated.state.get("draft", "")
    tool_context.state["loop_score"] = updated.state.get("quality_score", 0)
    tool_context.state["loop_iterations"] = updated.state.get("iteration", 0)
    tool_context.state["loop_feedback"] = updated.state.get("critic_feedback", "")

    return (
        f"Loop finished after {updated.state.get('iteration')} iterations.\n"
        f"Final score: {updated.state.get('quality_score')}\n"
        f"Call show_results() to see the draft."
    )


def show_results(tool_context: ToolContext) -> str:
    """Show the loop results from session state."""
    return (
        f"Iterations : {tool_context.state.get('loop_iterations', '(not run)')}\n"
        f"Score      : {tool_context.state.get('loop_score', '(not run)')}\n"
        f"Feedback   : {tool_context.state.get('loop_feedback', '(not run)')}\n\n"
        f"Draft:\n{tool_context.state.get('loop_draft', '(not run yet)')}"
    )


root_agent = LlmAgent(
    name="loop_agent_demo",
    model=MODEL,
    instruction=_INSTRUCTION,
    tools=[start_refinement, show_results],
    output_key="last_response",
)
