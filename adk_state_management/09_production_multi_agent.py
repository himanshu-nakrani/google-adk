"""
Demo 09: Production Multi-Agent Support Handoff & Auditing.

This demo showcases enterprise-grade patterns for state and context management in Google ADK:
1. Durable Cross-Session User Profiling: Using `user:` state to load customer history/tier across sessions.
2. State-Based Routing: A supervisor determines the support queue (Premium vs. Standard) based on user state.
3. Conditional Execution Handoff: Specialized agents execute only if their queue is targeted.
4. Rich Audit Logging: Tracking agent transitions in a shared list in `session.state`.
5. Guardrails & Validation: A checker agent ensures crucial state keys are populated and valid.

Run:
    python 09_production_multi_agent.py
"""

import asyncio
import datetime
from typing import Any, Dict, List

from google.adk.agents import BaseAgent, SequentialAgent
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

APP_NAME = "production_support_app"
USER_ID = "enterprise_user_123"


def log_audit(state: Dict[str, Any], message: str) -> List[str]:
    """Helper to append an audit log entry in the session state."""
    trail = list(state.get("audit_trail", []))
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    trail.append(f"[{timestamp}] {message}")
    return trail


class SupervisorAgent(BaseAgent):
    """
    Supervisor that handles customer profiling and dynamic routing.
    - If user profile does not exist in `user:` scope, registers user details.
    - Inspects `user:tier` to decide the routing target.
    - Logs transition in the shared session audit trail.
    """

    async def _run_async_impl(self, ctx):
        print(f"\n[{self.name}] Inspecting user state...")
        
        # Check if user details exist in cross-session user scope
        user_name = ctx.session.state.get("user:name")
        user_tier = ctx.session.state.get("user:tier")
        
        # If no user profile exists, perform registration delta
        state_delta = {}
        if not user_name:
            user_name = "Alice Vance"
            user_tier = "Premium"
            state_delta["user:name"] = user_name
            state_delta["user:tier"] = user_tier
            print(f"  -> Profile not found! Registering user: {user_name} ({user_tier} tier) in user: scope.")
        else:
            print(f"  -> Found persistent user profile: {user_name} ({user_tier} tier).")

        # Determine support route
        route_target = "PremiumQueue" if user_tier == "Premium" else "StandardQueue"
        state_delta["route_target"] = route_target
        
        # Log to audit trail
        audit_msg = f"Supervisor: Routed user '{user_name}' ({user_tier} tier) to support queue: '{route_target}'."
        state_delta["audit_trail"] = log_audit(ctx.session.state, audit_msg)
        
        yield Event(
            author=self.name,
            actions=EventActions(state_delta=state_delta),
        )

        yield Event(
            author=self.name,
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=f"Supervisor has routed this ticket to the {route_target}.")]
            )
        )


class PremiumSupportAgent(BaseAgent):
    """
    Specialized Premium Support Agent.
    - Executes ONLY if `route_target == 'PremiumQueue'`.
    - Simulates white-glove engineering and high priority resolution.
    - Commits resolution details and logs audit trail.
    """

    async def _run_async_impl(self, ctx):
        route = ctx.session.state.get("route_target")
        if route != "PremiumQueue":
            # Pass-through if not routed to this agent
            return

        print(f"[{self.name}] Active. Processing high-priority ticket...")
        
        state_delta = {
            "resolution_status": "RESOLVED_PREMIUM",
            "assigned_agent": "Senior Engineer Xavier",
            "resolution_notes": "Identified and resolved the database connection timeout in the staging environment. Applied high-throughput configuration.",
        }
        
        # Log audit
        audit_msg = "PremiumSupport: Ticket resolved by Senior Engineer Xavier. High-priority SLAs satisfied."
        state_delta["audit_trail"] = log_audit(ctx.session.state, audit_msg)
        
        yield Event(
            author=self.name,
            actions=EventActions(state_delta=state_delta)
        )


class StandardSupportAgent(BaseAgent):
    """
    Standard Support Agent.
    - Executes ONLY if `route_target == 'StandardQueue'`.
    - Simulates standard tier automated chatbot or support desk ticket creation.
    - Commits resolution details and logs audit trail.
    """

    async def _run_async_impl(self, ctx):
        route = ctx.session.state.get("route_target")
        if route != "StandardQueue":
            # Pass-through
            return

        print(f"[{self.name}] Active. Processing standard ticket...")
        
        state_delta = {
            "resolution_status": "RESOLVED_STANDARD",
            "assigned_agent": "Support Desk AutoBot",
            "resolution_notes": "Ticket processed. Automated diagnostics run. Basic self-help guidelines sent to customer.",
        }
        
        # Log audit
        audit_msg = "StandardSupport: Ticket processed by Support Desk AutoBot."
        state_delta["audit_trail"] = log_audit(ctx.session.state, audit_msg)
        
        yield Event(
            author=self.name,
            actions=EventActions(state_delta=state_delta)
        )


