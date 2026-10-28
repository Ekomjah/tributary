from __future__ import annotations

from tributary.services.text import (
    html_to_text,
    normalize_text,
    readable_title,
    sanitize_html,
    unescape_all,
)


def test_unescape_all_decodes_double_escaped_entities() -> None:
    assert unescape_all("It&amp;#8217;s &amp;amp; more") == "It\u2019s & more"


def test_normalize_text_uses_nfc_and_keeps_curly_apostrophes() -> None:
    assert normalize_text("Cafe\u0301") == "Caf\u00e9"
    assert normalize_text("It\u2019s") == "It\u2019s"


def test_html_to_text_strips_tags_and_decodes_entities() -> None:
    assert html_to_text("<p>It&#8217;s &amp; more</p>") == "It\u2019s & more"


def test_html_to_text_preserves_paragraph_boundaries() -> None:
    assert html_to_text("<p>One</p><p>Two</p>") == "One\n\nTwo"


def test_html_to_text_drops_scripts_and_styles() -> None:
    text = html_to_text("<p>Hello</p><script>alert(1)</script><style>p{}</style>")
    assert text == "Hello"


def test_readable_title_strips_markup_and_collapses_whitespace() -> None:
    assert readable_title("<b>Markup</b>\n  Feed") == "Markup Feed"
    assert readable_title("<p>It&#8217;s</p><p>fine</p>") == "It\u2019s fine"


def test_sanitize_html_strips_unsafe_markup_and_resolves_links() -> None:
    cleaned = sanitize_html(
        '<p onclick="steal()">Hi <a href="/about" target="_blank">about</a>'
        "<script>alert(1)</script><img src=x onerror=steal()></p>",
        base_url="https://example.com/posts/1",
    )

    assert cleaned is not None
    assert "onclick" not in cleaned
    assert "onerror" not in cleaned
    assert "<script" not in cleaned
    assert "<img" not in cleaned
    assert 'href="https://example.com/about"' in cleaned
    assert 'rel="noopener noreferrer"' in cleaned
    assert "target=" not in cleaned


def test_sanitize_html_drops_unsafe_links_and_forms() -> None:
    cleaned = sanitize_html(
        '<form><input name="q"></form><a href="javascript:alert(1)">bad</a>'
        '<a href="mailto:hello@example.com">mail</a>'
    )

    assert cleaned is not None
    assert "javascript:" not in cleaned
    assert "<form" not in cleaned
    assert "<input" not in cleaned
    assert 'href="mailto:hello@example.com"' in cleaned


def test_sanitize_html_keeps_allowed_formatting() -> None:
    cleaned = sanitize_html(
        "<h2>Title</h2><ul><li>One</li></ul><blockquote>Quote</blockquote>"
        "<pre><code>x = 1</code></pre><hr>"
    )

    assert cleaned is not None
    for tag in ("<h2>", "<ul>", "<li>", "<blockquote>", "<pre>", "<code>", "<hr"):
        assert tag in cleaned


def test_sanitize_html_treats_double_escaped_markup_as_text() -> None:
    cleaned = sanitize_html("&lt;script&gt;alert(1)&lt;/script&gt;")

    assert cleaned is None


def test_sanitize_html_returns_none_for_plain_text() -> None:
    assert sanitize_html("Just a plain summary.") is None
