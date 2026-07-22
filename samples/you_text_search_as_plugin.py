# SPDX-FileCopyrightText: 2026-present You.com <developers@you.com>
#
# SPDX-License-Identifier: Apache-2.0

"""Use You.com web search as a Semantic Kernel plugin in a chat loop.

No You.com API key is required to run this sample — searches default to the
keyless free tier. Set YDC_API_KEY for higher limits. An OpenAI key is needed
for the chat model (OPENAI_API_KEY / OPENAI_CHAT_MODEL_ID).
"""

import asyncio

from semantic_kernel import Kernel
from semantic_kernel.connectors.ai import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion, OpenAIChatPromptExecutionSettings
from semantic_kernel.contents import ChatHistory
from semantic_kernel.functions import KernelArguments, KernelParameterMetadata

from youcom_semantic_kernel import YouSearch

kernel = Kernel()
kernel.add_service(OpenAIChatCompletion(service_id="chat"))
kernel.add_function(
    plugin_name="you",
    function=YouSearch().create_search_function(
        function_name="you_search",
        description="Search the web for up-to-date information with You.com.",
        parameters=[
            KernelParameterMetadata(
                name="query", description="The search query.", type="str", is_required=True, type_object=str
            ),
            KernelParameterMetadata(
                name="top", description="Number of results to return.", type="int", default_value=5, type_object=int
            ),
        ],
    ),
)

settings = OpenAIChatPromptExecutionSettings(
    service_id="chat",
    function_choice_behavior=FunctionChoiceBehavior.Auto(),
)
history = ChatHistory()
history.add_system_message("You are a helpful assistant with access to real-time web search via You.com.")


async def chat() -> bool:
    try:
        user_input = input("User:> ")
    except (KeyboardInterrupt, EOFError):
        return False
    if user_input.lower().strip() == "exit":
        return False

    history.add_user_message(user_input)
    result = await kernel.invoke_prompt(
        prompt="{{$chat_history}}",
        arguments=KernelArguments(chat_history=history, settings=settings),
    )
    history.add_assistant_message(str(result))
    print(f"Assistant:> {result}")
    return True


async def main() -> None:
    print("Ask me anything that needs fresh web results (type 'exit' to quit).")
    while await chat():
        pass


if __name__ == "__main__":
    asyncio.run(main())
