import re
import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_BOILERPLATE = re.compile(
    r'(subscribe|sign up|newsletter|cookie|privacy policy|terms of service'
    r'|advertisement|follow us|share this|read more|loading\.\.\.)',
    re.IGNORECASE,
)

_MAX_CHARS = 4000


def fetch_article_body(url: str) -> str:
    """Fetch article text from a URL. Returns empty string on any failure."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10, allow_redirects=True)
        resp.raise_for_status()
    except Exception:
        return ""

    try:
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove noise tags
        for tag in soup(["script", "style", "nav", "header", "footer",
                          "aside", "figure", "figcaption", "noscript"]):
            tag.decompose()

        # Prefer <article> if present, else fall back to <main> then <body>
        container = soup.find("article") or soup.find("main") or soup.body
        if not container:
            return ""

        paragraphs = [
            p.get_text(" ", strip=True)
            for p in container.find_all("p")
            if len(p.get_text(strip=True)) > 40
            and not _BOILERPLATE.search(p.get_text())
        ]

        text = "\n\n".join(paragraphs)
        return text[:_MAX_CHARS]
    except Exception:
        return ""
