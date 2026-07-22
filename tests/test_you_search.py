# SPDX-FileCopyrightText: 2026-present You.com <developers@you.com>
#
# SPDX-License-Identifier: Apache-2.0

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import HTTPStatusError, Request, Response
from semantic_kernel.data.text_search import TextSearchResult
from semantic_kernel.exceptions import ServiceInvalidRequestError

from youcom_semantic_kernel import YouSearch, YouSettings
from youcom_semantic_kernel.you_search import KEYED_URL, KEYLESS_URL, USER_AGENT

SAMPLE_BODY = """
{
    "results": {
        "web": [
            {
                "url": "https://learn.microsoft.com/semantic-kernel",
                "title": "Semantic Kernel documentation",
                "description": "Build AI agents with Semantic Kernel",
                "snippets": ["Semantic Kernel is a lightweight SDK", "for building AI agents"],
                "page_age": "2026-07-01T00:00:00"
            }
        ],
        "news": [
            {
                "url": "https://example.com/news",
                "title": "AI news item",
                "description": "A news description",
                "page_age": "2026-07-20T00:00:00"
            }
        ]
    },
    "metadata": {"query": "test", "search_uuid": "abc-123", "latency": 0.12}
}
"""


@pytest.fixture()
def clean_env(monkeypatch):
    monkeypatch.delenv("YDC_API_KEY", raising=False)


def make_client_mock(body: str = SAMPLE_BODY, status_code: int = 200):
    """Mock httpx.AsyncClient context manager returning a canned response."""
    response = Response(
        status_code=status_code,
        text=body,
        request=Request("GET", "https://unit.test"),
    )
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return context, client


class TestYouSettings:
    def test_no_key_is_allowed(self, clean_env):
        settings = YouSettings()
        assert settings.api_key is None

    def test_env_var_key(self, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "env-key")
        settings = YouSettings()
        assert settings.api_key.get_secret_value() == "env-key"


class TestYouSearch:
    async def test_keyless_url_and_no_key_header(self, clean_env):
        context, client = make_client_mock()
        with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
            search = YouSearch()
            await search.search("test query")

        call = client.get.call_args
        assert call.args[0] == KEYLESS_URL
        assert "X-API-Key" not in call.kwargs["headers"]

    async def test_keyed_url_and_key_header(self, clean_env):
        context, client = make_client_mock()
        with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
            search = YouSearch(api_key="explicit-key")
            await search.search("test query")

        call = client.get.call_args
        assert call.args[0] == KEYED_URL
        assert call.kwargs["headers"]["X-API-Key"] == "explicit-key"

    async def test_env_key_used(self, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "env-key")
        context, client = make_client_mock()
        with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
            search = YouSearch()
            await search.search("q")

        assert client.get.call_args.kwargs["headers"]["X-API-Key"] == "env-key"

    async def test_user_agent_sent(self, clean_env):
        context, client = make_client_mock()
        with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
            search = YouSearch()
            await search.search("q")

        headers = client.get.call_args.kwargs["headers"]
        assert headers["User-Agent"] == USER_AGENT
        assert USER_AGENT.startswith("youcom-semantic-kernel/")

    async def test_request_parameters(self, clean_env):
        context, client = make_client_mock()
        with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
            search = YouSearch()
            await search.search("semantic kernel", top=7, skip=2)

        params = client.get.call_args.kwargs["params"]
        assert params == {"query": "semantic kernel", "count": 7, "offset": 2}

    async def test_filter_lambda_maps_to_params(self, clean_env):
        context, client = make_client_mock()
        with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
            search = YouSearch()
            await search.search("q", filter='lambda x: x.country == "US" and x.freshness == "week"')

        params = client.get.call_args.kwargs["params"]
        assert params["country"] == "US"
        assert params["freshness"] == "week"

    async def test_invalid_filter_field_is_ignored(self, clean_env):
        context, client = make_client_mock()
        with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
            search = YouSearch()
            await search.search("q", filter='lambda x: x.bogus == "nope"')

        params = client.get.call_args.kwargs["params"]
        assert "bogus" not in params

    async def test_string_results(self, clean_env):
        context, _ = make_client_mock()
        with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
            search = YouSearch()
            results = await search.search("q", output_type=str)
            strings = [r async for r in results.results]

        assert strings == [
            "Semantic Kernel is a lightweight SDK\nfor building AI agents",
            "A news description",
        ]

    async def test_text_search_results(self, clean_env):
        context, _ = make_client_mock()
        with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
            search = YouSearch()
            results = await search.search("q", output_type=TextSearchResult)
            items = [r async for r in results.results]

        assert len(items) == 2
        assert items[0].name == "Semantic Kernel documentation"
        assert items[0].link == "https://learn.microsoft.com/semantic-kernel"
        assert items[1].name == "AI news item"

    async def test_total_count_and_metadata(self, clean_env):
        context, _ = make_client_mock()
        with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
            search = YouSearch()
            results = await search.search("q", include_total_count=True)

        assert results.total_count == 2
        assert results.metadata["search_uuid"] == "abc-123"

    async def test_total_count_none_by_default(self, clean_env):
        context, _ = make_client_mock()
        with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
            search = YouSearch()
            results = await search.search("q")

        assert results.total_count is None

    @pytest.mark.parametrize(
        ("top", "skip", "message"),
        [
            (0, 0, "Invalid search options"),
            (101, 0, "top value must be 100 or less"),
            (5, -1, "Invalid search options"),
            (5, 10, "skip must be less than 10"),
        ],
    )
    async def test_option_validation(self, clean_env, top, skip, message):
        search = YouSearch()
        with pytest.raises(ServiceInvalidRequestError, match=message):
            await search.search("q", top=top, skip=skip)

    async def test_keyless_rate_limit_hint(self, clean_env):
        context, client = make_client_mock(body='{"error": "rate_limit_exceeded"}', status_code=402)
        response = client.get.return_value
        client.get = AsyncMock(side_effect=HTTPStatusError("402", request=response.request, response=response))
        context.__aenter__ = AsyncMock(return_value=client)
        with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
            search = YouSearch()
            with pytest.raises(ServiceInvalidRequestError, match="YDC_API_KEY"):
                await search.search("q")

    async def test_keyed_error_no_hint(self, clean_env):
        context, client = make_client_mock(body="unauthorized", status_code=401)
        response = client.get.return_value
        client.get = AsyncMock(side_effect=HTTPStatusError("401", request=response.request, response=response))
        context.__aenter__ = AsyncMock(return_value=client)
        with patch("youcom_semantic_kernel.you_search.AsyncClient", return_value=context):
            search = YouSearch(api_key="bad-key")
            with pytest.raises(ServiceInvalidRequestError, match="Failed to get search results"):
                await search.search("q")


@pytest.mark.integration
class TestYouSearchIntegration:
    async def test_keyless_live(self, monkeypatch):
        monkeypatch.delenv("YDC_API_KEY", raising=False)
        search = YouSearch()
        results = await search.search("What is Semantic Kernel?", output_type=TextSearchResult, top=2)
        items = [r async for r in results.results]
        assert len(items) > 0
        assert items[0].link

    @pytest.mark.skipif("YDC_API_KEY" not in os.environ, reason="YDC_API_KEY not set")
    async def test_keyed_live(self):
        search = YouSearch()
        results = await search.search("What is Semantic Kernel?", top=2)
        strings = [r async for r in results.results]
        assert len(strings) > 0
