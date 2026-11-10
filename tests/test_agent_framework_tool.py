# SPDX-FileCopyrightText: 2026-present You.com <developers@you.com>
#
# SPDX-License-Identifier: Apache-2.0

from unittest.mock import patch

import pytest
from semantic_kernel.exceptions import ServiceInitializationError

from youcom_semantic_kernel import YouSearch
from youcom_semantic_kernel.you_search import DEFAULT_TOOL_NAME, KEYED_URL, KEYLESS_URL

from .test_you_search import make_client_mock


@pytest.fixture()
def clean_env(monkeypatch):
    monkeypatch.delenv("YDC_API_KEY", raising=False)


agent_framework = pytest.importorskip("agent_framework")


async def call(tool, **arguments) -> str:
    return await tool.invoke(arguments=arguments, skip_parsing=True)


def test_returns_function_tool_with_defaults(clean_env):
    tool = YouSearch().as_agent_framework_tool()
    assert isinstance(tool, agent_framework.FunctionTool)
    assert tool.name == DEFAULT_TOOL_NAME
    assert "You.com" in tool.description
    assert tool.approval_mode == "never_require"


def test_schema_exposes_query_count_freshness_only(clean_env):
    tool = YouSearch().as_agent_framework_tool(name="web_search", description="Search.", country="US")
    spec = tool.to_json_schema_spec()["function"]
    assert spec["name"] == "web_search"
    assert spec["description"] == "Search."
    assert set(spec["parameters"]["properties"]) == {"query", "count", "freshness"}
    assert spec["parameters"]["required"] == ["query"]


@pytest.mark.parametrize("top", [0, -1, 101])
def test_invalid_top_rejected(clean_env, top):
    with pytest.raises(ServiceInitializationError, match="top must be between"):
        YouSearch().as_agent_framework_tool(top=top)


async def test_invoke_formats_results_with_urls(clean_env):
    tool = YouSearch().as_agent_framework_tool()
    context, client = make_client_mock()
    with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
        text = await call(tool, query="what is semantic kernel")

    assert text == (
        "1. Semantic Kernel documentation\n"
        "URL: https://learn.microsoft.com/semantic-kernel\n"
        "Published: 2026-07-01T00:00:00\n"
        "Semantic Kernel is a lightweight SDK\n"
        "for building AI agents\n"
        "\n"
        "2. AI news item\n"
        "URL: https://example.com/news\n"
        "Published: 2026-07-20T00:00:00\n"
        "A news description"
    )
    args, kwargs = client.get.call_args
    assert args[0] == KEYLESS_URL
    assert kwargs["params"] == {"query": "what is semantic kernel", "count": 5}


async def test_invoke_applies_fixed_and_default_parameters(clean_env):
    tool = YouSearch(api_key="k").as_agent_framework_tool(
        top=3, freshness="month", country="DE", language="DE", safesearch="strict"
    )
    context, client = make_client_mock()
    with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
        await call(tool, query="q")

    args, kwargs = client.get.call_args
    assert args[0] == KEYED_URL
    assert kwargs["headers"]["X-API-Key"] == "k"
    assert kwargs["params"] == {
        "query": "q",
        "count": 3,
        "freshness": "month",
        "country": "DE",
        "language": "DE",
        "safesearch": "strict",
    }


async def test_model_arguments_override_defaults(clean_env):
    tool = YouSearch().as_agent_framework_tool(top=3, freshness="month")
    context, client = make_client_mock()
    with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
        await call(tool, query="q", count=8, freshness="day")

    assert client.get.call_args.kwargs["params"] == {"query": "q", "count": 8, "freshness": "day"}


async def test_count_out_of_range_is_rejected_before_any_request(clean_env):
    tool = YouSearch().as_agent_framework_tool()
    context, client = make_client_mock()
    with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
        with pytest.raises(TypeError, match="less than or equal to 100"):
            await call(tool, query="q", count=500)
    client.get.assert_not_called()


async def test_empty_results_message(clean_env):
    tool = YouSearch().as_agent_framework_tool()
    context, _ = make_client_mock(body='{"results": {"web": [], "news": []}}')
    with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
        assert await call(tool, query="q") == "No results found."


async def test_sparse_hit_falls_back_to_url_and_description(clean_env):
    tool = YouSearch().as_agent_framework_tool()
    body = '{"results": {"web": [{"url": "https://example.com/a", "description": "Only a description"}]}}'
    context, _ = make_client_mock(body=body)
    with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
        text = await call(tool, query="q")
    assert text == "1. https://example.com/a\nURL: https://example.com/a\nOnly a description"


@pytest.mark.parametrize("status_code", [402, 429])
async def test_keyless_rate_limit_is_returned_to_the_model(clean_env, status_code):
    tool = YouSearch().as_agent_framework_tool()
    context, _ = make_client_mock(body="{}", status_code=status_code)
    with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
        text = await call(tool, query="q")
    assert text.startswith("You.com search failed:")
    assert "YDC_API_KEY" in text


async def test_server_error_is_returned_to_the_model(clean_env):
    tool = YouSearch(api_key="k").as_agent_framework_tool()
    context, _ = make_client_mock(body="{}", status_code=500)
    with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
        assert await call(tool, query="q") == "You.com search failed: Failed to get search results."


async def test_default_parsing_returns_one_text_content(clean_env):
    """Without skip_parsing, Agent Framework wraps the result the way its tool loop does."""
    tool = YouSearch().as_agent_framework_tool()
    context, client = make_client_mock()
    with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
        contents = await tool.invoke(arguments={"query": "q", "count": 2}, tool_call_id="call_1")

    assert client.get.call_args.kwargs["params"]["count"] == 2
    assert len(contents) == 1
    assert contents[0].type == "text"
    assert "URL: https://learn.microsoft.com/semantic-kernel" in contents[0].text


@pytest.mark.integration
async def test_agent_framework_tool_live(clean_env):
    tool = YouSearch().as_agent_framework_tool(top=3)
    text = await call(tool, query="What is Microsoft Agent Framework?")
    assert "URL: http" in text
