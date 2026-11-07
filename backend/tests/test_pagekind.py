from __future__ import annotations

from tributary.services.pagekind import PageKind, classify_page


def test_reddit_style_challenge_needs_token_and_form() -> None:
    body = """
    <html><body>
      <form action="/r/technology/comments/abc/post/">
        <input name="solution" type="hidden">
        <input name="js_challenge" type="hidden" value="1">
        <input name="jsc_token" type="hidden" value="abc">
      </form>
    </body></html>
    """

    result = classify_page(body)

    assert result.kind is PageKind.JS_CHALLENGE
    assert set(result.signals) == {"token", "form"}


def test_one_weak_signal_is_not_a_challenge() -> None:
    body = """
    <html><body><article>
      <h1>How bot challenges work</h1>
      <p>This article explains the jsc_token and js_challenge fields.</p>
    </article></body></html>
    """

    result = classify_page(body)

    assert result.kind is PageKind.ARTICLE


def test_login_page_is_only_blocked_when_extraction_is_short() -> None:
    body = """
    <html><body>
      <h1>Sign in to continue</h1>
      <form action="/login"><input name="password" type="password"></form>
    </body></html>
    """

    short = classify_page(body, extracted_chars=10, min_chars=500)
    long = classify_page(body, extracted_chars=900, min_chars=500)

    assert short.kind is PageKind.LOGIN_REQUIRED
    assert long.kind is PageKind.ARTICLE


def test_paywall_phrase_is_only_checked_after_short_extraction() -> None:
    body = """
    <html><body><article>
      <h1>Local news</h1>
      <p>Subscribe to continue reading this story.</p>
    </article></body></html>
    """

    short = classify_page(body, extracted_chars=20, min_chars=500)
    long = classify_page(body, extracted_chars=800, min_chars=500)

    assert short.kind is PageKind.PAYWALL
    assert long.kind is PageKind.ARTICLE


def test_status_and_phrase_are_two_challenge_signals() -> None:
    body = "<html><body><p>Checking your browser before accessing the site.</p></body></html>"

    result = classify_page(body, status_code=403)

    assert result.kind is PageKind.JS_CHALLENGE
    assert set(result.signals) == {"phrase", "status"}


def test_plain_forbidden_page_is_not_a_challenge() -> None:
    body = "<html><body><h1>Forbidden</h1><p>You do not have access.</p></body></html>"

    result = classify_page(body, status_code=403, extracted_chars=0)

    assert result.kind is PageKind.ARTICLE


def test_login_phrase_inside_a_script_is_not_visible() -> None:
    body = (
        "<html><body>"
        "<script>var copy = 'Sign in to continue';</script>"
        "<article><p>A short but real article body.</p></article>"
        "</body></html>"
    )

    result = classify_page(body, extracted_chars=10, min_chars=500)

    assert result.kind is PageKind.ARTICLE


def test_paywall_phrase_inside_a_script_is_not_visible() -> None:
    body = (
        "<html><body>"
        "<script>var copy = 'subscribe to continue reading';</script>"
        "<article><p>A short but real article body.</p></article>"
        "</body></html>"
    )

    result = classify_page(body, extracted_chars=10, min_chars=500)

    assert result.kind is PageKind.ARTICLE
