"""
EventActions.state_delta demo agent.

Subclasses BaseAgent and implements _run_async_impl directly.
Each yield Event(actions=EventActions(state_delta={...})) is the lowest-level
mechanism — everything else (output_key, ToolContext, CallbackContext) builds
on top of this.

Because this is a BaseAgent, wrapping in an LlmAgent lets the web UI work.
The outer LlmAgent routes "run workflow" to the inner WorkflowAgent tool.

Run with:
    adk web    (from adk_state_management/)
    adk run custom_state_delta_agent
"""

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.tool_context import ToolContext
from google.genai import types

MODEL = "gemini-2.0-flash"

_INSTRUCTION = """
You are an ADK EventActions.state_delta demo agent.

When the user says "run workflow" or asks to see state_delta in action,
call run_workflow_tool() which executes a multi-step BaseAgent that commits
state via manual EventActions.state_delta at each step.

After the workflow finishes, call show_workflow_state() to show what was committed.

Explain that EventActions.state_delta is the foundation all higher-level
state mechanisms are built on.
""".strip()


async def run_workflow_tool(tool_context: ToolContext) -> str:
    """Run the three-step WorkflowAgent and return a summary."""
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="workflow_inner", user_id="inner_user"
    )

    class WorkflowAgent(BaseAgent):
        async def _run_async_impl(self, ctx):
            yield Event(
                author=self.name,
                actions=EventActions(state_delta={"workflow_status": "started", "step": 1}),
            )
            step = ctx.session.state.get("step", 1)
            yield Event(
                author=self.name,
                actions=EventActions(
                    state_delta={
                        "step": step + 1,
                        "workflow_status": "processing",
                        "temp:intermediate": "raw_xyz",
                    }
                ),
            )
            step = ctx.session.state.get("step", 2)
            yield Event(
                author=self.name,
                actions=EventActions(
                    state_delta={
                        "step": step + 1,
                        "workflow_status": "completed",
                        "final_result": "processed_abc",
                    }
                ),
            )
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text="Workflow done.")],
                ),
            )

    runner = Runner(
        agent=WorkflowAgent(name="WorkflowAgent"),
        app_name="workflow_inner",
        session_service=session_service,
    )
    async for _ in runner.run_async(
        user_id="inner_user",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part.from_text(text="go")]),
    ):
        pass

    updated = await session_service.get_session(
        app_name="workflow_inner", user_id="inner_user", session_id=session.id
    )
    state = updated.state
    tool_context.state["wf_status"] = state.get("workflow_status", "")
    tool_context.state["wf_step"] = state.get("step", 0)
    tool_context.state["wf_result"] = state.get("final_result", "")
    tool_context.state["wf_temp"] = state.get("temp:intermediate")  # None — temp is gone

    return (
        f"Workflow finished.\n"
        f"  status        = {state.get('workflow_status')}\n"
        f"  step          = {state.get('step')}\n"
        f"  final_result  = {state.get('final_result')}\n"
        f"  temp:intermediate = {state.get('temp:intermediate')} (temp scope — gone)"
    )


def show_workflow_state(tool_context: ToolContext) -> str:
    """Show the workflow state keys saved by the last run_workflow_tool call."""
    lines = ["Workflow state (copied into outer session):"]
    lines.append(f"  wf_status = {tool_context.state.get('wf_status', '(not run yet)')!r}")
    lines.append(f"  wf_step   = {tool_context.state.get('wf_step', '(not run yet)')}")
    lines.append(f"  wf_result = {tool_context.state.get('wf_result', '(not run yet)')!r}")
    lines.append(f"  wf_temp   = {tool_context.state.get('wf_temp')!r}  ← None (temp scope discarded)")
    return "\n".join(lines)


root_agent = LlmAgent(
    name="custom_state_delta_agent",
    model=MODEL,
    instruction=_INSTRUCTION,
    tools=[run_workflow_tool, show_workflow_state],
    output_key="last_response",
)
