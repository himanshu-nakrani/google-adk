# Google ADK State Management Deep Research

## TL;DR

Google ADK state management is event-sourced.

The important pieces are:

- Session: one conversation thread
- session.events: the execution history
- session.state: the shared key-value scratchpad
- EventActions.state_delta: the mechanism that commits state changes
- SessionService.append_event(): the commit point
- InvocationContext: the runtime context shared across agent calls in a turn

In multi-agent workflows:

- SequentialAgent shares the same InvocationContext and session.state across sub-agents
- LoopAgent reuses the same InvocationContext and session.state across iterations
- ParallelAgent creates branch-specific invocation contexts, but still shares session.state, so branch writes must use distinct keys

The practical rule is simple:

If you want state to persist, make it flow through an Event.

## 1. The core mental model

Think of ADK like an event-sourced workflow engine.

- Session is the persistent container for one conversation
- Event is the atomic record of what happened
- EventActions describes side effects like state changes
- SessionService commits those side effects
- Agents and tools work against a runtime InvocationContext

State is not just an ordinary in-memory dict.
It becomes durable only when ADK appends the event carrying the state delta.

## 2. The main state objects

### Session

A Session represents a single conversation thread.

Typical fields include:

- id
- app_name
- user_id
- state
- events
- last_update_time

The role of Session is to hold the current conversation’s history and mutable state.

### session.events

This is the ordered event log.

It is the history of everything that happened in the session:

- user messages
- agent outputs
- tool calls
- tool results
- state updates
- control signals

### session.state

This is the current key-value scratchpad.

Use it for things like:

- current draft
- extracted facts
- loop counters
- workflow flags
- user preferences
- temporary routing data

Examples:

- draft
- summary
- quality_status
- booking_step
- user_is_authenticated
- temp:search_results
- user:preferred_language

## 3. How state is actually committed

The central mechanism is:

- code prepares an Event
- Event carries EventActions.state_delta
- Runner receives the Event
- Runner calls SessionService.append_event(session, event)
- SessionService applies the state delta
- session.state is updated

This means that state updates are not “magically saved” by direct mutation alone.
They are committed as part of the event lifecycle.

### Common ways to write state

#### A. output_key on LlmAgent

This is the most convenient mechanism for agent-to-agent data transfer.

Example:

```python
writer = LlmAgent(
    name="Writer",
    instruction="Write a draft.",
    output_key="draft",
)
```

The final output is stored into session.state["draft"].

#### B. ToolContext.state

Inside a tool:

```python
def my_tool(tool_context: ToolContext):
    tool_context.state["lookup_result"] = {"x": 1}
    return {"ok": True}
```

ADK tracks the mutation and turns it into a state delta on the resulting event.

#### C. CallbackContext.state

Inside callbacks:

```python
def before_agent(callback_context: CallbackContext):
    callback_context.state["started_at"] = "..."
```

#### D. Manual EventActions.state_delta

For custom BaseAgent implementations:

```python
yield Event(
    author=self.name,
    actions=EventActions(state_delta={"status": "completed"}),
)
```

## 4. State scopes and prefixes

ADK supports prefixes that help you distinguish scopes.

### No prefix

Example:

- draft
- summary
- status

This is normal session state.
It is the main shared blackboard for the conversation.

### temp:

Example:

- temp:raw_results
- temp:iteration_notes

This is scoped to the current invocation.
Use it for scratch data that should not persist across future turns.

### user:

Example:

- user:preferred_language
- user:timezone

This is user-scoped state.
Use it for durable per-user preferences.

### app:

Example:

- app:feature_flag
- app:global_config

This is app-scoped state.
Use it sparingly for global application data.

## 5. Event loop timing

ADK uses a cooperative event loop.

The sequence is:

1. Runner gets user input
2. Runner loads the Session
3. Runner creates InvocationContext
4. Runner calls agent.run_async(ctx)
5. Agent yields an Event
6. Runner processes the Event
7. Runner commits state changes via SessionService
8. Runner forwards the Event upward
9. Agent resumes after the yield

Important consequence:

State becomes reliable only after the event carrying the change has been yielded and processed.

If code depends on the new value, do it after the yield/resume boundary.

## 6. SequentialAgent

SequentialAgent runs sub-agents in order.

Key behavior:

- passes the same InvocationContext to each sub-agent
- shares the same session.state across all sub-agents
- is ideal for pipelines

This makes SequentialAgent the simplest pattern for data passing between agents.

### Example pattern

```python
extract = LlmAgent(
    name="Extractor",
    instruction="Extract facts from the input.",
    output_key="facts",
)

summarize = LlmAgent(
    name="Summarizer",
    instruction="Summarize these facts: {facts}",
    output_key="summary",
)

root = SequentialAgent(
    name="Pipeline",
    sub_agents=[extract, summarize],
)
```

### SequentialAgent internal state

SequentialAgent also has its own resumability state.
The current source defines a SequentialAgentState with fields like:

- current_sub_agent

That is ADK internal agent state, not your application state.

## 7. LoopAgent

LoopAgent runs its sub-agents repeatedly.

Key behavior:

- uses the same InvocationContext across iterations
- preserves session.state across iterations
- stops when max_iterations is reached or when a sub-agent emits escalate=True

### Loop state

Current source defines LoopAgentState with fields like:

- current_sub_agent
- times_looped

Again, that is internal ADK state for resumability.

### Typical loop pattern

