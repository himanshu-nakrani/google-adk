# Chapter 4: LLM Flows, Request Processors, & Prompt Assembly

The conversational brain of an agent in Google ADK is [`LlmAgent`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/agents/llm_agent.py#L274). However, rather than calling the Gemini model directly inside the agent class, `LlmAgent` delegates turn execution to an **LLM Flow** pipeline ([`BaseLlmFlow`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/base_llm_flow.py#L1271)).

---

## 1. Flow Types: `SingleFlow` vs. `AutoFlow`

In [`llm_agent.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/agents/llm_agent.py#L885-L894), the agent dynamically selects its flow:

```python
def _llm_flow(self) -> BaseLlmFlow:
  if (
      self.disallow_transfer_to_parent
      and self.disallow_transfer_to_peers
      and not self.sub_agents
  ):
    return SingleFlow()
  else:
    return AutoFlow()
```

- [`SingleFlow`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/single_flow.py#L84): For stand-alone, isolated agents with no sub-agents or routing abilities. It only binds the agent's explicit tools.
- [`AutoFlow`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/auto_flow.py#L23): Inherits from `SingleFlow` and appends [`agent_transfer.request_processor`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/agent_transfer.py), exposing virtual tools to the model that allow dynamic handoffs to child or peer agents.

---

## 2. The Request Processor Pipeline

Before an LLM API request is sent to Gemini, it passes sequentially through a pipeline of **Request Processors** defined in [`single_flow.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/single_flow.py#L41-L73):

```python
request_processors = [
    basic.request_processor,                    # 1. Config & temperature defaults
    auth_preprocessor.request_processor,        # 2. Authentication tokens
    request_confirmation.request_processor,     # 3. Tool confirmation check
    instructions.request_processor,             # 4. System instruction assembly
    identity.request_processor,                 # 5. Agent identity tags
    compaction.request_processor,               # 6. Event window compaction
    interactions_processor.request_processor,   # 7. Stateful Interactions chain ID
    contents.request_processor,                 # 8. History & wire-content builder
    context_cache_processor.request_processor,  # 9. Gemini context caching
    _nl_planning.request_processor,             # 10. Natural language planning
    _code_execution.request_processor,          # 11. Code execution optimization
    _output_schema_processor.request_processor, # 12. Structured JSON output schema
]
```

Let's dissect the two most critical processors: `instructions.py` and `contents.py`.

---

## 3. Dynamic System Prompts & State Templating: `instructions.py`

In [`flows/llm_flows/instructions.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/instructions.py#L37-L63):

```python
async def _process_agent_instruction(
    agent: 'LlmAgent',
    invocation_context: 'InvocationContext',
) -> str:
  raw_si, bypass_state_injection = await agent.canonical_instruction(
      ReadonlyContext(invocation_context)
  )
  si = raw_si
  if not bypass_state_injection:
    si = await instructions_utils.inject_session_state(
        raw_si, ReadonlyContext(invocation_context)
    )
  return si
```

### How State Variable Interpolation Works:
If your instruction contains:
```
You are assisting {user:name}. Their loyalty tier is {user:tier}.
The current draft is: {draft}
```
ADK's `inject_session_state` scans the instruction string, resolves each token against `invocation_context.session.state`, and substitutes the actual value automatically before sending the prompt to the model.

---

## 4. History Building & Protocol Alignment: `contents.py`

Gemini and modern LLM APIs enforce strict conversational turn rules:
1. Turns must strictly alternate (`user -> model -> user -> model`).
2. A `function_call` from the model **must be followed immediately by its corresponding `function_response`** before any other message can appear.
3. Out-of-order or orphaned function responses trigger a `400 Bad Request`.

In [`flows/llm_flows/contents.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/contents.py#L163-L232), ADK performs sophisticated history restructuring:

### A. Async Response Realignment:
When tools execute asynchronously or in parallel across turns, their responses may appear later in the raw event log. [`_rearrange_events_for_async_function_responses_in_history()`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/contents.py#L163) re-sequences the history so that every `function_response` is repositioned directly after its originating `function_call`.

```
Raw Event Log:
[Event 1: FunctionCall (id="fc_1")]
[Event 2: User Message]
[Event 3: FunctionResponse (id="fc_1")]

Realigned for LLM Request:
[Turn 1: FunctionCall (id="fc_1")]
[Turn 2: FunctionResponse (id="fc_1")]
[Turn 3: User Message]
```

### B. Orphan Dropping:
If a previous branch was aborted or rewound, any orphaned `function_response` lacking a matching `function_call` is discarded via [`_drop_orphaned_function_responses()`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/contents.py#L235).

### C. Multi-Agent Branch Isolation:
In multi-agent configurations, an agent must not see internal scratchpad events from peer agents. ADK checks [`_BranchPath`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/events/_branch_path.py) in [`contents.py`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/contents.py#L944-L947):

```python
inv_path = _BranchPath.from_string(invocation_branch)
evt_path = _BranchPath.from_string(event.branch)
return inv_path == evt_path or inv_path.is_descendant_of(evt_path)
```

An agent sees only events on its own branch and ancestor branches. Sub-agent `coordinator.agent_b` can never see the internal conversation history of `coordinator.agent_a`!

---

## 5. The Core Step Loop: `_run_one_step_async`

Inside [`BaseLlmFlow`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/base_llm_flow.py#L1271-L1375), the agent executes steps in a while loop:

```python
while True:
  last_event = None
  async with Aclosing(self._run_one_step_async(invocation_context)) as agen:
    async for event in agen:
      last_event = event
      yield event
  # Exit loop if final response reached or invocation completed
  if not last_event or last_event.is_final_response() or last_event.partial:
    break
```

In each step ([`_run_one_step_async`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/base_llm_flow.py#L1286)):
1. Calls `_preprocess_async(invocation_context, llm_request)`: Runs the Request Processors to construct system prompt, context history, and tool declarations.
2. Calls `_call_llm_async(invocation_context, llm_request)`: Transmits the payload to the Gemini endpoint.
3. If Gemini emits `function_calls`: ADK yields the function call event, invokes [`handle_function_calls_async`](file:///Users/himanshu/Git/google-adk/adk-venv/lib/python3.14/site-packages/google/adk/flows/llm_flows/functions.py#L447), yields the resulting function response event, and then **repeats the while loop** so the model can read the tool results!
4. If Gemini emits text: Yields the final content event, ending the loop.
