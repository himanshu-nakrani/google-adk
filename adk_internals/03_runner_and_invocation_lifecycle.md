# Chapter 3: The Execution Engine: Runner & Invocation Lifecycle

The [Runner](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/runners.py#L209) is the execution engine of Google ADK. It manages sessions, initializes turn contexts, controls concurrency, enforces invocation limits, and yields streaming event outputs.

---

## 1. The Core Lifecycle: Step-by-Step

When client code calls:

```python
async for event in runner.run_async(
    user_id="user_123",
    session_id="session_456",
    new_message=Content(role="user", parts=[Part(text="Hello!")]),
):
  print(event)
```

The execution passes through a strict 10-step pipeline in [`runners.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/runners.py#L580-L780):

```
1. Get or Create Session
   └─► self._get_or_create_session(user_id, session_id)
        │
2. Resolve Resume Tokens
   └─► Checks if new_message is a FunctionResponse or resume input.
       If resuming, resolves past invocation_id from history.
        │
3. Create InvocationContext
   └─► ic = self._new_invocation_context(session, new_message, run_config)
       ic._event_queue = asyncio.Queue()
        │
4. Plugin Hook: on_user_message
   └─► ic.plugin_manager.run_on_user_message_callback(user_message)
        │
5. Append User Event
   └─► Appends user message to session.events and writes to DB
        │
6. Plugin Hook: before_run
   └─► If a plugin returns Content, exit early and yield response immediately
        │
7. Spawn Background Driver Task
   └─► task = asyncio.create_task(_drive_root_node())
        │
8. Main Consumer Loop
   └─► _consume_event_queue(ic, done_sentinel):
       Reads from ic._event_queue, commits to DB, yields to caller
        │
9. Task Cleanup & Cancellation
   └─► Awaits driver task completion; handles early break / cancellation
        │
10. Post-Invocation Compaction
    └─► Runs sliding-window event compaction if token limits are exceeded
```

---

## 2. InvocationContext: The Scope of a Single Turn

An [`InvocationContext`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/agents/invocation_context.py#L105) encapsulates all transient execution state for **one conversational turn**:

```python
class InvocationContext(BaseModel):
  invocation_id: str               # Unique UUID identifying this single turn
  branch: str | None = None        # Execution branch tag (e.g. "coordinator.sub_1")
  isolation_scope: str | None = None
  agent: BaseAgent | BaseNode | None = None
  user_content: types.Content | None = None
  session: Session                 # Reference to current Session
  session_service: BaseSessionService
  artifact_service: BaseArtifactService | None = None
  memory_service: BaseMemoryService | None = None
  end_invocation: bool = False     # Set to True by tools/callbacks to halt turn immediately
  _event_queue: asyncio.Queue | None = None  # Inter-task pipeline
```

### Invariant: Invocation vs. Step vs. Agent Call
Inside the ADK source code, these terms have precise technical meanings:
- **Invocation**: Begins with a user query and ends when the final user-facing response is emitted (or aborted). Handled by `runner.run_async()`.
- **Agent Call**: The execution span of one specific agent inside that turn. Handled by `agent.run_async()`.
- **Step**: Exactly **one** LLM API call + its corresponding tool calls. Handled by `flow._run_one_step_async()`.

```
┌────────────────────────────────── Invocation ───────────────────────────────────┐
┌─────────── Agent Call 1 ───────────┐ ┌─────────────── Agent Call 2 ─────────────┐
┌──── Step 1 ────┐  ┌──── Step 2 ────┐
[Call LLM] [Tools]  [Call LLM] [Handoff]  [Call LLM] [Tools] [Final Text Response]
```

---

## 3. Cost & Safety Controls: `_InvocationCostManager`

To protect against runaway infinite loops (e.g. an agent calling tools in an unbounded loop), `InvocationContext` embeds an internal cost manager in [`invocation_context.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/agents/invocation_context.py#L75-L103):

```python
class _InvocationCostManager(BaseModel):
  _number_of_llm_calls: int = 0

  def increment_and_enforce_llm_calls_limit(
      self, run_config: RunConfig | None
  ) -> None:
    self._number_of_llm_calls += 1
    if (
        run_config
        and run_config.max_llm_calls > 0
        and self._number_of_llm_calls > run_config.max_llm_calls
    ):
      raise LlmCallsLimitExceededError(
          f"Max number of llm calls limit of `{run_config.max_llm_calls}` exceeded"
      )
```

Every time `BaseLlmFlow` prepares an LLM call, this counter increments. If it breaches `run_config.max_llm_calls`, it immediately halts execution with an exception.

---

## 4. The Producer-Consumer Queue

Why does ADK use an `asyncio.Queue` between the agent node and the runner rather than a direct generator yield?

In [`runners.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/runners.py#L739-L761):

```python
done_sentinel = object()

async def _drive_root_node() -> None:
  try:
    await root_ctx._run_node_internal(
        root_node,
        node_input=node_input,
        resume_inputs=resume_inputs,
    )
  except NodeInterruptedError:
    pass  # Node intentionally paused (e.g., awaiting human confirmation)
  finally:
    await ic._event_queue.put((done_sentinel, None))

task = asyncio.create_task(_drive_root_node())
```

And in [`_consume_event_queue()`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/runners.py#L998-L1044):

```python
async def _consume_event_queue(
    self, ic: InvocationContext, done_sentinel: object
) -> AsyncGenerator[Event, None]:
  while True:
    event_or_done, processed_signal = await event_queue.get()
    if event_or_done is done_sentinel:
      break
    event = event_or_done

    # Run plugin on_event callbacks (allows observability & telemetry inspection)
    modified_event = await ic.plugin_manager.run_on_event_callback(
        invocation_context=ic, event=event
    )

    # Partial streaming events bypass persistent storage!
    if not event.partial:
      await self.session_service.append_event(
          session=ic.session, event=output_event
      )

    yield output_event

    # Acknowledge event processing
    if isinstance(processed_signal, asyncio.Event):
      processed_signal.set()
```

### Key Architectural Benefits:
1. **Concurrency Decoupling**: If an agent starts parallel sub-nodes or tools, they can emit events onto the queue concurrently without blocking each other.
2. **Persistence Guarantee**: Every non-partial event is guaranteed to be saved into `session_service` before it is yielded out to the client. If the client disconnects or crashes during iteration, past events are already durably saved.
3. **Graceful Cancellation**: If the client does `break` inside their `async for event in runner.run_async()`, [`_cleanup_root_task()`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/runners.py#L1045) detects that the driver task is still running, issues `task.cancel()`, and awaits it to prevent leaked background coroutines.
