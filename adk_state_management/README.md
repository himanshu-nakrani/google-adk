# ADK State Management — Demo Agents

A hands-on demo suite for learning how state works in Google ADK.

This folder contains two ways to study the same concepts:

1. Standalone numbered scripts (`01_...py` through `08_...py`) that you run from the terminal.
2. ADK Web / `adk run` compatible agent folders (`*_agent/`, `*_demo/`) that expose the same ideas as interactive agents.

The goal is to make ADK state feel concrete: you can see exactly when values enter `session.state`, which state survives across turns, and how multi-agent workflows pass data through shared state.

---

## Quick start

```bash
cd adk_state_management
python -m pip install -r requirements.txt
export GOOGLE_API_KEY=<your_key>   # required for LLM demos
```

Run a standalone script:

```bash
python 01_output_key.py
```

Run an interactive ADK agent:

```bash
adk run output_key_agent
```

Or start the ADK web UI from this folder:

```bash
adk web
```

Then choose one of the agent folders, such as `output_key_agent`, `state_prefixes_agent`, or `parallel_agent_demo`.

---

## Big picture

ADK state management is event-driven.

```text
User input
   ↓
Runner loads Session
   ↓
Agent / Tool / Callback runs with InvocationContext
   ↓
Code yields or returns an Event
   ↓
EventActions.state_delta carries state changes
   ↓
SessionService.append_event() commits the Event
   ↓
session.state now contains the committed values
```

Important mental model:

```text
Session                    = one conversation container
Event                      = atomic record of something that happened
EventActions.state_delta   = patch of state changes carried by an Event
SessionService.append_event = commit point
InvocationContext          = runtime context shared inside a turn/workflow
session.state              = shared key/value blackboard
```

State is not just an ordinary in-memory dictionary. In normal ADK execution, state becomes reliable when it flows through the managed event lifecycle and is committed by the `SessionService`.

---

## Demo map

| # | Concept | Standalone script | Interactive agent | Needs LLM? | Core lesson |
|---|---------|-------------------|-------------------|------------|-------------|
| 01 | `output_key` | `01_output_key.py` | `output_key_agent` | Yes | Save final LLM response into `session.state` automatically. |
| 02 | State prefixes | `02_state_prefixes.py` | `state_prefixes_agent` | No for script; agent shell uses LLM | Understand session, temp, user, and app scopes. |
| 03 | `ToolContext.state` | `03_tool_context_state.py` | `tool_context_agent` | Yes | Tools can read/write state and ADK tracks the delta. |
| 04 | `CallbackContext.state` | `04_callback_context_state.py` | `callback_context_agent` | Yes | Lifecycle callbacks can instrument turns through state. |
| 05 | Manual `EventActions.state_delta` | `05_custom_agent_state_delta.py` | `custom_state_delta_agent` | No for inner workflow; agent shell uses LLM | Lowest-level state commit mechanism. |
| 06 | `SequentialAgent` | `06_sequential_pipeline.py` | `sequential_pipeline_agent` | Yes | Ordered pipeline where each step reads prior state. |
| 07 | `LoopAgent` | `07_loop_agent.py` | `loop_agent_demo` | Yes | Iterative refinement with stateful stop condition. |
| 08 | `ParallelAgent` | `08_parallel_agent.py` | `parallel_agent_demo` | Yes | Fan-out/fan-in with shared state and unique branch keys. |
| 09 | Enterprise Routing & Auditing | `09_production_multi_agent.py` | `production_multi_agent_demo` | No for inner pipeline; agent shell uses LLM | Supervisor routing, persistent user profiles, audit logs, and guardrails. |

---

## State scopes and prefixes

ADK recognizes prefixes that determine the scope of a state key.

| Prefix | Example key | Scope | Persists? | Use for |
|--------|-------------|-------|-----------|---------|
| none | `draft` | Current session | Yes | Main workflow data for one conversation. |
| `temp:` | `temp:raw_search_results` | Current invocation only | No | Scratch data that should vanish after the turn. |
| `user:` | `user:preferred_language` | All sessions for the user | Yes | Durable user preferences. |
| `app:` | `app:feature_flag` | All users and sessions for the app | Yes | Shared app configuration or global flags. |

Rule of thumb: start with normal session keys, use `temp:` for scratch data, and use `user:` / `app:` only when you intentionally want cross-session or global behavior.

---

## The eight demos

### 01 — `output_key`: simplest state write

`LlmAgent(output_key="last_response")` saves the agent's final text response into `session.state["last_response"]` automatically.

Run:

```bash
python 01_output_key.py
adk run output_key_agent
```

Use this when one agent needs to hand its final answer to another agent, a later workflow step, or a UI inspection view.

Key idea:

```python
agent = LlmAgent(
    name="Greeter",
    model=MODEL,
    instruction="Write a short greeting.",
    output_key="greeting",
)
```

