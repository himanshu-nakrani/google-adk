# Google ADK (Agent Development Kit) Code-Level Architecture & Internals

Welcome to the code-level internal architecture guide for **Google ADK** (Agent Development Kit). This documentation breaks down the internals of Google ADK directly from the source code implementation (based on `google-adk` v2.8+ located in [`google/adk`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk)).

Unlike consumer tutorials that focus merely on building quick demos, this guide explains **how ADK actually functions under the hood**: its event-sourcing mechanics, state persistence pipeline, asynchronous producer-consumer execution engine, LLM prompt assembly, tool reflection, and graph orchestration.

---

## The Core Mental Model

At its fundamental architectural layer, Google ADK is built around three core design principles:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             1. EVENT-SOURCED RECORD                              │
│  State is never an arbitrary mutable blob in storage. It is an append-only log   │
│  of immutable `Event` objects. `session.state` is a projection of state_deltas.  │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                       2. ASYNCHRONOUS PRODUCER-CONSUMER                          │
│  The agent/node graph executes inside a background worker coroutine pushing      │
│  events onto an `asyncio.Queue`. The runner consumes the queue, commits side     │
│  effects (state & database), and yields the streaming events to the caller.       │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         3. GEMINI PROTOCOL REALIGNMENT                           │
│  The framework actively rearranges, groups, and filters history so that async,   │
│  parallel, and multi-agent tool executions strictly conform to the alternating   │
│  conversational turn rules demanded by LLM inference engines (e.g. Gemini).      │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## High-Level Execution Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                           Runner.run_async()                                           │
│  Initializes Session & InvocationContext, handles resume tokens, fires on_user_message callbacks       │
└───────────────────────────────────────────────────┬────────────────────────────────────────────────────┘
                                                    │
                   ┌────────────────────────────────┴───────────────────────────────┐
                   ▼                                                                ▼
   ┌───────────────────────────────┐                                ┌───────────────────────────────┐
   │      PRODUCER (Worker)        │                                │      CONSUMER (Runner)        │
   │      _drive_root_node()       │                                │     _consume_event_queue()    │
   │                               │                                │                               │
   │  BaseNode / LlmAgent / Graph  │  ─── ic._event_queue.put() ──► │  Pops Event:                  │
   │                               │                                │  1. Run on_event plugins      │
   │  - Preprocess (Prompt/State)  │                                │  2. If not event.partial:     │
   │  - LLM API Call               │                                │     SessionService.append()   │
   │  - Parallel Tool Execution    │                                │     (Commits state_delta)     │
   │  - Dynamic Node Scheduling    │                                │  3. Yield Event to caller     │
   └───────────────────────────────┘                                └───────────────────────────────┘
```

---

## Codebase Map (`google/adk/`)

The core framework package is structured into the following specialized subsystems:

| Directory / File | Responsibilities | Key Symbols |
| :--- | :--- | :--- |
| [`events/`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/events) | Atomic data contracts, actions, branching, node metadata | [`Event`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/events/event.py#L91), [`EventActions`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/events/event_actions.py#L78), [`NodeInfo`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/events/event.py#L33), [`_BranchPath`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/events/_branch_path.py) |
| [`sessions/`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/sessions) | Session storage, state prefixes (`temp:`, `user:`, `app:`), DB persistence | [`State`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/sessions/state.py#L61), [`BaseSessionService`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/sessions/base_session_service.py#L63), [`DatabaseSessionService`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/sessions/database_session_service.py) |
| [`runners.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/runners.py) | Orchestration engine, event queue consumer, turn lifecycle | [`Runner`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/runners.py#L209) |
| [`agents/`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/agents) | Agent definitions, turn contexts, legacy multi-agent containers | [`BaseAgent`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/agents/base_agent.py#L110), [`LlmAgent`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/agents/llm_agent.py#L274), [`InvocationContext`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/agents/invocation_context.py#L105), [`Context`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/agents/context.py#L119) |
| [`flows/llm_flows/`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows) | Prompt building pipeline, tool execution, turn alignment | [`BaseLlmFlow`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/base_llm_flow.py#L1271), [`contents.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/contents.py), [`functions.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/functions.py), [`instructions.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/instructions.py) |
| [`tools/`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/tools) | Function reflection, argument schema parsing, context injection | [`BaseTool`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/tools/base_tool.py), [`FunctionTool`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/tools/function_tool.py#L99), [`ToolContext`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/tools/tool_context.py#L27) |
| [`workflow/`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow) | Modern graph engine, DAGs, loops, sequence barrier rehydration | [`BaseNode`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_base_node.py#L43), [`Workflow`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_workflow.py#L145), [`DynamicNodeScheduler`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_dynamic_node_scheduler.py), [`ReplaySequenceBarrier`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/utils/_replay_sequence_barrier.py) |

---

## Documentation Index

Explore the in-depth architectural chapters:

1. [**Chapter 1: Event-Sourced Core & The Event Contract**](./01_event_sourcing_and_events.md)  
   *The anatomy of `Event`, `EventActions`, immutability invariants, serialization wrapping, and live streaming chunks.*

2. [**Chapter 2: Session & State Management Under The Hood**](./02_session_and_state_mechanics.md)  
   *The dual-dict `State` wrapper, key prefixes (`temp:`, `user:`, `app:`), `SessionService.append_event()`, and persistence backends.*

3. [**Chapter 3: The Execution Engine: Runner & Invocation Lifecycle**](./03_runner_and_invocation_lifecycle.md)  
   *Tracing `runner.run_async()`, the background producer task, `_consume_event_queue()`, resume tokens, and lifecycle hooks.*

4. [**Chapter 4: LLM Flows, Request Processors, & Prompt Assembly**](./04_llm_flows_and_prompt_pipeline.md)  
   *`SingleFlow` vs `AutoFlow`, the request processor pipeline, system prompt formatting, `_BranchPath` isolation, and turn re-sequencing in `contents.py`.*

5. [**Chapter 5: Tool Reflection, Dispatch, & Human-In-The-Loop**](./05_tool_system_and_reflection.md)  
   *`FunctionTool` signature introspection, Pydantic type coercion, context stripping & injection, concurrent execution with `asyncio.gather`, and HITL confirmations.*

6. [**Chapter 6: The Modern Graph Engine: Workflows & Deterministic Replay**](./06_workflow_graph_engine.md)  
   *Unified `BaseNode` hierarchy, `Workflow` graphs, `DynamicNodeScheduler`, and deterministic history rehydration with `ReplaySequenceBarrier`.*
