# SPDX-FileCopyrightText: 2026-present You.com <developers@you.com>
#
# SPDX-License-Identifier: Apache-2.0

import ast
import logging
import sys
from collections.abc import AsyncIterable, Callable
from importlib.metadata import PackageNotFoundError, version
from inspect import getsource
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Final, Literal

from httpx import AsyncClient, HTTPStatusError, RequestError
from pydantic import Field, SecretStr, ValidationError
from semantic_kernel.data.text_search import (
    KernelSearchResults,
    SearchOptions,
    TextSearch,
    TextSearchResult,
    TSearchResult,
)
from semantic_kernel.exceptions import ServiceInitializationError, ServiceInvalidRequestError
from semantic_kernel.kernel_pydantic import KernelBaseModel, KernelBaseSettings
from semantic_kernel.kernel_types import OptionalOneOrList

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from agent_framework import FunctionTool

logger: logging.Logger = logging.getLogger(__name__)

# region Constants
KEYED_URL: Final[str] = "https://ydc-index.io/v1/search"
KEYLESS_URL: Final[str] = "https://api.you.com/v1/agents/search"

QUERY_PARAMETERS: Final[list[str]] = [
    "country",
    "language",
    "safesearch",
    "freshness",
]

try:
    _VERSION = version("youcom-semantic-kernel")
except PackageNotFoundError:  # pragma: no cover
    _VERSION = "0.0.0-dev"

USER_AGENT: Final[str] = f"youcom-semantic-kernel/{_VERSION}"

MAX_TOP: Final[int] = 100
MAX_SKIP: Final[int] = 9

_RATE_LIMIT_STATUSES: Final[tuple[int, ...]] = (402, 429)
_UPGRADE_HINT: Final[str] = (
    "You.com keyless free-tier limit reached. Set the YDC_API_KEY environment variable "
    "(or pass api_key) for higher limits - get a free API key at https://you.com/platform."
)

DEFAULT_TOOL_NAME: Final[str] = "you_search"
DEFAULT_TOOL_DESCRIPTION: Final[str] = (
    "Search the web with You.com for current information. Returns a numbered list of results, "
    "each with a title, a URL to cite, and text snippets from the page."
)
_AGENT_FRAMEWORK_HINT: Final[str] = (
    "Microsoft Agent Framework is not installed. Install it with "
    "`pip install 'youcom-semantic-kernel[agent-framework]'` (requires Python 3.11 or newer)."
)
# endregion Constants


# region YouSettings
class YouSettings(KernelBaseSettings):
    """You.com Search connector settings.

    The settings are first loaded from environment variables with the prefix 'YDC_'. If the
    environment variables are not found, the settings can be loaded from a .env file with the
    encoding 'utf-8'.

    Optional settings for prefix 'YDC_' are:
    - api_key: SecretStr | None - The You.com API key (Env var YDC_API_KEY). When not set,
      the connector uses You.com's keyless free tier (rate limited per IP), so no
      configuration is required to get started.
    """

    env_prefix: ClassVar[str] = "YDC_"

    api_key: SecretStr | None = None


# endregion YouSettings


# region You.com response models
class YouWebPage(KernelBaseModel):
    """A You.com web search result."""

    url: str | None = None
    title: str | None = None
    description: str | None = None
    snippets: list[str] | None = None
    page_age: str | None = None
    thumbnail_url: str | None = None
    favicon_url: str | None = None


class YouNewsResult(KernelBaseModel):
    """A You.com news search result."""

    url: str | None = None
    title: str | None = None
    description: str | None = None
    page_age: str | None = None
    thumbnail_url: str | None = None


class YouSearchResults(KernelBaseModel):
    """The result sections of a You.com search response."""

    web: list[YouWebPage] = Field(default_factory=list)
    news: list[YouNewsResult] = Field(default_factory=list)


class YouSearchResponse(KernelBaseModel):
    """The response from a You.com search."""

    results: YouSearchResults = Field(default_factory=YouSearchResults)
    metadata: dict[str, Any] | None = None


# endregion You.com response models


