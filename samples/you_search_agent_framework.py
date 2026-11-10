# SPDX-FileCopyrightText: 2026-present You.com <developers@you.com>
#
# SPDX-License-Identifier: Apache-2.0

"""Use You.com web search as a tool in a Microsoft Agent Framework agent.

No Kernel or plugin is involved: `as_agent_framework_tool()` returns a tool that
goes straight into `Agent(tools=[...])`.

No You.com API key is required to run this sample. Searches default to the
keyless free tier. Set YDC_API_KEY for higher limits. An OpenAI key is needed
for the chat model (OPENAI_API_KEY / OPENAI_CHAT_MODEL_ID).

    pip install 'youcom-semantic-kernel[agent-framework]' agent-framework-openai
"""

import asyncio

from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient

from youcom_semantic_kernel import YouSearch

agent = Agent(
    client=OpenAIChatClient(),
    name="researcher",
    instructions=(
        "You answer questions using real-time web search via You.com. Cite the URL of every source you rely on."
    ),
    # The model picks the query, result count, and freshness. Country is fixed here.
    tools=[YouSearch().as_agent_framework_tool(top=5, country="US")],
)


async def main() -> None:
    print("Ask me anything that needs fresh web results (type 'exit' to quit).")
    session = agent.create_session()
    while True:
        try:
            user_input = input("User:> ")
        except (KeyboardInterrupt, EOFError):
            break
        if user_input.lower().strip() == "exit":
            break
        response = await agent.run(user_input, session=session)
        print(f"Assistant:> {response.text}")


if __name__ == "__main__":
    asyncio.run(main())
