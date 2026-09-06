# Chapter 1: Event-Sourced Core & The Event Contract

At the heart of Google ADK lies an architectural decision: **everything that happens during an agent execution is recorded as an immutable, structured event**. Rather than mutating conversation logs or database rows in place, ADK records facts about what happened.

---

## 1. Class Hierarchy: `Event` as an `LlmResponse`

In [`google.adk.events.event.Event`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/events/event.py#L91), `Event` is not a generic logging container—it directly inherits from [`LlmResponse`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/models/llm_response.py):

```python
class Event(LlmResponse):
  model_config = ConfigDict(
      extra='ignore',
      ser_json_bytes='base64',
      val_json_bytes='base64',
      alias_generator=alias_generators.to_camel,
      populate_by_name=True,
  )

  invocation_id: str = ''
  author: str = ''
  actions: EventActions = Field(default_factory=EventActions)
  output: Any | None = None
  node_info: NodeInfo = Field(default_factory=NodeInfo)
  long_running_tool_ids: set[str] | None = None
  branch: str | None = None
  isolation_scope: str | None = None
  id: str = ''
  timestamp: float = Field(default_factory=lambda: platform_time.get_time())
```

### Key Fields and Their Internal Roles:
- **`id`**: Unique string minted by ADK (via `Event.new_id()`) representing this event occurrence.
- **`invocation_id`**: Identifies the single conversational turn (`user message -> agent invocation -> final output`). All events generated during one invocation share this ID.
- **`author`**: Identifies the actor. Set to `'user'` for human inputs, or the agent's name (e.g., `'flight_agent'`) for model outputs and tool executions.
- **`content`**: Carries the raw [`google.genai.types.Content`](https://cloud.google.com/vertex-ai/docs/reference/rest/v1/Content) object (parts, role). This adheres strictly to the Gemini API wire format.
- **`actions`**: An instance of [`EventActions`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/events/event_actions.py#L78), which bundles all deterministic side-effects (state mutations, handoffs, human approvals) produced during this event.
- **`output`**: Generic typed data payload emitted by a workflow node when functioning as an automated processing step.
- **`node_info`**: Metadata identifying where the node lives in a workflow execution tree (e.g. `path="checkout_flow/payment_agent@2"`).
- **`branch`**: Hierarchical branch path string (e.g. `agent_1.agent_2`) used to isolate context between sub-agents.
- **`isolation_scope`**: Internal scope tag used by the Task API to restrict session events visible to delegated sub-agents.

---

## 2. Convenience Kwarg Routing via Pydantic Validator

ADK provides ergonomic constructors so callers don't have to nest Pydantic structures manually. In [`event.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/events/event.py#L169), a pre-model validator intercept kwargs:

```python
@model_validator(mode='before')
@classmethod
def _accept_convenience_kwargs(cls, data: Any) -> Any:
  # Routes convenience kwargs to nested fields:
  # message:   ContentUnion -> content (converted via t_content)
  # state:     dict         -> actions.state_delta
  # route:     value        -> actions.route
  # node_path: str          -> node_info.path
```

When you write:
```python
Event(author="worker", state={"processed": True}, message="Task completed")
```
ADK automatically:
1. Converts `message` into `google.genai.types.Content` via transformers.
2. Injects `state` directly into `actions.state_delta`.

---

## 3. The Side-Effect Bundle: `EventActions`

The [`EventActions`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/events/event_actions.py#L78) class defines what actions the framework must take when committing the event:

```python
class EventActions(BaseModel):
  skip_summarization: Optional[bool] = None
  state_delta: dict[str, Any] = Field(default_factory=dict)
  artifact_delta: dict[str, int] = Field(default_factory=dict)
  transfer_to_agent: Optional[str] = None
  escalate: Optional[bool] = None
  requested_auth_configs: dict[str, AuthConfig] = Field(default_factory=dict)
  requested_tool_confirmations: dict[str, ToolConfirmation] = Field(default_factory=dict)
  compaction: Optional[EventCompaction] = None
  end_of_agent: Optional[bool] = None
  agent_state: Optional[dict[str, Any]] = None
  rewind_before_invocation_id: Optional[str] = None
  route: Optional[Union[bool, int, str, list[Union[bool, int, str]]]] = None
  render_ui_widgets: Optional[list[UiWidget]] = None
  set_model_response: Optional[Any] = None
```

### Critical Side-Effect Fields:
1. **`state_delta`**: A dictionary containing updates to `session.state`. Only keys present in `state_delta` are merged into the session.
2. **`transfer_to_agent`**: If populated with an agent name, ADK hands off the execution flow to that agent on the next step.
3. **`requested_tool_confirmations`**: Pauses the invocation and yields a Human-in-the-Loop request event containing the tool call details awaiting approval.
4. **`route`**: Edge identifier used in graph workflows to decide which edge to follow out of a branching node.

---

## 4. Resilient Serialization & Fallback Wrapping

In Python agent development, users frequently store rich objects (datetimes, custom classes, even closures/lambdas) in session state. Standard JSON encoders crash on non-serializable objects.

ADK solves this with a custom **wrap serializer** in [`event_actions.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/events/event_actions.py#L97-L116):

```python
@field_serializer('state_delta', mode='wrap')
def _serialize_state_delta(
    self, value: dict[str, object], handler: SerializerFunctionWrapHandler
) -> dict[str, Any]:
  try:
    return cast(dict[str, Any], handler(value))
  except Exception:
    logger.warning('Failed to serialize `state_delta`; replacing with string repr...')
    return cast(dict[str, Any], handler(_make_json_serializable(value)))
```

Where `_make_json_serializable` delegates to `pydantic_core.to_jsonable_python(obj, serialize_unknown=True)`. If an object cannot be serialized to JSON, it is safely converted to its string `repr` rather than crashing the agent in production!

---

## 5. Streaming Invariant: Partial vs. Final Events

When streaming LLM responses or long-running tool outputs, the model yields incremental chunks.

In [`runners.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/runners.py#L1036-L1040), there is a crucial guard:

```python
if not event.partial:
  await self.session_service.append_event(
      session=ic.session, event=output_event
  )
yield output_event
```

### Why this matters:
- **`event.partial == True`**: Emitted on every streaming token chunk so UI clients can display text in real-time. **It is NEVER saved to persistent storage or session history.**
- **`event.partial == False`**: Emitted once the full model response or tool result is assembled. **Only finalized events are appended to `session.events` and committed to storage.**