After the agent finishes, the final answer is available as:

```python
session.state["greeting"]
```

---

### 02 — State prefixes: session vs temp vs user vs app

This demo writes one key per scope and then shows which keys survive after the run.

Run:

```bash
python 02_state_prefixes.py
adk run state_prefixes_agent
```

Expected behavior:

- `session_key` / `session_demo` survives in the current session.
- `temp:scratch` is available only during the invocation and is discarded afterward.
- `user:preferred_language` is stored at user scope.
- `app:feature_flag` is stored at app scope.

Use this demo to build intuition about state lifetime.

---

### 03 — `ToolContext.state`: tools as state participants

Any tool function can ask for a `ToolContext` parameter. ADK injects it when the tool is called.

Run:

```bash
python 03_tool_context_state.py
adk run tool_context_agent
```

Pattern:

```python
def search(query: str, tool_context: ToolContext) -> str:
    count = tool_context.state.get("search_count", 0) + 1
    tool_context.state["search_count"] = count
    tool_context.state["last_query"] = query
    return f"Search complete: {query}"
```

What it teaches:

- Tools can maintain counters, intermediate results, flags, and structured data.
- You usually do not need manual `EventActions.state_delta` inside normal tool functions.
- ADK observes the `tool_context.state` mutation and commits it as part of the tool event.

---

### 04 — `CallbackContext.state`: lifecycle instrumentation

Callbacks let you read/write state around the agent lifecycle.

Run:

```bash
python 04_callback_context_state.py
adk run callback_context_agent
```

Typical uses:

- Track turn counts.
- Add timestamps.
- Store audit/debug metadata.
- Short-circuit or modify responses based on state.

This is useful when the state update belongs to infrastructure or orchestration rather than the agent prompt itself.

---

### 05 — Manual `EventActions.state_delta`: lowest-level commit

Custom `BaseAgent` implementations can yield `Event` objects directly.

Run:

```bash
python 05_custom_agent_state_delta.py
adk run custom_state_delta_agent
```

Pattern:

```python
yield Event(
    author=self.name,
    actions=EventActions(
        state_delta={
            "workflow_status": "processing",
            "step": 2,
        }
    ),
)
```

What it teaches:

- `EventActions.state_delta` is the foundation below `output_key`, tools, and callbacks.
- Each yielded event is a natural commit boundary.
- A later step can read state committed by an earlier yielded event.

Use this when you are writing custom agents that need explicit control over the event stream.

---

### 06 — `SequentialAgent`: ordered pipeline state

`SequentialAgent` passes the same `InvocationContext` through sub-agents in order.

Run:

```bash
python 06_sequential_pipeline.py
adk run sequential_pipeline_agent
```

Pipeline in this demo:

```text
Extractor  --writes--> keywords
    ↓
Summariser --reads keywords + article, writes--> summary
    ↓
Titler     --reads summary, writes--> title
```

Why it works:

- Each sub-agent writes its result with `output_key`.
- Later sub-agents reference earlier state through instruction templates like `{keywords}` and `{summary}`.
- All sub-agents share the same session state for the workflow.

Use `SequentialAgent` when step B depends on the output of step A.

---

### 07 — `LoopAgent`: iterative stateful refinement

`LoopAgent` repeats its sub-agents until either `max_iterations` is reached or a sub-agent emits `escalate=True`.

Run:

```bash
python 07_loop_agent.py
adk run loop_agent_demo
```

Loop in this demo:

```text
Writer → Critic → CriticParser → QualityChecker
   ↑                                      ↓
   └──────── repeat until score ≥ 8 ──────┘
```

State keys used:

| Key | Written by | Meaning |
|-----|------------|---------|
| `draft` | Writer | Current draft text. |
| `critic_output` | Critic | Raw score/feedback text. |
| `quality_score` | CriticParser | Parsed numeric score. |
| `critic_feedback` | CriticParser | Parsed feedback. |
| `iteration` | QualityChecker | Number of loop cycles completed. |

Use this pattern for self-improvement, retry loops, quality gates, and incremental refinement.

---

### 08 — `ParallelAgent`: fan-out/fan-in state

`ParallelAgent` runs branches concurrently. The branches have separate branch contexts, but they still share the same `session.state` blackboard.

Run:

```bash
python 08_parallel_agent.py
adk run parallel_agent_demo
```

Workflow in this demo:

```text
                    ┌─ ClimateResearcher → climate_result ┐
Parallel fan-out ───┼─ AIResearcher      → ai_result      ├─ Merger → final_report
                    └─ SpaceResearcher   → space_result   ┘
```

Critical rule:

Every parallel branch must write to a unique key.

Good:

```text
climate_result
ai_result
space_result
```

Bad:

```text
result
result
result
```

If multiple branches write the same key, the final value depends on race timing and is not reliable.