- writer updates draft
- critic reviews draft
- checker decides whether to stop
- if not done, loop again

### Example

```python
class CheckStatusAndEscalate(BaseAgent):
    async def _run_async_impl(self, ctx):
        status = ctx.session.state.get("quality_status", "fail")
        should_stop = (status == "pass")
        yield Event(author=self.name, actions=EventActions(escalate=should_stop))
```

## 8. ParallelAgent

ParallelAgent runs sub-agents concurrently.

Important behavior:

- creates a branch-specific InvocationContext for each sub-agent
- changes the branch name for each child
- merges event streams from parallel branches
- still shares the same session.state

The practical implication is:

Parallel branches are not isolated state silos.
They share the session blackboard.

So you must avoid collisions.

### Good pattern

Each branch writes a unique key:

- renewable_energy_result
- ev_technology_result
- carbon_capture_result

Then a later merge agent reads all of them.

### Bad pattern

All branches writing to:

- result

That is a race condition waiting to happen.

### Recommended structure

Use a parallel fan-out followed by a sequential merge:

```python
root = SequentialAgent(
    name="ResearchWorkflow",
    sub_agents=[
        ParallelAgent(
            name="FanOut",
            sub_agents=[
                researcher_a,
                researcher_b,
                researcher_c,
            ],
        ),
        merger_agent,
    ],
)
```

## 9. Internal agent state vs session state

This distinction matters.

### session.state

Your application/workflow data.

Examples:

- draft
- summary
- quality_status
- user preferences
- temporary workflow flags

### agent_state

ADK’s internal resumability bookkeeping.

Examples:

- SequentialAgentState.current_sub_agent
- LoopAgentState.times_looped
- LoopAgentState.current_sub_agent

Do not use agent_state as your app’s main data channel.

## 10. Callbacks and tools

Callbacks and tools are first-class participants in state management.

### CallbackContext.state

If you mutate callback_context.state, ADK tracks the delta.

### ToolContext.state

If you mutate tool_context.state, ADK tracks the delta.

### Why this matters

It means tool code can contribute state updates without manual EventActions wiring in most cases.

## 11. Streaming and partial events

When LLM streaming is enabled:

- partial events may be emitted for incremental UI updates
- state changes are usually committed only on the final non-partial event

This avoids repeated or unstable state writes during token streaming.

## 12. Temp state and dirty reads

ADK docs discuss a subtle behavior sometimes called dirty reads.

Within a single invocation, some code may see locally staged state before the event is fully committed.

But you should not depend on that for correctness.

Safe rule:

If the next step needs the new value reliably, make sure the previous step yielded an event and let the Runner process it first.

## 13. Recommended workflow patterns

### Sequential pipeline

Use SequentialAgent when each step depends on the previous step.

### Parallel fan-out / fan-in

Use ParallelAgent for independent work, then gather with a later agent.

### Iterative refinement

Use LoopAgent when you want repeated improvement until a criterion is met.

### Scratch state

Use temp: keys for one-turn intermediate data.

## 14. Rules of thumb

1. Use output_key for simple agent-to-agent transfers.
2. Use distinct keys in parallel branches.
3. Use SequentialAgent to merge parallel results.
4. Use LoopAgent with max_iterations or a clear escalation condition.
5. Use temp: for invocation-local scratch state.
6. Do not store large payloads in session.state.
7. Do not rely on direct mutation of retrieved sessions outside the managed event flow.
8. Treat state as event-committed, not just in-memory.

## 15. Compact mental model

- Session = conversation container
- Event = atomic record
- EventActions.state_delta = state patch
- SessionService.append_event = commit
- InvocationContext = runtime shared within a turn
- session.state = shared blackboard
- temp: = current-turn scratchpad
- SequentialAgent = ordered pipeline
- ParallelAgent = concurrent fan-out with shared state
- LoopAgent = iterative cycle with shared state
- agent_state = internal resume bookkeeping

## 16. Current source nuance

Based on the current google/adk-python source I reviewed:

- SequentialAgent passes the same ctx to each sub-agent
- LoopAgent passes the same ctx across iterations and resets sub-agent resume state between loop cycles
- ParallelAgent creates branch-specific contexts and merges event streams
- ParallelAgent is currently marked deprecated in the Python source in favor of Workflow

So the conceptual model remains valid, but ParallelAgent should be treated as a legacy/transitioning API in current source.

## 17. Bottom line

Google ADK state management is event-driven and shared across a workflow turn.

If you want to remember one sentence:

State in ADK is not just data in memory; it is data committed through events, and multi-agent workflows share that state unless you explicitly isolate or partition it.

## Sources

Official docs and source reviewed:

- https://google.github.io/adk-docs/sessions/state/
- https://google.github.io/adk-docs/sessions/session/
- https://google.github.io/adk-docs/runtime/event-loop/
- https://google.github.io/adk-docs/agents/multi-agents/
- https://google.github.io/adk-docs/agents/workflow-agents/sequential-agents/
- https://google.github.io/adk-docs/agents/workflow-agents/parallel-agents/
- https://google.github.io/adk-docs/agents/workflow-agents/loop-agents/
- https://github.com/google/adk-python/blob/main/src/google/adk/agents/base_agent.py
- https://github.com/google/adk-python/blob/main/src/google/adk/agents/sequential_agent.py
- https://github.com/google/adk-python/blob/main/src/google/adk/agents/parallel_agent.py
- https://github.com/google/adk-python/blob/main/src/google/adk/agents/loop_agent.py
