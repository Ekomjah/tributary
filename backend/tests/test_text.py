from __future__ import annotations

from tributary.services.text import (
    clean_byline,
    html_to_text,
    is_promo_image,
    leading_image,
    normalize_text,
    readable_title,
    safe_image_url,
    sanitize_html,
    strip_leading_image,
    titles_match,
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
    assert 'src="https://example.com/posts/x"' in cleaned
    assert 'href="https://example.com/about"' in cleaned
    assert 'rel="noopener noreferrer"' in cleaned
    assert "target=" not in cleaned


def test_sanitize_html_keeps_safe_images_and_drops_unsafe_sources() -> None:
    cleaned = sanitize_html(
        '<p><img src="/pics/a.png" alt="A" width="1200" height="800"'
        ' srcset="/pics/a@2x.png 2x" onerror="steal()"></p>'
        '<img src="data:image/png;base64,AAAA">'
        '<img src="javascript:alert(1)">'
        '<img src="https://cdn.example.com/b.jpg" alt="B">',
        base_url="https://example.com/posts/1",
    )

    assert cleaned is not None
    assert 'src="https://example.com/pics/a.png"' in cleaned
    assert 'src="https://cdn.example.com/b.jpg"' in cleaned
    assert 'alt="A"' in cleaned
    assert 'alt="B"' in cleaned
    assert "data:" not in cleaned
    assert "javascript:" not in cleaned
    assert "srcset" not in cleaned
    assert "onerror" not in cleaned
    assert "width=" not in cleaned
    assert "height=" not in cleaned
    assert 'loading="lazy"' in cleaned
    assert 'decoding="async"' in cleaned
    assert 'referrerpolicy="no-referrer"' in cleaned


def test_sanitize_html_drops_tracking_pixels() -> None:
    cleaned = sanitize_html(
        '<p>Text</p><img src="https://example.com/pixel.gif" width="1" height="1">',
        base_url="https://example.com/posts/1",
    )

    assert cleaned is not None
    assert "pixel.gif" not in cleaned
    assert "<p>Text</p>" in cleaned


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


def test_sanitize_html_turns_div_blocks_into_paragraphs() -> None:
    cleaned = sanitize_html("<div>First paragraph</div><div>Second <b>paragraph</b></div>")

    assert cleaned == "<p>First paragraph</p><p>Second <b>paragraph</b></p>"


def test_sanitize_html_flattens_nested_layout_divs() -> None:
    cleaned = sanitize_html("<div><div>Alpha</div><div><div>Beta</div></div></div>")

    assert cleaned == "<p>Alpha</p><p>Beta</p>"


def test_sanitize_html_keeps_block_structure_inside_sections() -> None:
    cleaned = sanitize_html("<section><h2>A heading</h2>Loose text.<p>A paragraph.</p></section>")

    assert cleaned == ("<h2>A heading</h2><p>Loose text.</p><p>A paragraph.</p>")


def test_sanitize_html_wraps_loose_text_but_not_a_lead_image() -> None:
    cleaned = sanitize_html('<img src="https://example.com/lead.jpg" alt="Lead"><p>Text</p>')

    assert cleaned is not None
    assert cleaned.startswith("<img")
    assert '<img alt="Lead"' in cleaned
    assert "<p>Text</p>" in cleaned


def test_sanitize_html_drops_empty_paragraphs() -> None:
    cleaned = sanitize_html("<p>One</p><p> </p><p><br></p><p>Two</p>")

    assert cleaned == "<p>One</p><p>Two</p>"


def test_sanitize_html_flattens_nested_pre_blocks() -> None:
    cleaned = sanitize_html("<pre><pre>print(1)</pre></pre>")

    assert cleaned == "<pre>print(1)</pre>"


def test_sanitize_html_demotes_body_headings_below_the_page_title() -> None:
    cleaned = sanitize_html("<h1>Section</h1><h3>Subsection</h3>")

    assert cleaned == "<h2>Section</h2><h3>Subsection</h3>"


def test_sanitize_html_preserves_paragraph_line_breaks_and_inline_spacing() -> None:
    cleaned = sanitize_html("<p>One<br>Two<br><br>Three <em>four</em></p>")

    assert cleaned is not None
    assert cleaned.count("<br") == 3
    assert "Three <em>four</em>" in cleaned
    assert cleaned.startswith("<p>One<br")


def test_titles_match_ignores_markup_case_and_site_suffix() -> None:
    assert titles_match("<b>A Big Post About Things</b>", "a big post about things")
    assert titles_match("A Big Post About Things — Example", "A Big Post About Things")
    assert not titles_match("A Big Post About Things", "Another Post Entirely")
    assert not titles_match("Week 4", "Week 4 recap")
    assert not titles_match("", "A Big Post About Things")


def test_clean_byline_strips_prefixes_and_rejects_contact_details() -> None:
    assert clean_byline("By Jane Doe") == "Jane Doe"
    assert clean_byline("Written by Jane Doe") == "Jane Doe"
    assert clean_byline("jane@example.com") is None
    assert clean_byline("https://example.com/jane") is None


def test_safe_image_url_resolves_relative_sources_and_rejects_local_schemes() -> None:
    assert (
        safe_image_url("/cover.jpg", base_url="https://example.com/post")
        == "https://example.com/cover.jpg"
    )
    assert safe_image_url("data:image/png;base64,AAAA") is None
    assert is_promo_image("https://example.com/promo/cover.jpg")
    assert is_promo_image("https://example.com/newsletter-cover.jpg")
    assert not is_promo_image("https://example.com/2026/10/octoverse-header.jpg")


def test_leading_image_reads_a_figure_with_alt_and_caption() -> None:
    fragment = (
        '<figure><img src="https://example.com/cover.jpg" alt="A cover">'
        "<figcaption>The caption.</figcaption></figure><p>Body.</p>"
    )

    assert leading_image(fragment) == ("https://example.com/cover.jpg", "A cover", "The caption.")


def test_leading_image_accepts_an_image_only_paragraph() -> None:
    fragment = '<p><a href="/"><img src="https://example.com/a.jpg" alt="A"></a></p>'

    assert leading_image(fragment) == ("https://example.com/a.jpg", "A", None)


def test_leading_image_ignores_a_body_that_starts_with_text() -> None:
    assert leading_image('<p>Intro</p><img src="https://example.com/a.jpg" alt="A">') is None


def test_strip_leading_image_deduplicates_a_cover_at_another_size() -> None:
    fragment = (
        '<figure><img src="https://ichef.bbci.co.uk/ace/standard/1920/abc123.jpg" alt="A">'
        "<figcaption>Caption.</figcaption></figure><p>Body.</p>"
    )

    cleaned, caption = strip_leading_image(
        fragment,
        "https://ichef.bbci.co.uk/ace/branded_news/1200/abc123.jpg",
    )

    assert cleaned == "<p>Body.</p>"
    assert caption == "Caption."


def test_strip_leading_image_keeps_a_different_or_captioned_image() -> None:
    fragment = '<p><img src="https://example.com/a.jpg" alt="A"></p><p>Body.</p>'
    assert strip_leading_image(fragment, "https://example.com/b.jpg") == (
        fragment,
        None,
    )

    captioned = '<p>A photo <img src="https://example.com/a.jpg"></p><p>Body.</p>'
    assert strip_leading_image(captioned, "https://example.com/a.jpg") == (
        captioned,
        None,
    )