class YouSearch(KernelBaseModel, TextSearch):
    """A search connector that uses the You.com Search API to perform a web search.

    Works with zero configuration: when no API key is available, searches use You.com's
    keyless free tier (rate limited per IP). Set the `YDC_API_KEY` environment variable
    (or pass `api_key`) to use the keyed You.com Search API with higher limits.
    """

    settings: YouSettings
    timeout: float = 10.0

    def __init__(
        self,
        api_key: str | None = None,
        env_file_path: str | None = None,
        env_file_encoding: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        """Initializes a new instance of the You.com Search class.

        Args:
            api_key: The You.com API key. If provided, will override
                the value in the env vars or .env file. When no key is available
                anywhere, the keyless free tier is used.
            env_file_path: The optional path to the .env file. If provided,
                the settings are read from this file path location.
            env_file_encoding: The optional encoding of the .env file.
            timeout: Timeout in seconds for the HTTP request. Defaults to 10.
        """
        try:
            settings = YouSettings(
                api_key=SecretStr(api_key) if api_key else None,
                env_file_path=env_file_path,
                env_file_encoding=env_file_encoding,
            )
        except ValidationError as ex:
            raise ServiceInitializationError("Failed to create You.com settings.") from ex

        super().__init__(settings=settings, timeout=timeout)  # type: ignore[call-arg]

    @override
    async def search(
        self,
        query: str,
        output_type: type[str] | type[TSearchResult] | Literal["Any"] = str,
        *,
        filter: OptionalOneOrList[Callable | str] = None,
        skip: int = 0,
        top: int = 5,
        include_total_count: bool = False,
        **kwargs: Any,
    ) -> "KernelSearchResults[TSearchResult]":
        """Search the web using the You.com Search API."""
        try:
            options = SearchOptions(
                filter=filter, skip=skip, top=top, include_total_count=include_total_count, **kwargs
            )
        except ValidationError as ex:
            raise ServiceInvalidRequestError("Invalid search options.") from ex
        results = await self._inner_search(query=query, options=options)
        return KernelSearchResults(
            results=self._get_result_strings(results)  # type: ignore[arg-type]
            if output_type is str
            else self._get_text_search_results(results)
            if output_type is TextSearchResult
            else self._get_you_web_pages(results),
            total_count=self._get_total_count(results, options),
            metadata=self._get_metadata(results),
        )

    def as_agent_framework_tool(
        self,
        name: str = DEFAULT_TOOL_NAME,
        description: str = DEFAULT_TOOL_DESCRIPTION,
        *,
        top: int = 5,
        freshness: str | None = None,
        country: str | None = None,
        language: str | None = None,
        safesearch: str | None = None,
        approval_mode: Literal["always_require", "never_require"] = "never_require",
        max_invocations: int | None = None,
    ) -> "FunctionTool":
        """Create a Microsoft Agent Framework tool backed by this connector.

        Agent Framework is the successor to Semantic Kernel's agent APIs. The returned
        ``FunctionTool`` goes straight into ``Agent(tools=[...])``, with no ``Kernel``,
        plugin, or ``KernelParameterMetadata`` needed. The model can set ``query``,
        ``count``, and ``freshness``; everything else is fixed here by the developer.

        Results come back as a numbered list with the title, URL, and snippets of each
        hit, so the model has the source links it needs to cite. Search failures
        (including the keyless free-tier limit) are returned to the model as text
        instead of raising, so one failed search does not end the agent run.

        Args:
            name: The tool name shown to the model.
            description: The tool description shown to the model.
            top: Default number of results when the model does not pass ``count`` (1 to 100).
            freshness: Default freshness (``day``, ``week``, ``month``, ``year``, or
                ``YYYY-MM-DDtoYYYY-MM-DD``) when the model does not pass one.
            country: 2-letter country code applied to every search.
            language: Result language (BCP 47) applied to every search.
            safesearch: ``off``, ``moderate``, or ``strict``, applied to every search.
            approval_mode: Agent Framework approval mode. Web search is read-only, so the
                default is ``never_require``.
            max_invocations: Optional cap on how many times the tool may be called over
                its lifetime. Useful for staying inside the keyless free tier.

        Returns:
            An ``agent_framework.FunctionTool``.

        Raises:
            ServiceInitializationError: If Agent Framework is not installed, or ``top``
                is out of range.
        """
        try:
            from agent_framework import tool  # noqa: PLC0415 - optional dependency, imported on use
        except ImportError as ex:
            raise ServiceInitializationError(_AGENT_FRAMEWORK_HINT) from ex

        if not 1 <= top <= MAX_TOP:
            raise ServiceInitializationError(f"top must be between 1 and {MAX_TOP}.")

        fixed: dict[str, str | int] = {
            key: value
            for key, value in (("country", country), ("language", language), ("safesearch", safesearch))
            if value
        }
        default_freshness = freshness

        async def you_search(
            query: Annotated[str, "The search query."],
            count: Annotated[
                int | None, Field(description="Number of results to return. Omit for the default.", ge=1, le=MAX_TOP)
            ] = None,
            freshness: Annotated[
                str | None,
                "Only return results from this period: day, week, month, year, "
                "or a date range written as YYYY-MM-DDtoYYYY-MM-DD. Omit for any time.",
            ] = None,
        ) -> str:
            params: dict[str, str | int] = {"query": query, "count": count or top, **fixed}
            period = freshness or default_freshness
            if period:
                params["freshness"] = period
            try:
                response = await self._send(params)
            except ServiceInvalidRequestError as ex:
                return f"You.com search failed: {ex}"
            return self._format_for_agent(response)

        return tool(
            you_search,
            name=name,
            description=description,
            approval_mode=approval_mode,
            max_invocations=max_invocations,
        )

    def _format_for_agent(self, response: YouSearchResponse) -> str:
        blocks: list[str] = []
        for web_page in response.results.web:
            blocks.append(self._format_hit(len(blocks) + 1, web_page, self._page_content(web_page)))
        for news_result in response.results.news:
            blocks.append(self._format_hit(len(blocks) + 1, news_result, news_result.description or ""))
        return "\n\n".join(blocks) if blocks else "No results found."

    @staticmethod
    def _format_hit(index: int, hit: YouWebPage | YouNewsResult, content: str) -> str:
        lines = [f"{index}. {hit.title or hit.url or 'Untitled'}"]
        if hit.url:
            lines.append(f"URL: {hit.url}")
        if hit.page_age:
            lines.append(f"Published: {hit.page_age}")
        if content:
            lines.append(content)
        return "\n".join(lines)

    async def _get_result_strings(self, response: YouSearchResponse) -> AsyncIterable[str]:
        for web_page in response.results.web:
            yield self._page_content(web_page)
        for news_result in response.results.news:
            yield news_result.description or ""

    async def _get_text_search_results(self, response: YouSearchResponse) -> AsyncIterable[TextSearchResult]:
        for web_page in response.results.web:
            yield TextSearchResult(
                name=web_page.title,
                value=self._page_content(web_page),
                link=web_page.url,
            )
        for news_result in response.results.news:
            yield TextSearchResult(
                name=news_result.title,
                value=news_result.description,
                link=news_result.url,
            )

    async def _get_you_web_pages(self, response: YouSearchResponse) -> AsyncIterable[YouWebPage]:
        for val in response.results.web:
            yield val

    @staticmethod
    def _page_content(web_page: YouWebPage) -> str:
        if web_page.snippets:
            return "\n".join(web_page.snippets)
        return web_page.description or ""

    def _get_metadata(self, response: YouSearchResponse) -> dict[str, Any]:
        metadata = response.metadata or {}
        return {
            "query": metadata.get("query"),
            "search_uuid": metadata.get("search_uuid"),
            "latency": metadata.get("latency"),
        }

    def _get_total_count(self, response: YouSearchResponse, options: SearchOptions) -> int | None:
        if options.include_total_count:
            return len(response.results.web) + len(response.results.news)
        return None

    def _keyless(self) -> bool:
        return self.settings.api_key is None

    async def _inner_search(self, query: str, options: SearchOptions) -> YouSearchResponse:
        self._validate_options(options)
        return await self._send(self._build_request_parameters(query, options))

    async def _send(self, params: dict[str, str | int]) -> YouSearchResponse:
        url = KEYLESS_URL if self._keyless() else KEYED_URL

        logger.info(f"Sending GET request to {url}")

        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if not self._keyless() and self.settings.api_key is not None:
            headers["X-API-Key"] = self.settings.api_key.get_secret_value()

        try:
            async with AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
                return YouSearchResponse.model_validate_json(response.text)
        except HTTPStatusError as ex:
            logger.error(f"Failed to get search results: {ex}")
            if self._keyless() and ex.response.status_code in _RATE_LIMIT_STATUSES:
                raise ServiceInvalidRequestError(_UPGRADE_HINT) from ex
            raise ServiceInvalidRequestError("Failed to get search results.") from ex
        except RequestError as ex:
            logger.error(f"Client error occurred: {ex}")
            raise ServiceInvalidRequestError("A client error occurred while getting search results.") from ex
        except Exception as ex:
            logger.error(f"An unexpected error occurred: {ex}")
            raise ServiceInvalidRequestError("An unexpected error occurred while getting search results.") from ex

    def _validate_options(self, options: SearchOptions) -> None:
        if options.top <= 0:
            raise ServiceInvalidRequestError("top value must be greater than 0.")
        if options.top > MAX_TOP:
            raise ServiceInvalidRequestError(f"top value must be {MAX_TOP} or less.")
        if options.skip < 0:
            raise ServiceInvalidRequestError("skip must be greater than or equal to 0.")
        if options.skip > MAX_SKIP:
            raise ServiceInvalidRequestError(f"skip must be less than {MAX_SKIP + 1}.")

    def _parse_filter_lambda(self, filter_lambda: Callable | str) -> list[dict[str, str]]:
        """Parse a lambda or string expression into a list of {field: value} dicts using AST.

        Supports equality comparisons on allowed query parameters, optionally
        combined with `and`, e.g. `lambda x: x.country == "US" and x.freshness == "week"`.
        """
        expr = filter_lambda if isinstance(filter_lambda, str) else getsource(filter_lambda).strip()
        tree = ast.parse(expr, mode="eval")
        node = tree.body
        if isinstance(node, ast.Lambda):
            node = node.body

        comparisons: list[ast.Compare] = []
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
            for value in node.values:
                if not isinstance(value, ast.Compare):
                    msg = "Only equality comparisons combined with 'and' are supported in filters."
                    raise ValueError(msg)
                comparisons.append(value)
        elif isinstance(node, ast.Compare):
            comparisons.append(node)
        else:
            msg = "Unsupported filter expression; use e.g. lambda x: x.country == 'US'."
            raise ValueError(msg)

        filters: list[dict[str, str]] = []
        for comp in comparisons:
            if not (len(comp.ops) == 1 and isinstance(comp.ops[0], ast.Eq)):
                msg = "Only '==' comparisons are supported in filters."
                raise ValueError(msg)
            left, right = comp.left, comp.comparators[0]
            if not (isinstance(left, ast.Attribute) and isinstance(right, ast.Constant)):
                msg = "Filters must compare a field to a constant, e.g. x.country == 'US'."
                raise ValueError(msg)
            field = left.attr
            if field not in QUERY_PARAMETERS:
                msg = f"Unknown filter field '{field}'; allowed: {QUERY_PARAMETERS}."
                raise ValueError(msg)
            filters.append({field: str(right.value)})
        return filters

    def _build_request_parameters(self, query: str, options: SearchOptions) -> dict[str, str | int]:
        params: dict[str, str | int] = {"query": query or "", "count": options.top, "offset": options.skip}
        if not options.filter:
            return params
        filters = options.filter
        if not isinstance(filters, list):
            filters = [filters]
        for f in filters:
            try:
                for d in self._parse_filter_lambda(f):
                    for field, value in d.items():
                        params[field] = value
            except Exception as exc:
                logger.warning(f"Failed to parse filter lambda: {f}, ignoring this filter. Error: {exc}")
                continue
        return params
