"""
Demo 06: SequentialAgent — chained state passing via output_key.

SequentialAgent runs sub-agents in order, passing the same InvocationContext
(and therefore the same session.state) to each one. output_key stores each
agent's final response into state, and instruction templates {key} inject
those values into the next agent's prompt automatically.

Pipeline:
    ExtractKeywords  →  output_key="keywords"
    WriteSummary     →  reads {keywords}, output_key="summary"
    GenerateTitle    →  reads {summary}, output_key="title"

The article is seeded into session.state at creation time so the first
agent can reference it as {article}.

Run:
    GOOGLE_API_KEY=<key> python 06_sequential_pipeline.py
"""

import asyncio

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

MODEL = "gemini-2.0-flash"
APP_NAME = "sequential_demo"
USER_ID = "demo_user"

ARTICLE = (
    "Transformer neural networks, introduced in 'Attention Is All You Need' (2017), "
    "revolutionised NLP by replacing recurrent architectures with self-attention. "
    "They scale efficiently and power models like GPT and BERT, enabling breakthroughs "
    "in translation, summarisation, question answering, and code generation."
)


async def main() -> None:
    session_service = InMemorySessionService()

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
            "Write a 2-sentence summary of the following article. "
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
            "Return only the title text, nothing else.\n\n{summary}"
        ),
        output_key="title",
    )

    pipeline = SequentialAgent(
        name="ArticlePipeline",
        sub_agents=[extractor, summariser, titler],
    )

    runner = Runner(agent=pipeline, app_name=APP_NAME, session_service=session_service)

    # Seed the article into initial state so {article} resolves in the templates
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        state={"article": ARTICLE},
    )
    print(f"Initial state keys: {list(session.state.keys())}\n")

    async for _ in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=types.Content(
            role="user", parts=[types.Part.from_text(text="Process the article.")]
        ),
    ):
        pass  # consume events; inspect state afterwards

    updated = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    print("=== Pipeline results in session.state ===")
    print(f"\nkeywords:\n  {updated.state.get('keywords')}")
    print(f"\nsummary:\n  {updated.state.get('summary')}")
    print(f"\ntitle:\n  {updated.state.get('title')}")


if __name__ == "__main__":
    asyncio.run(main())
