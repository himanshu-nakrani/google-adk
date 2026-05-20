"""
SequentialAgent state-passing demo.

SequentialAgent passes the same InvocationContext (and session.state) to
every sub-agent in order. output_key saves each agent response; {key}
templates in the next agent's instruction inject the saved values.

Pipeline: Extractor → Summariser → Titler

The article is seeded into state via the tool set_article(). The user
can also set any article they like and then call run_pipeline().

Run with:
    adk web    (from adk_state_management/)
    adk run sequential_pipeline_agent
"""

import asyncio

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.tool_context import ToolContext
from google.genai import types

MODEL = "gemini-2.0-flash"

_DEFAULT_ARTICLE = (
    "Transformer neural networks, introduced in Attention Is All You Need (2017), "
    "revolutionised NLP by replacing recurrent architectures with self-attention. "
    "They scale efficiently and power models like GPT and BERT, enabling breakthroughs "
    "in translation, summarisation, question answering, and code generation."
)

_INSTRUCTION = """
You are a sequential-pipeline demo agent for ADK.

You coordinate a three-step pipeline:
  1. Extractor  – extracts keywords from an article
  2. Summariser – writes a summary using those keywords
  3. Titler     – generates a title from the summary

Tools:
  set_article(text) – store the article to process
  run_pipeline()    – execute the SequentialAgent pipeline
  show_results()    – display keywords, summary, and title from state

Walk the user through the pipeline. Explain how SequentialAgent shares
InvocationContext so each sub-agent sees the previous one's output_key.
""".strip()


def set_article(text: str, tool_context: ToolContext) -> str:
    """Store article text in session state so the pipeline can process it."""
    tool_context.state["article"] = text
    return f"Article stored ({len(text)} chars). Call run_pipeline() to process it."


async def run_pipeline(tool_context: ToolContext) -> str:
    """Run the Extractor → Summariser → Titler pipeline on the stored article."""
    article = tool_context.state.get("article", _DEFAULT_ARTICLE)

    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="seq_inner",
        user_id="inner_user",
        state={"article": article},
    )

    extractor = LlmAgent(
        name="Extractor",
        model=MODEL,
        instruction=(
            "Extract the 5 most important keywords from this text. "
            "Return them as a comma-separated list, nothing else.\n\n"
            "Text: {article}"
        ),
        output_key="keywords",
    )
    summariser = LlmAgent(
        name="Summariser",
        model=MODEL,
        instruction=(
            "Write a 2-sentence summary of the article. "
            "You must include these keywords: {keywords}\n\n"
            "Article: {article}"
        ),
        output_key="summary",
    )
    titler = LlmAgent(
        name="Titler",
        model=MODEL,
        instruction=(
            "Generate a concise, catchy title (max 10 words) for this summary. "
            "Return only the title text, nothing else.\n\n"
            "{summary}"
        ),
        output_key="title",
    )
    pipeline = SequentialAgent(
        name="ArticlePipeline",
        sub_agents=[extractor, summariser, titler],
    )
    runner = Runner(agent=pipeline, app_name="seq_inner", session_service=session_service)
    async for _ in runner.run_async(
        user_id="inner_user",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part.from_text(text="process")]),
    ):
        pass

    updated = await session_service.get_session(
        app_name="seq_inner", user_id="inner_user", session_id=session.id
    )
    tool_context.state["pipeline_keywords"] = updated.state.get("keywords", "")
    tool_context.state["pipeline_summary"] = updated.state.get("summary", "")
    tool_context.state["pipeline_title"] = updated.state.get("title", "")
    return "Pipeline complete. Call show_results() to see the output."


def show_results(tool_context: ToolContext) -> str:
    """Display the pipeline results stored in session state."""
    kw = tool_context.state.get("pipeline_keywords", "(not run yet)")
    su = tool_context.state.get("pipeline_summary", "(not run yet)")
    ti = tool_context.state.get("pipeline_title", "(not run yet)")
    return f"Keywords : {kw}\n\nSummary  : {su}\n\nTitle    : {ti}"


root_agent = LlmAgent(
    name="sequential_pipeline_agent",
    model=MODEL,
    instruction=_INSTRUCTION,
    tools=[set_article, run_pipeline, show_results],
    output_key="last_response",
)
