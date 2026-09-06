# Chapter 2: Session & State Management Under The Hood

In Google ADK, state is not an arbitrary in-memory dictionary. State management is bound to the event sourcing lifecycle, strictly scoped with prefixes, and persisted by a `SessionService`.

---

## 1. The Container: `Session`

In [`google.adk.sessions.session.Session`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/sessions/session.py):

```python
class Session(BaseModel):
  id: str                          # Session ID (e.g. UUID or thread ID)
  app_name: str                    # Scopes state to this application
  user_id: str                     # User identifier
  state: dict[str, Any] = Field(default_factory=dict)
  events: list[Event] = Field(default_factory=list)
  last_update_time: float = Field(default_factory=platform_time.get_time)
```

- `session.events`: The append-only event log representing chronological conversation and execution history.
- `session.state`: The current key-value state materialized from the aggregate of all committed `state_delta` actions.

---

## 2. The Dual-Dict Pattern: `State` Wrapper

When tools or callbacks interact with state, ADK does not pass raw `session.state`. It wraps it in [`google.adk.sessions.state.State`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/sessions/state.py#L61):

```python
class State:
  APP_PREFIX = "app:"
  USER_PREFIX = "user:"
  TEMP_PREFIX = "temp:"

  def __init__(
      self,
      value: dict[str, Any],
      delta: dict[str, Any],
      schema: type[BaseModel] | None = None,
  ):
    self._value = value   # Direct reference to session.state
    self._delta = delta   # Reference to event_actions.state_delta
    self._schema = schema
```

### Reading and Writing Mechanics:

```python
def __getitem__(self, key: str) -> Any:
  # If written during this uncommitted step, return pending delta first;
  # otherwise fall back to committed session value.
  if key in self._delta:
    return self._delta[key]
  return self._value[key]

def __setitem__(self, key: str, value: Any) -> None:
  if self._schema is not None and isinstance(self._schema, type):
    _validate_state_entry(self._schema, key, value)
  # Immediately update both:
  self._value[key] = value  # Makes it readable immediately by subsequent code
  self._delta[key] = value  # Buffers it into the Event's state_delta
```

### Schema Validation:
If a node declares a Pydantic `state_schema`, any mutation to a non-prefixed key is strictly validated against the model's type hints via `TypeAdapter.validate_python(value)`. Prefixed keys (`temp:`, `user:`, `app:`) intentionally bypass strict schema validation to allow dynamic runtime tagging.

---

## 3. Scopes & Prefixes

ADK organizes state lifetimes and visibility through key prefixes:

| Scope | Prefix | Lifetime | Persistence | Use Case |
| :--- | :--- | :--- | :--- | :--- |
| **Session** | None (default) | Current conversation thread | Persisted to DB with Session document | Current user draft, order details, loop index |
| **Temporary** | `temp:` | Current invocation turn | **In-memory only** (Trimmed before persistence) | Intermediate calculation, raw tool payloads, sub-agent scratchpad |
| **User** | `user:` | All sessions of this user | Persisted to User document across all threads | User preferences, tier, language, saved auth tokens |
| **App** | `app:` | Global application | Persisted globally across all users | Feature flags, application-wide config |

---

## 4. The Commit Point: `append_event()` & The Temp-Trimming Filter

The moment state becomes durable is inside [`BaseSessionService.append_event`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/sessions/base_session_service.py#L166-L183):

```python
async def append_event(self, session: Session, event: Event) -> Event:
  if event.partial:
    return event

  # 1. Apply temp-scoped state to in-memory session.state
  self._apply_temp_state(session, event)

  # 2. Strip temp keys from the event delta before persistence
  event = self._trim_temp_delta_state(event)

  # 3. Apply persistent delta to session.state
  self._update_session_state(session, event)

  # 4. Append to history log
  session.events.append(event)
  return event
```

### How `temp:` Keys Disappear from Storage:
Look at the implementations in [`base_session_service.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/sessions/base_session_service.py#L191-L220):

```python
def _apply_temp_state(self, session: Session, event: Event) -> None:
  if not event.actions or not event.actions.state_delta:
    return
  for key, value in event.actions.state_delta.items():
    if key.startswith(State.TEMP_PREFIX):
      session.state[key] = value  # Kept in-memory for downstream agents in this turn

def _trim_temp_delta_state(self, event: Event) -> Event:
  if not event.actions or not event.actions.state_delta:
    return event
  # Filters out all keys starting with "temp:"
  event.actions.state_delta = {
      key: value
      for key, value in event.actions.state_delta.items()
      if not key.startswith(State.TEMP_PREFIX)
  }
  return event
```

This ensures that downstream agents in a sequential pipeline can read `session.state["temp:my_key"]` during the current turn, but when the database serialization executes, **no `temp:` key is ever saved into the database or event history!**

---

## 5. User-Scoped State: `get_user_state`

Cross-session user state is handled via [`get_user_state(app_name, user_id)`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/sessions/base_session_service.py#L126). 

When a session service loads or initializes a session:
1. It queries the user document at `(app_name, user_id)`.
2. Any key starting with `user:` is merged into `session.state`.
3. When `append_event()` receives `user:key` in `state_delta`, persistent implementations update both the session document and the shared user document.

---

## 6. Concrete `SessionService` Backends

ADK ships with multiple production-ready implementations:

1. [`InMemorySessionService`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/sessions/in_memory_session_service.py): Pure Python dictionary storage. Fast for unit tests and local CLI evaluation.
2. [`SQLiteSessionService`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/sessions/sqlite_session_service.py): Embedded disk storage using SQLite with JSON columns.
3. [`DatabaseSessionService`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/sessions/database_session_service.py): SQLAlchemy-backed engine supporting PostgreSQL, MySQL, and Cloud SQL.
4. [`VertexAiSessionService`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/sessions/vertex_ai_session_service.py): Google Cloud Vertex AI Managed Session Service with managed persistence and audit logs.
