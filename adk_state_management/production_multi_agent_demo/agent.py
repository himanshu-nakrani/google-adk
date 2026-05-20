"""
Production Multi-Agent Support Orchestration & Auditing Agent.

This interactive agent demonstrates how to manage session and user state in a multi-agent system:
- Supervisor-based support dispatching based on `user:tier` state.
- Chronological audit logging recorded directly in `session.state`.
- Strict guardrails validating output states prior to resolution.
- Live modification of persistent user profiles.

Run using:
    adk run production_multi_agent_demo
    adk web   (then open UI and select production_multi_agent_demo)
"""

import datetime
from typing import Any, Dict, List

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.tool_context import ToolContext
from google.genai import types

MODEL = "gemini-2.0-flash"

_INSTRUCTION = """
You are a Production Multi-Agent Support Coordinator and Orchestrator.
Your goal is to guide the user in exploring how enterprise state management, dynamic routing, and audit logs are built in Google ADK.

Explain that you have the following state tools available:
  1. set_user_tier(tier)       – Update customer's tier in cross-session `user:tier` scope (Premium vs. Standard).
  2. run_support_ticket(ticket) – Execute the multi-agent pipeline: Supervisor -> Support Agents -> Guardrails.
  3. view_audit_trail()        – Inspect the chronological transition log saved in state.
  4. clear_user_profile()      – Deletes user profile keys (`user:name` and `user:tier`) to simulate a first-time visitor.

Be detailed and informative. Explain exactly how the states flow, highlighting that:
  - The Supervisor reads `user:tier` to assign either the `PremiumSupport` or `StandardSupport` agent.
  - The Guardrail agent verifies that the resulting state contains valid resolution flags.
  - All logs are dynamically preserved in `session.state["audit_trail"]`.
""".strip()


def log_audit(state: Dict[str, Any], message: str) -> List[str]:
    """Helper to append an audit log entry in the session state."""
    trail = list(state.get("audit_trail", []))
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    trail.append(f"[{timestamp}] {message}")
    return trail


# Define inner agents for the support ticket execution
class SupervisorAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        user_name = ctx.session.state.get("user:name")
        user_tier = ctx.session.state.get("user:tier")
        
        state_delta = {}
        if not user_name:
            user_name = "Jane Doe"
            user_tier = "Premium"
            state_delta["user:name"] = user_name
            state_delta["user:tier"] = user_tier

        route_target = "PremiumQueue" if user_tier == "Premium" else "StandardQueue"
        state_delta["route_target"] = route_target
        
        audit_msg = f"Supervisor: Routed user '{user_name}' ({user_tier} tier) to support queue: '{route_target}'."
        state_delta["audit_trail"] = log_audit(ctx.session.state, audit_msg)
        
        yield Event(
            author=self.name,
            actions=EventActions(state_delta=state_delta),
        )


class PremiumSupportAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        route = ctx.session.state.get("route_target")
        if route != "PremiumQueue":
            return
        
        state_delta = {
            "resolution_status": "RESOLVED_PREMIUM",
            "assigned_agent": "Senior Engineer Xavier",
            "resolution_notes": "Premium ticket processed. Staging environment debugged and resolved connection timeout.",
        }
        audit_msg = "PremiumSupport: Ticket resolved by Senior Engineer Xavier. High-priority SLAs satisfied."
        state_delta["audit_trail"] = log_audit(ctx.session.state, audit_msg)
        
        yield Event(
            author=self.name,
            actions=EventActions(state_delta=state_delta)
        )


class StandardSupportAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        route = ctx.session.state.get("route_target")
        if route != "StandardQueue":
            return
        
        state_delta = {
            "resolution_status": "RESOLVED_STANDARD",
            "assigned_agent": "Support Desk AutoBot",
            "resolution_notes": "Standard ticket processed. Auto-diagnostics complete. Guidelines sent.",
        }
        audit_msg = "StandardSupport: Ticket resolved by Support Desk AutoBot."
        state_delta["audit_trail"] = log_audit(ctx.session.state, audit_msg)
        
        yield Event(
            author=self.name,
            actions=EventActions(state_delta=state_delta)
        )


class GuardrailAgent(BaseAgent):
    async def _run_async_impl(self, ctx):
        res_status = ctx.session.state.get("resolution_status")
        route_target = ctx.session.state.get("route_target")
        
        errors = []
        if not res_status:
            errors.append("Missing resolution_status.")
        if not route_target:
            errors.append("Missing route_target.")
        if route_target == "PremiumQueue" and res_status != "RESOLVED_PREMIUM":
            errors.append("Premium route resolved under non-premium status.")
            
        state_delta = {}
        if errors:
            state_delta["guardrail_passed"] = False
            audit_msg = f"Guardrail: State validation FAILED: {', '.join(errors)}"
            state_delta["audit_trail"] = log_audit(ctx.session.state, audit_msg)
            yield Event(
                author=self.name,
                actions=EventActions(escalate=True, state_delta=state_delta)
            )
        else:
            state_delta["guardrail_passed"] = True
            audit_msg = "Guardrail: State validation PASSED. Ready for workflow archive."
            state_delta["audit_trail"] = log_audit(ctx.session.state, audit_msg)
            yield Event(
                author=self.name,
                actions=EventActions(state_delta=state_delta)
            )


