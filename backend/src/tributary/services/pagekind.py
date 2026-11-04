from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from bs4 import BeautifulSoup

__all__ = [
    "PageClassification",
    "PageKind",
    "classify_page",
]

# A challenge page is only trusted when at least two independent kinds of
# evidence agree. A single token or a lone 403 is not enough: articles about
# bot protection routinely quote these strings, and some sites use 403 for
# ordinary access rules.
_CHALLENGE_TOKEN = re.compile(
    r"(?:js_challenge|jsc_token|jsc_[a-z]|cf[-_]chl|__cf_chl|challenge-platform|"
    r"turnstile|hcaptcha|recaptcha/api|perimeterx|px-captcha|datadome|"
    r"incapsula|_incapsula_resource)",
    re.IGNORECASE,
)
_CHALLENGE_PHRASE = re.compile(
    r"(?:checking (?:if the site connection is secure|your browser)|"
    r"verify(?:ing)? (?:that )?you are (?:a )?human|"
    r"enable (?:javascript|js) and cookies|"
    r"please (?:complete|wait).{0,40}(?:security check|verification)|"
    r"just a moment\.{0,3}|attention required|"
    r"unusual traffic from your computer network|"
    r"press (?:and|&) hold)",
    re.IGNORECASE,
)
_CHALLENGE_INPUTS = frozenset(
    {
        "js_challenge",
        "jsc_token",
        "jsc_orig_r",
        "solution",
        "cf_chl_opt",
        "__cf_chl_turnstile",
    }
)

_LOGIN = re.compile(
    r"(?:type=[\"']password[\"']|name=[\"']password[\"']|"
    r"action=[\"'][^\"']*/(?:login|signin|sign-in|auth)|"
    r"sign in to (?:continue|read)|log in to (?:continue|read)|"
    r"you (?:must|need to) (?:be )?(?:logged|signed) in|"
    r"create (?:a free |an )?account to continue)",
    re.IGNORECASE,
)
_PAYWALL = re.compile(
    r"(?:subscribe to (?:continue|read|keep reading)|"
    r"subscriber[- ]only|already a subscriber|"
    r"this (?:article|story|content) is (?:for|available to) subscribers|"
    r"to continue reading|"
    r"start your (?:free )?trial to (?:read|continue)|"
    r"become a (?:member|subscriber) to (?:read|continue))",
    re.IGNORECASE,
)


class PageKind(str, Enum):
    """What a fetched HTML page appears to be."""

    ARTICLE = "article"
    JS_CHALLENGE = "js_challenge"
    LOGIN_REQUIRED = "login_required"
    PAYWALL = "paywall"


@dataclass(frozen=True, slots=True)
class PageClassification:
    """A page classification plus the independent signals behind it."""

    kind: PageKind
    signals: tuple[str, ...] = ()


def _decode(body: bytes | str) -> str:
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="ignore")
    return body


def _has_challenge_form(soup: BeautifulSoup) -> bool:
    for form in soup.find_all("form"):
        for field in form.find_all("input"):
            if str(field.get("name") or "").strip().lower() in _CHALLENGE_INPUTS:
                return True
        action = str(form.get("action") or "").strip()
        if action and re.search(r"(?:challenge|verify|check)", action, re.IGNORECASE):
            return True
    return False


def _is_script_heavy(soup: BeautifulSoup, visible_text: str) -> bool:
    scripts = soup.find_all("script")
    return len(scripts) >= 3 and len(visible_text) < 300


def _challenge_signals(
    text: str,
    soup: BeautifulSoup,
    status_code: int,
) -> tuple[str, ...]:
    visible_text = soup.get_text(" ", strip=True)
    signals: list[str] = []
    if _CHALLENGE_TOKEN.search(text):
        signals.append("token")
    if _CHALLENGE_PHRASE.search(text):
        signals.append("phrase")
    if _has_challenge_form(soup):
        signals.append("form")
    if _is_script_heavy(soup, visible_text):
        signals.append("scripts")
    if status_code in {403, 503}:
        signals.append("status")
    return tuple(signals)


def classify_page(
    body: bytes | str,
    *,
    status_code: int = 200,
    extracted_chars: int | None = None,
    min_chars: int = 500,
) -> PageClassification:
    """Classify a page without trusting one weak signal.

    ``extracted_chars`` is ``None`` before extraction. Login and paywall
    detection only runs once the extracted text is known to be short, so an
    article that merely mentions signing in or subscribing is not mislabelled.
    """

    text = _decode(body)
    if not text.strip():
        return PageClassification(PageKind.ARTICLE)

    soup = BeautifulSoup(text, "html.parser")
    signals = _challenge_signals(text, soup, status_code)
    if len(signals) >= 2:
        return PageClassification(PageKind.JS_CHALLENGE, signals)

    if extracted_chars is None or extracted_chars >= min_chars:
        return PageClassification(PageKind.ARTICLE, signals)

    if _LOGIN.search(text):
        return PageClassification(PageKind.LOGIN_REQUIRED, signals)
    if _PAYWALL.search(text):
        return PageClassification(PageKind.PAYWALL, signals)
    return PageClassification(PageKind.ARTICLE, signals)
