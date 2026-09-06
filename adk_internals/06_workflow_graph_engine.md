# Chapter 6: The Modern Graph Engine: Workflows & Deterministic Replay

Starting in Google ADK v2.x, the framework transitioned from rigid multi-agent wrappers (`SequentialAgent`, `ParallelAgent`, `LoopAgent`) to a unified, graph-based execution engine centered around [`BaseNode`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_base_node.py#L43) and [`Workflow`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_workflow.py#L145).

---

## 1. Unified Node Hierarchy: `BaseNode`

In [`google.adk.workflow._base_node.BaseNode`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_base_node.py#L43):

```python
class BaseNode(BaseModel, abc.ABC):
  name: str = Field(...)
  description: str = ''
  rerun_on_resume: bool = False
  wait_for_output: bool = False
  retry_config: RetryConfig | None = None
  timeout: float | None = None
  input_schema: SchemaType | None = None
  output_schema: SchemaType | None = None

  @abc.abstractmethod
  async def _run_impl(
      self, *, ctx: Context, node_input: Any
  ) -> AsyncGenerator[Any, None]:
    """Every node in the graph yields its outputs or events via this method."""
```

### Unification with `BaseAgent`:
Notice how [`BaseAgent`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/agents/base_agent.py#L110) is declared:

```python
class BaseAgent(BaseNode, abc.ABC): ...
```

In ADK, **every agent is a workflow node**. This means agents, pure Python functions ([`FunctionNode`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_function_node.py)), tools ([`ToolNode`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_tool_node.py)), and synchronization barriers ([`JoinNode`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_join_node.py)) can be mixed and matched freely inside a single workflow graph.

---

## 2. Graph Definition: `Workflow` & `EdgeItem`

A [`Workflow`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_workflow.py#L145) defines a directed graph of nodes and transitions:

```python
from google.adk.workflow import Workflow, START

workflow = Workflow(
    name="order_fulfillment",
    edges=[
        (START, "validate_order"),
        ("validate_order", "process_payment"),
        ("process_payment", "notify_warehouse"),
    ],
    max_concurrency=5,
)
```

### Graph Features:
1. **DAGs and Cyclic Loops**: Unlike basic chain executors, ADK's [`Graph`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_graph.py) supports cyclic edges for iterative refinement (e.g. `generator -> reviewer -> generator`).
2. **Conditional Branching via Routes**: Nodes can yield route tags (`ctx.set_route("approved")`). Graph edges can match specific route conditions:
   ```python
   edges=[
       ("review_code", "approved", "deploy_service"),
       ("review_code", "rejected", "fix_code"),
   ]
   ```

---

## 3. The Graph Orchestration Loop: `Workflow._run_impl`

Inside [`Workflow._run_impl()`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_workflow.py), ADK executes a reactive orchestration loop:

```
                            Workflow._run_impl() Starts
                                         │
                                         ▼
                           1. _seed_start_triggers()
                              Places initial triggers into trigger_buffer
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   ▼                                           ▼
         2. _schedule_ready_nodes()               3. Await Completed Tasks
         - Pops triggers from buffer              - Gathers outputs from finished nodes
         - Respects `max_concurrency`             - Checks for NodeInterruptedError
         - Spawns NodeRunner as asyncio.Task      - Emits completed events
                   ▲                                           │
                   │                                           ▼
                   └──────────────── 4. _buffer_downstream_triggers()
                                     Evaluates edges leaving finished node;
                                     Pushes new triggers into trigger_buffer
```

The loop runs until there are no running tasks and no pending triggers in the buffer, at which point the workflow finalizes.

---

## 4. Dynamic Node Scheduling: `ctx.run_node()`

In complex multi-agent architectures, workflows cannot always be pre-compiled into a static graph. An agent may decide at runtime: *"I need to run the research agent 3 times for these 3 specific topics."*

ADK provides dynamic scheduling via [`DynamicNodeScheduler`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_dynamic_node_scheduler.py):

```python
# Inside an agent or function node:
summary = await ctx.run_node(analyst_agent, node_input={"topic": "Quantum Computing"})
```

### How it works:
1. `ctx.run_node()` creates a dynamic child execution path (e.g. `root/research_agent@run_1`).
2. It tracks the dynamic node in [`_LoopState`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_workflow.py#L68).
3. The child node runs using the outer workflow's event queue and shares the same `session.state`.

---

## 5. Resumption & History Rehydration: `ReplaySequenceBarrier`

One of the hardest problems in agent workflows is **resuming execution after an interruption** (e.g. waiting days for a user to approve a budget request, or recovering after a server crash).

If the server restarts, how does ADK know which nodes already completed without re-running expensive LLM calls or duplicate database writes?

In [`workflow/utils/_replay_sequence_barrier.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/utils/_replay_sequence_barrier.py) and [`_workflow.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/workflow/_workflow.py#L43-L47):

### The Rehydration Process:
1. When `runner.run_async()` resumes under an existing `session_id`, the workflow does not run blind.
2. It scans `session.events` to reconstruct the status and output of every node that ran previously (`recovered_executions: dict[str, _ChildScanState]`).
3. For nodes that already completed, ADK performs a **fast-forward replay**:
   - The node is not actually re-executed.
   - Its cached outputs and state deltas are replayed instantly through the sequence barrier.
4. Execution only executes fresh code once it reaches the node that was interrupted or has never run!
