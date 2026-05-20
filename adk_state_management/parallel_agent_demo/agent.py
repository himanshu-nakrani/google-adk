"""
ParallelAgent concurrent fan-out demo.

ParallelAgent runs sub-agents concurrently. All branches share session.state,
so each branch must write to a unique output_key. A merger agent in a wrapping
SequentialAgent reads all three keys and synthesises a final report.

Fan-out:  ClimateResearcher → climate_result
          AIResearcher      → ai_result
          SpaceResearcher   → space_result
Fan-in:   Merger            → final_report

Use run_research(topics) to trigger the workflow and show_report() to read results.

Run with:
    adk web    (from adk_state_management/)
    adk run parallel_agent_demo
"""

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.tool_context import ToolContext
from google.genai import types

MODEL = "gemini-2.0-flash"

_INSTRUCTION = """
You are a ParallelAgent fan-out demo agent for ADK.

You coordinate three parallel researchers and a merger:
  (parallel) ClimateResearcher  → climate_result
  (parallel) AIResearcher       → ai_result
  (parallel) SpaceResearcher    → space_result
  (sequential merge) Merger     → final_report

Tools:
  run_research()  – execute the parallel workflow
  show_report()   – display individual results and merged report from state

Explain that all parallel branches share session.state, so each branch MUST
write to a unique key. Warn that writing to the same key from two branches
is a race condition.
""".strip()


async def run_research(tool_context: ToolContext) -> str:
    """Run the parallel research workflow. Returns a brief status."""
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name="par_inner", user_id="inner_user")

    climate = LlmAgent(
        name="ClimateResearcher",
        model=MODEL,
        instruction="Write 2 sentences about the current state of climate change research.",
        output_key="climate_result",
    )
    ai = LlmAgent(
        name="AIResearcher",
        model=MODEL,
        instruction="Write 2 sentences about recent advances in artificial intelligence.",
        output_key="ai_result",
    )
    space = LlmAgent(
        name="SpaceResearcher",
        model=MODEL,
        instruction="Write 2 sentences about current space exploration missions.",
        output_key="space_result",
    )
    merger = LlmAgent(
        name="Merger",
        model=MODEL,
        instruction=(
            "Combine the three research summaries into one cohesive paragraph (4-5 sentences). "
            "Do not introduce new facts.\n\n"
            "Climate: {climate_result}\n\n"
            "AI: {ai_result}\n\n"
            "Space: {space_result}"
        ),
        output_key="final_report",
    )
    root = SequentialAgent(
        name="ResearchWorkflow",
        sub_agents=[
            ParallelAgent(name="FanOut", sub_agents=[climate, ai, space]),
            merger,
        ],
    )
    runner = Runner(agent=root, app_name="par_inner", session_service=session_service)
    async for _ in runner.run_async(
        user_id="inner_user",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part.from_text(text="research")]),
    ):
        pass

    updated = await session_service.get_session(
        app_name="par_inner", user_id="inner_user", session_id=session.id
    )
    tool_context.state["par_climate"] = updated.state.get("climate_result", "")
    tool_context.state["par_ai"] = updated.state.get("ai_result", "")
    tool_context.state["par_space"] = updated.state.get("space_result", "")
    tool_context.state["par_report"] = updated.state.get("final_report", "")
    return "Research complete. Call show_report() to see the results."


def show_report(tool_context: ToolContext) -> str:
    """Display the parallel research results and merged report from state."""
    return (
        f"Climate:\n  {tool_context.state.get('par_climate', '(not run)')}\n\n"
        f"AI:\n  {tool_context.state.get('par_ai', '(not run)')}\n\n"
        f"Space:\n  {tool_context.state.get('par_space', '(not run)')}\n\n"
        f"=== Merged Report ===\n{tool_context.state.get('par_report', '(not run yet)')}"
    )


root_agent = LlmAgent(
    name="parallel_agent_demo",
    model=MODEL,
    instruction=_INSTRUCTION,
    tools=[run_research, show_report],
    output_key="last_response",
)
