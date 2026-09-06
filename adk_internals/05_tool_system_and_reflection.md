# Chapter 5: Tool Reflection, Dispatch, & Human-In-The-Loop

The tool system in Google ADK allows developers to turn arbitrary Python functions into Gemini tool declarations without writing manual JSON schemas. The core magic resides in [`FunctionTool`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/tools/function_tool.py#L99) and the function calling engine in [`flows/llm_flows/functions.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/functions.py).

---

## 1. Schema Generation & Reflection: `FunctionTool`

When you wrap a Python callable in [`FunctionTool`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/tools/function_tool.py#L106-L143):

```python
def check_order_status(order_id: str, tool_context: ToolContext) -> dict[str, Any]:
  """Check the status of an existing order.
  
  Args:
    order_id: The UUID of the order.
  """
  ...
```

ADK automatically executes the following:

### A. Context Parameter Detection & Schema Stripping
In [`function_tool.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/tools/function_tool.py#L140-L142):

```python
self._context_param_name = find_context_parameter(func) or 'tool_context'
self._ignore_params = [self._context_param_name, 'input_stream']
```

ADK inspects the callable's signature. If it finds a parameter annotated as [`ToolContext`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/tools/tool_context.py#L27) or named `tool_context`, it registers it in `self._ignore_params`.

When building the Gemini `FunctionDeclaration`, **these parameters are stripped from the schema**. The LLM never sees `tool_context` in the schema and will never attempt to generate arguments for it.

### B. Declaration Caching: `_build_declaration_cached`
Building JSON schemas via Pydantic on every single LLM call is computationally expensive. ADK caches declarations using `@functools.lru_cache(maxsize=1024)` in [`function_tool.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/tools/function_tool.py#L75-L96), ensuring that tool schemas are generated only once per process.

---

## 2. Argument Preprocessing & Pydantic Coercion

LLM APIs return tool call arguments as plain JSON dictionaries. If your Python function expects a strongly typed Pydantic model:

```python
class ShippingAddress(BaseModel):
  street: str
  postal_code: str

def update_shipping(address: ShippingAddress): ...
```

Inside [`FunctionTool._preprocess_args()`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/tools/function_tool.py#L157-L264):

1. It checks the type hints of each function parameter.
2. If the target parameter is a `BaseModel` (or `Optional[BaseModel]`, `Union`, or `list[BaseModel]`), ADK coerces the incoming dictionary using `target_type.model_validate(args[param_name])` or Pydantic's `TypeAdapter`.
3. If validation fails, it logs a warning and passes the raw arguments rather than crashing.

---

## 3. Dynamic Context Injection: `_prepare_invocation_args`

When it is time to invoke the function in [`function_tool.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/tools/function_tool.py#L266-L289):

```python
def _prepare_invocation_args(
    self, args: dict[str, Any], tool_context: ToolContext
) -> dict[str, Any]:
  args_to_call = self._preprocess_args(args)
  signature = inspect.signature(self.func)
  valid_params = set(signature.parameters.keys())
  
  # Inject the runtime ToolContext instance!
  if self._context_param_name in valid_params:
    args_to_call[self._context_param_name] = tool_context
    
  # In live streaming mode, inject the active WebRTC/Audio queue
  if 'input_stream' in valid_params:
    ...
  return {k: v for k, v in args_to_call.items() if k in valid_params}
```

The runtime [`ToolContext`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/tools/tool_context.py#L27) (which is an alias for [`Context`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/agents/context.py#L119)) is injected seamlessly.

---

## 4. Concurrent Tool Execution

When Gemini emits multiple parallel function calls in a single turn, ADK executes them concurrently in [`handle_function_call_list_async`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/functions.py#L465-L508):

```python
# Create tasks for parallel execution
tasks = [
    asyncio.create_task(
        _execute_single_function_call_async(
            invocation_context, function_call, tools_dict, agent, ...
        )
    )
    for function_call in filtered_calls
]

# Wait for all tasks to complete concurrently
maybe_function_response_events = await asyncio.gather(*tasks)

# Merge parallel results into one response event for the wire protocol
merged_event = merge_parallel_function_response_events(function_response_events)
```

Each tool runs concurrently in its own asyncio task. Once all tool executions return, their individual responses are merged into a single event carrying all `function_responses`.

---

## 5. Tool Lifecycle Callbacks & Middleware

ADK provides a structured interceptor chain around tool execution in [`_execute_single_function_call_async`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/functions.py#L544-L640):

```
                        function_call emitted by Gemini
                                       │
                                       ▼
                     1. plugin_manager.before_tool_callback
                     2. agent.canonical_before_tool_callbacks
                                       │
                  ┌────────────────────┴────────────────────┐
                  │ Overridden?                             │
                 YES                                       NO
                  │                                         │
                  ▼                                         ▼
         Use injected response                      Invoke actual tool
                                                            │
                                             ┌──────────────┴──────────────┐
                                          Success                       Exception
                                             │                             │
                                             ▼                             ▼
                              3. after_tool_callback       4. on_tool_error_callback
```

- **`before_tool_callback`**: Can intercept, inspect, or mock the tool response (e.g. for caching or security sandboxing). If it returns a value, the actual tool function is skipped.
- **`on_tool_error_callback`**: Captures exceptions raised inside tool functions. It can convert crashes into polite error messages returned to the LLM (e.g., *"Database timed out, please retry"*), preventing the agent from crashing.

---

## 6. Human-In-The-Loop (HITL) & Tool Confirmations

Certain sensitive actions (e.g., executing a financial transaction or deleting a database record) require human confirmation before execution.

ADK supports this natively through `require_confirmation` in [`FunctionTool`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/tools/function_tool.py#L110):

```python
def delete_database(db_id: str): ...

tool = FunctionTool(delete_database, require_confirmation=True)
# Or dynamic: require_confirmation=lambda args: args["amount"] > 1000
```

### Execution Flow on Confirmation:
1. Gemini calls `delete_database(db_id="prod")`.
2. ADK calls [`check_require_confirmation()`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/tools/function_tool.py#L291).
3. If `True`, the tool execution is **halted**. ADK yields an event containing [`EventActions.requested_tool_confirmations`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/events/event_actions.py#L152) and raises `NodeInterruptedError`.
4. The client receives the event, renders an *"Approve / Reject"* modal in the UI.
5. On user approval, the client calls `runner.run_async(...)` passing the original `invocation_id` and the confirmation response.
6. ADK resumes execution, executes the function call, and continues the conversation.
