README_START = "<!-- AUTOGEN:method-table START -->"
README_END = "<!-- AUTOGEN:method-table END -->"
LLMS_START = "<!-- AUTOGEN:method-list START -->"
LLMS_END = "<!-- AUTOGEN:method-list END -->"

METHOD_DOCSTRINGS = {
    "check": "Check the checkbox matching `selector`.",
    "uncheck": "Uncheck the checkbox matching `selector`.",
    "cookies": "Return the cookies on the page.",
    "content": "Return the full HTML content of the page as a string.",
    "watch_event": (
        "Start tracking `event` now so a later `wait_for_event` call can return "
        "immediately if that event has already fired."
    ),
    "eval_on_selector": (
        "Return the text content of the first element matching `selector`. "
        "Unlike Playwright's `eval_on_selector`, this takes no page function: "
        "it is a shortcut for `text(selector=...)`."
    ),
    "eval_on_selector_all": (
        "Return details (`innerHTML`, `innerText`, `id`, `class`) for every element "
        "matching `selector`. Unlike Playwright's `eval_on_selector_all`, this "
        "takes no page function: it is a shortcut for `map_selector(selector)`."
    ),
    "query_selector": (
        "Return a handle for the first element matching `selector`, or `None`. "
        "The element's `innerHTML`/`outerHTML` are fetched only with `html=True`."
    ),
    "query_selector_all": (
        "Return handles for every element matching `selector`. "
        "The elements' `innerHTML`/`outerHTML` are fetched only with `html=True`."
    ),
}


def lead_prose(description: str | None) -> str | None:
    if not description:
        return None
    markers = (
        "```",
        "**Usage Example",
        "**Field Definition",
        "**Simple Example",
        "**Advanced",
        "Simple Example",
        "Advanced Example",
        "Example (",
        "**Usage",
        "**Example",
    )
    end = min(
        (description.index(marker) for marker in markers if marker in description),
        default=len(description),
    )
    return description[:end].strip() or None
