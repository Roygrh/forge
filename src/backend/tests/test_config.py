"""Settings parsing.

``CORS_ORIGINS`` earns a test because it broke in the one place tests do not run: the
container. pydantic-settings JSON-decodes list-typed fields straight off the
environment, so a comma-separated value raised at import time and took the API down
before a single request. The fix is a field annotation, which is exactly the kind of
thing that gets refactored away without a test standing on it.
"""

import pytest

from app.config import Settings


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://localhost:5173", ["http://localhost:5173"]),
        (
            "http://localhost:5173,http://127.0.0.1:5173",
            ["http://localhost:5173", "http://127.0.0.1:5173"],
        ),
        # Whitespace and a trailing comma are what a hand-edited compose file looks like.
        (" http://a , http://b ,", ["http://a", "http://b"]),
    ],
)
def test_cors_origins_are_comma_separated(value: str, expected: list[str]) -> None:
    assert Settings(cors_origins=value).cors_origins == expected  # type: ignore[arg-type]


def test_cors_origins_default_to_the_documented_dev_ports() -> None:
    """A wildcard would be one fewer line and a worse answer."""
    assert Settings().cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]