---

### 09 — Enterprise Routing & Auditing: Production Patterns

In production multi-agent systems, state is crucial for orchestration, routing, compliance, and user personalization. This demo combines four major patterns:

1. **Durable Cross-Session User Profiling**: Stores customer tier (`user:tier`) in the cross-session `user:` scope.
2. **Supervisor-driven State Routing**: A supervisor agent reads the user's state to determine routing (`route_target`).
3. **Chronological Audit Trail**: Log messages are dynamically formatted and stored as a structured list in `session.state["audit_trail"]` for observability.
4. **Validation Guardrails**: A checker agent evaluates the final state against compliance rules, raising errors or setting status.

Run:

```bash
python 09_production_multi_agent.py
adk run production_multi_agent_demo
```

Workflow:

```text
User profile in user: scope
         ↓
Supervisor inspects profile & assigns support queue
         ↓
Support Agents execute conditionally based on queue state
         ↓
Guardrail validates the outcome & commits compliance status
         ↓
Audit Trail records every step chronologically in state
```

---

## Standalone scripts vs interactive agent folders

### Standalone scripts

The numbered scripts are best for understanding mechanics because they print state before and after a run.

Examples:

```bash
python 02_state_prefixes.py
python 05_custom_agent_state_delta.py
```

These are good when you want to inspect exact state changes without the ADK web UI.

### Interactive agent folders

The agent folders are best for experimenting conversationally with `adk run` or `adk web`.

Examples:

```bash
adk run tool_context_agent
adk run sequential_pipeline_agent
adk run loop_agent_demo
```

Each folder contains an `agent.py` with a `root_agent` that ADK can discover.

---

## Common patterns

### Pattern 1: Simple handoff

Use `output_key`.

```text
Agent A final response → session.state["a_result"] → Agent B prompt template
```

### Pattern 2: Tool records useful metadata

Use `ToolContext.state`.

```text
Tool call → update counters/results in tool_context.state → ADK commits tool event
```

### Pattern 3: Ordered pipeline

Use `SequentialAgent`.

```text
Extract → Transform → Summarize → Title
```

### Pattern 4: Quality loop

Use `LoopAgent` plus a checker agent.

```text
Generate → Critique → Parse score → Stop or repeat
```

### Pattern 5: Concurrent research

Use `ParallelAgent` with unique output keys, then merge sequentially.

```text
Parallel branches write distinct keys → merger reads all keys
```

---

## Pitfalls and fixes

| Problem | Symptom | Fix |
|---------|---------|-----|
| Forgetting `output_key` | Later agent sees missing `{key}` value. | Add a unique `output_key` to the producer agent. |
| Parallel key collision | Final value is inconsistent or from only one branch. | Give every branch its own output key. |
| Depending on `temp:` later | Key disappears after the invocation. | Use a normal session key if it must persist. |
| Mutating a fetched session directly | State seems changed in memory but not reliably persisted. | Make changes through tools, callbacks, `output_key`, or yielded events. |
| Loop never stops | `LoopAgent` runs until `max_iterations`. | Add a checker that emits `EventActions(escalate=True)` when done. |
| Prompt template key missing | LLM prompt has unresolved or empty context. | Seed the key in initial state or ensure an earlier step writes it. |
| Import error: `No module named 'google'` | Scripts fail before running. | Install dependencies with `python -m pip install -r requirements.txt`. |
| Missing API key | LLM demos fail at runtime. | Export `GOOGLE_API_KEY` before running LLM-based demos. |

---

## Suggested learning path

1. Run `02_state_prefixes.py` first. It does not need an LLM and teaches state lifetimes.
2. Run `05_custom_agent_state_delta.py` to see the raw event/state mechanism.
3. Run `01_output_key.py` to see the simplest LLM-to-state pattern.
4. Run `03_tool_context_state.py` and `04_callback_context_state.py` to see non-agent state writers.
5. Run `06_sequential_pipeline.py` for ordered multi-agent state passing.
6. Run `07_loop_agent.py` for repeated stateful refinement.
7. Run `08_parallel_agent.py` last, because shared state plus concurrency is the easiest place to make mistakes.

---

## Rules of thumb

1. Use `output_key` for simple LLM output handoff.
2. Use `ToolContext.state` when a tool discovers or computes something later steps need.
3. Use `CallbackContext.state` for lifecycle metadata and instrumentation.
4. Use manual `EventActions.state_delta` only when writing custom event-yielding agents.
5. Use normal session keys for workflow data that should persist in the current conversation.
6. Use `temp:` for scratch data that should vanish after the invocation.
7. Use `user:` and `app:` deliberately; they outlive a single session.
8. Use unique keys in parallel branches.
9. Use `SequentialAgent` to merge or consume results after parallel fan-out.
10. Treat state as event-committed, not merely dictionary-mutated.

---
