# youcom-semantic-kernel

[![PyPI - Version](https://img.shields.io/pypi/v/youcom-semantic-kernel.svg)](https://pypi.org/project/youcom-semantic-kernel)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/youcom-semantic-kernel.svg)](https://pypi.org/project/youcom-semantic-kernel)

[You.com](https://you.com) web search for [Semantic Kernel](https://github.com/microsoft/semantic-kernel) (Python), implementing SK's `TextSearch` abstraction.

Works with **zero configuration**: without an API key, searches use You.com's keyless free tier (rate limited per IP), so you can evaluate the connector without provisioning keys. Set the `YDC_API_KEY` environment variable to use the keyed [You.com Search API](https://you.com/docs/api-reference/search/v1-search) with higher limits — get a free key at [you.com/platform](https://you.com/platform).

## Installation

```bash
pip install youcom-semantic-kernel
```

## Usage

### Direct search

```python
from semantic_kernel.data.text_search import TextSearchResult
from youcom_semantic_kernel import YouSearch

search = YouSearch()  # no API key needed to get started
results = await search.search("What is Semantic Kernel?", output_type=TextSearchResult, top=5)
async for result in results.results:
    print(result.name, result.link)
    print(result.value)
```

### As a kernel plugin (function calling)

```python
from semantic_kernel import Kernel
from semantic_kernel.functions import KernelParameterMetadata
from youcom_semantic_kernel import YouSearch

kernel = Kernel()
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
```

### Filters

Restrict searches with equality filters on `country`, `language`, `safesearch`, or `freshness`:

```python
results = await search.search("AI news", filter='lambda x: x.country == "US" and x.freshness == "week"')
```

## Configuration

| Setting | Env var | Default | Description |
| --- | --- | --- | --- |
| `api_key` | `YDC_API_KEY` | `None` | You.com API key. When unset, the keyless free tier is used. Also loadable from a `.env` file via `env_file_path`. |
| `timeout` | — | `10.0` | HTTP timeout in seconds. |

`search()` supports `output_type` of `str` (result text), `TextSearchResult` (name/value/link), or `"Any"` (raw `YouWebPage` models), plus `top` (1–100), `skip` (0–9), and `include_total_count`.

## Rate limits

Without an API key, requests use the keyless endpoint (currently 100 searches/day per IP). When the limit is reached, the connector raises a `ServiceInvalidRequestError` explaining how to upgrade.

## License

Apache-2.0