class GuardrailAgent(BaseAgent):
    """
    System Guardrail Agent (Production Best Practice).
    - Validates state invariants.
    - Ensures that `resolution_status` is populated and that the correct queue was executed.
    - Sets a `guardrail_passed` flag, or escalates if state is corrupted.
    """

    async def _run_async_impl(self, ctx):
        print(f"[{self.name}] Validating state guardrails...")
        
        res_status = ctx.session.state.get("resolution_status")
        route_target = ctx.session.state.get("route_target")
        user_tier = ctx.session.state.get("user:tier")
        
        errors = []
        if not res_status:
            errors.append("Missing resolution_status.")
        if not route_target:
            errors.append("Missing route_target.")
        if route_target == "PremiumQueue" and res_status != "RESOLVED_PREMIUM":
            errors.append(f"Mismatched routing/resolution: route={route_target}, resolution={res_status}")
            
        state_delta = {}
        if errors:
            print(f"  [Guardrail FAILED]: {', '.join(errors)}")
            state_delta["guardrail_passed"] = False
            audit_msg = f"Guardrail: State validation FAILED: {', '.join(errors)}"
            state_delta["audit_trail"] = log_audit(ctx.session.state, audit_msg)
            
            yield Event(
                author=self.name,
                actions=EventActions(escalate=True, state_delta=state_delta)
            )
        else:
            print("  [Guardrail PASSED]: All state parameters are valid.")
            state_delta["guardrail_passed"] = True
            audit_msg = "Guardrail: State validation PASSED. Ready for workflow archive."
            state_delta["audit_trail"] = log_audit(ctx.session.state, audit_msg)
            
            yield Event(
                author=self.name,
                actions=EventActions(state_delta=state_delta)
            )


async def run_support_session(session_service: InMemorySessionService, session_id: str, new_ticket_desc: str) -> Dict[str, Any]:
    """Sets up the pipeline runner and processes a support turn."""
    # Build sequential pipeline
    support_pipeline = SequentialAgent(
        name="ProductionSupportPipeline",
        sub_agents=[
            SupervisorAgent(name="Supervisor"),
            PremiumSupportAgent(name="PremiumSupport"),
            StandardSupportAgent(name="StandardSupport"),
            GuardrailAgent(name="Guardrail"),
        ]
    )

    runner = Runner(
        agent=support_pipeline,
        app_name=APP_NAME,
        session_service=session_service,
    )

    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session_id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=new_ticket_desc)],
        )
    ):
        # We can observe final responses or delta updates
        if event.content and event.is_final_response():
            for part in event.content.parts:
                if part.text:
                    print(f"  [Pipeline output]: {part.text.strip()}")

    # Fetch and return updated session state
    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session_id,
    )
    return session.state


async def main() -> None:
    # 1. Initialize our Session Service (stores state in-memory, but scope lifecycles are fully enforced)
    session_service = InMemorySessionService()

    print("======================================================================")
    print("SESSION 1: First-time Customer (No Profile in user: scope)")
    print("======================================================================")
    
    # Create the first support session
    session_1 = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
    print(f"Initial Session 1 state: {session_1.state}")
    
    ticket_1 = "My production database has been throwing connection timeouts for the last 10 minutes. High urgency!"
    final_state_1 = await run_support_session(session_service, session_1.id, ticket_1)
    
    print("\n--- Session 1 Results ---")
    print(f"User Name   : {final_state_1.get('user:name')}")
    print(f"User Tier   : {final_state_1.get('user:tier')}")
    print(f"Route Target: {final_state_1.get('route_target')}")
    print(f"Resolution  : {final_state_1.get('resolution_status')}")
    print(f"Agent       : {final_state_1.get('assigned_agent')}")
    print(f"Guardrail   : {final_state_1.get('guardrail_passed')}")
    print("\nAudit Trail:")
    for log in final_state_1.get("audit_trail", []):
        print(f"  {log}")

    print("\n======================================================================")
    print("SESSION 2: Subsequent Contact (Profile automatically resolved from user: scope)")
    print("======================================================================")
    
    # Create a new second session for the same user.
    # The session_service remembers user-scoped state since the user_id is the same.
    session_2 = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
    print(f"Initial Session 2 state: {session_2.state}")
    print("Notice that 'user:name' and 'user:tier' are already present in Session 2's starting state!")
    
    ticket_2 = "Can we check the maximum storage limits for our current premium databases?"
    final_state_2 = await run_support_session(session_service, session_2.id, ticket_2)
    
    print("\n--- Session 2 Results ---")
    print(f"User Name   : {final_state_2.get('user:name')}")
    print(f"User Tier   : {final_state_2.get('user:tier')}")
    print(f"Route Target: {final_state_2.get('route_target')}")
    print(f"Resolution  : {final_state_2.get('resolution_status')}")
    print(f"Agent       : {final_state_2.get('assigned_agent')}")
    print(f"Guardrail   : {final_state_2.get('guardrail_passed')}")
    print("\nAudit Trail:")
    for log in final_state_2.get("audit_trail", []):
        print(f"  {log}")
        
    print("\n======================================================================")
    print("SESSION 3: Customer Tier Change (Demonstrating Route Adaptation)")
    print("======================================================================")
    
    # Force a tier change in user-scoped state for testing
    session_3 = await session_service.create_session(
        app_name=APP_NAME, 
        user_id=USER_ID,
        # Seed a change to user scope
        state={"user:tier": "Standard"}
    )
    print(f"Initial Session 3 state after manual downgrading: {session_3.state}")
    
    ticket_3 = "Where can I view the API docs for the standard dashboard?"
    final_state_3 = await run_support_session(session_service, session_3.id, ticket_3)
    
    print("\n--- Session 3 Results ---")
    print(f"User Name   : {final_state_3.get('user:name')}")
    print(f"User Tier   : {final_state_3.get('user:tier')}")
    print(f"Route Target: {final_state_3.get('route_target')}")
    print(f"Resolution  : {final_state_3.get('resolution_status')}")
    print(f"Agent       : {final_state_3.get('assigned_agent')}")
    print(f"Guardrail   : {final_state_3.get('guardrail_passed')}")
    print("\nAudit Trail:")
    for log in final_state_3.get("audit_trail", []):
        print(f"  {log}")


if __name__ == "__main__":
    asyncio.run(main())