# Tools exposed to the LLM agent
def set_user_tier(tier: str, tool_context: ToolContext) -> str:
    """
    Set the user's tier in durable cross-session state (either 'Premium' or 'Standard').
    """
    normalized_tier = tier.strip().capitalize()
    if normalized_tier not in ["Premium", "Standard"]:
        return "Invalid tier selection. Please select either 'Premium' or 'Standard'."
        
    tool_context.state["user:tier"] = normalized_tier
    if not tool_context.state.get("user:name"):
        tool_context.state["user:name"] = "Jane Doe"
        
    audit_msg = f"Management: Updated user tier to '{normalized_tier}'."
    tool_context.state["audit_trail"] = log_audit(tool_context.state, audit_msg)
    
    return f"Success: Set user:tier = '{normalized_tier}' and user:name = '{tool_context.state.get('user:name')}'."


async def run_support_ticket(ticket_details: str, tool_context: ToolContext) -> str:
    """
    Runs the multi-agent customer support dispatch pipeline on the current ticket details.
    """
    # Ensure profile exists in outer state
    user_name = tool_context.state.get("user:name")
    user_tier = tool_context.state.get("user:tier")
    if not user_name:
        user_name = "Jane Doe"
        user_tier = "Premium"
        tool_context.state["user:name"] = user_name
        tool_context.state["user:tier"] = user_tier
        
    # Build inner multi-agent system
    support_pipeline = SequentialAgent(
        name="ProductionSupportPipeline",
        sub_agents=[
            SupervisorAgent(name="Supervisor"),
            PremiumSupportAgent(name="PremiumSupport"),
            StandardSupportAgent(name="StandardSupport"),
            GuardrailAgent(name="Guardrail"),
        ]
    )
    
    session_service = InMemorySessionService()
    runner = Runner(
        agent=support_pipeline,
        app_name="prod_support_inner",
        session_service=session_service,
    )
    
    # Seed the inner runner session with our current outer states
    session = await session_service.create_session(
        app_name="prod_support_inner",
        user_id="demo_user",
        state=dict(tool_context.state)
    )
    
    # Run pipeline
    async for _ in runner.run_async(
        user_id="demo_user",
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=ticket_details)]
        )
    ):
        pass
        
    # Copy all committed state values back to the outer agent's tool_context.state
    updated = await session_service.get_session(
        app_name="prod_support_inner",
        user_id="demo_user",
        session_id=session.id
    )
    for k, v in updated.state.items():
        tool_context.state[k] = v
        
    res_status = tool_context.state.get("resolution_status")
    assigned = tool_context.state.get("assigned_agent")
    passed = tool_context.state.get("guardrail_passed")
    
    return (
        f"Pipeline Run Complete:\n"
        f"  - Customer Name: {user_name}\n"
        f"  - Customer Tier: {user_tier}\n"
        f"  - Route Selected: {tool_context.state.get('route_target')}\n"
        f"  - Assigned Agent: {assigned}\n"
        f"  - Resolution Status: {res_status}\n"
        f"  - Guardrail Passed: {passed}"
    )


def view_audit_trail(tool_context: ToolContext) -> str:
    """
    Displays the chronological audit trail from state showing agent transitions.
    """
    trail = tool_context.state.get("audit_trail", [])
    if not trail:
        return "No audit logs have been recorded in state yet."
        
    lines = ["=== Chronological Audit Trail ==="]
    for idx, log in enumerate(trail, 1):
        lines.append(f" {idx}. {log}")
    return "\n".join(lines)


def clear_user_profile(tool_context: ToolContext) -> str:
    """
    Deletes the customer's profile keys from state, simulating a fresh first-time user.
    """
    old_name = tool_context.state.get("user:name")
    old_tier = tool_context.state.get("user:tier")
    
    tool_context.state["user:name"] = None
    tool_context.state["user:tier"] = None
    tool_context.state["route_target"] = None
    tool_context.state["resolution_status"] = None
    tool_context.state["assigned_agent"] = None
    tool_context.state["resolution_notes"] = None
    tool_context.state["guardrail_passed"] = None
    tool_context.state["audit_trail"] = []
    
    return f"Success: Cleared persistent user profile (was: {old_name} - {old_tier} tier)."


root_agent = LlmAgent(
    name="production_multi_agent_demo",
    model=MODEL,
    instruction=_INSTRUCTION,
    tools=[set_user_tier, run_support_ticket, view_audit_trail, clear_user_profile],
    output_key="last_response",
)
