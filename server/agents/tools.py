"""Research tool interfaces. Nothing here pretends to work when it cannot."""
import ipaddress
import base64
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Dict, List

UA = "Mozilla/5.0 (compatible; SxarfAI-research/1.0)"


class SearchTool:
    name = "none"

    def available(self) -> bool:
        return False

    def search(self, query: str, n: int = 5) -> List[Dict[str, str]]:
        raise RuntimeError("No search tool configured")


def _clean(s: str) -> str:
    import html
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


class _DuckDuckGoResults(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: List[Dict[str, str]] = []
        self.capture = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if self.capture:
            if tag not in self.VOID_TAGS:
                self.capture["depth"] += 1
        elif tag == "a" and classes.intersection({"result__a", "result-link"}):
            self.capture = {"kind": "title", "depth": 1, "value": [],
                            "url": attrs.get("href", "")}
        elif tag in {"a", "td"} and classes.intersection({"result__snippet", "result-snippet"}):
            self.capture = {"kind": "snippet", "depth": 1, "value": []}

    def handle_endtag(self, tag):
        if not self.capture or tag in self.VOID_TAGS:
            return
        self.capture["depth"] -= 1
        if self.capture["depth"]:
            return
        value = re.sub(r"\s+", " ", "".join(self.capture["value"])).strip()
        if self.capture["kind"] == "title":
            href = self.capture["url"]
            parsed = urllib.parse.urlparse(href)
            if parsed.hostname == "duckduckgo.com" and parsed.path.startswith("/l/"):
                href = urllib.parse.parse_qs(parsed.query).get("uddg", [href])[0]
            elif href.startswith("//"):
                href = "https:" + href
            if urllib.parse.urlparse(href).scheme in ("http", "https"):
                self.results.append({"title": value, "url": href, "snippet": ""})
        elif self.results:
            self.results[-1]["snippet"] = value
        self.capture = None

    def handle_data(self, data):
        if self.capture:
            self.capture["value"].append(data)


def parse_ddg_html(page: str, n: int = 5) -> List[Dict[str, str]]:
    parser = _DuckDuckGoResults()
    parser.feed(page)
    return parser.results[:n]


class DuckDuckGoSearch(SearchTool):
    """Free, keyless DuckDuckGo Lite search."""
    name = "duckduckgo-lite"

    def available(self) -> bool:
        return True

    def search(self, query: str, n: int = 5) -> List[Dict[str, str]]:
        url = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query})
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            page = r.read(800_000).decode("utf-8", "replace")
        results = parse_ddg_html(page, n)
        if not results and ("anomaly-modal" in page or "botnet" in page.lower()):
            raise RuntimeError("DuckDuckGo blocked the search request; retry later or use another search provider.")
        return results


class _YahooResults(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: List[Dict[str, str]] = []
        self.current = None
        self.depth = 0
        self.in_title = False
        self.in_snippet = False
        self.snippet_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if self.current is None:
            if tag == "div" and "algo-sr" in classes:
                self.current = {"title": [], "url": "", "snippet": []}
                self.depth = 1
            return

        if tag not in self.VOID_TAGS:
            self.depth += 1
        if tag == "a" and not self.current["url"]:
            self.current["url"] = attrs.get("href", "")
        if tag == "h3":
            self.in_title = True
        if "compText" in classes:
            self.in_snippet = True
            self.snippet_depth = self.depth

    def handle_endtag(self, tag):
        if self.current is None or tag in self.VOID_TAGS:
            return
        if tag == "h3":
            self.in_title = False
        if self.in_snippet and tag == "div" and self.depth == self.snippet_depth:
            self.in_snippet = False
        if tag == "div" and self.depth == 1:
            title = re.sub(r"\s+", " ", "".join(self.current["title"])).strip()
            snippet = re.sub(r"\s+", " ", "".join(self.current["snippet"])).strip()
            href = self.current["url"]
            match = re.search(r"/RU=([^/]+)", href)
            if match:
                href = urllib.parse.unquote(match.group(1))
            parsed = urllib.parse.urlparse(href)
            if title and parsed.scheme in ("http", "https") and parsed.hostname:
                self.results.append({"title": title, "url": href, "snippet": snippet})
            self.current = None
            self.in_title = self.in_snippet = False
            self.depth = 0
            return
        self.depth -= 1

    def handle_data(self, data):
        if self.current is None:
            return
        if self.in_title:
            self.current["title"].append(data)
        if self.in_snippet:
            self.current["snippet"].append(data)


class YahooSearch(SearchTool):
    """Keyless Yahoo web results used when DuckDuckGo is unavailable."""
    name = "yahoo"

    def available(self) -> bool:
        return True

    def search(self, query: str, n: int = 5) -> List[Dict[str, str]]:
        url = "https://search.yahoo.com/search?" + urllib.parse.urlencode({"p": query})
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; SxarfAI-research/1.0)",
                          "Accept-Language": "en-US,en;q=0.9"})
        with urllib.request.urlopen(req, timeout=12) as response:
            page = response.read(800_000).decode("utf-8", "replace")
        parser = _YahooResults()
        parser.feed(page)
        return parser.results[:n]


class _BingResults(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: List[Dict[str, str]] = []
        self.current = None
        self.depth = 0
        self.in_title = False
        self.in_snippet = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if self.current is None:
            if tag == "li" and "b_algo" in classes:
                self.current = {"title": [], "url": "", "snippet": []}
                self.depth = 1
            return

        if tag not in self.VOID_TAGS:
            self.depth += 1
        if tag == "h2":
            self.in_title = True
        elif tag == "a" and self.in_title and not self.current["url"]:
            self.current["url"] = attrs.get("href", "")
        elif tag == "p" and ({"b_lineclamp2", "b_lineclamp3"} & classes):
            self.in_snippet = True

    def handle_endtag(self, tag):
        if self.current is None or tag in self.VOID_TAGS:
            return
        if tag == "h2":
            self.in_title = False
        elif tag == "p":
            self.in_snippet = False
        if tag == "li" and self.depth == 1:
            title = re.sub(r"\s+", " ", "".join(self.current["title"])).strip()
            snippet = re.sub(r"\s+", " ", "".join(self.current["snippet"])).strip()
            href = self.current["url"]
            encoded = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("u", [""])[0]
            if encoded.startswith("a1"):
                try:
                    href = base64.urlsafe_b64decode(encoded[2:] + "==").decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    pass
            elif href.startswith("//"):
                href = "https:" + href
            parsed = urllib.parse.urlparse(href)
            if title and parsed.scheme in ("http", "https") and parsed.hostname != "www.bing.com":
                self.results.append({"title": title, "url": href, "snippet": snippet})
            self.current = None
            self.in_title = self.in_snippet = False
            self.depth = 0
            return
        self.depth -= 1

    def handle_data(self, data):
        if self.current is None:
            return
        if self.in_title:
            self.current["title"].append(data)
        if self.in_snippet:
            self.current["snippet"].append(data)


class BingSearch(SearchTool):
    """Keyless Bing HTML search used as a final provider fallback."""
    name = "bing"

    def available(self) -> bool:
        return True

    def search(self, query: str, n: int = 5) -> List[Dict[str, str]]:
        url = "https://www.bing.com/search?" + urllib.parse.urlencode(
            {"q": query, "setlang": "en-US", "cc": "US"})
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                       "AppleWebKit/537.36 Chrome/131 Safari/537.36",
                          "Accept-Language": "en-US,en;q=0.9"})
        with urllib.request.urlopen(req, timeout=12) as response:
            page = response.read(800_000).decode("utf-8", "replace")
        parser = _BingResults()
        parser.feed(page)
        return parser.results[:n]


class FallbackSearch(SearchTool):
    def __init__(self, providers):
        self.providers = providers
        self.name = " + ".join(provider.name for provider in providers)

    def available(self) -> bool:
        return any(provider.available() for provider in self.providers)

    def search(self, query: str, n: int = 5) -> List[Dict[str, str]]:
        errors = []
        for provider in self.providers:
            if not provider.available():
                continue
            try:
                results = provider.search(query, n)
                if results:
                    return results
                errors.append(f"{provider.name}: no results")
            except Exception as exc:
                errors.append(f"{provider.name}: {type(exc).__name__}: {exc}")
        raise RuntimeError("All configured search providers failed (" + "; ".join(errors) + ")")


class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer", "aside", "noscript", "svg", "form"}
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "pre", "tr", "section", "article"}

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def html_to_text(page: str) -> str:
    p = _Text()
    p.feed(page)
    text = "".join(p.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _safe_host(host: str) -> bool:
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local)
    except ValueError:
        return True


class DocFetcher:
    def fetch(self, url: str, max_chars: int = 40_000) -> str:
        u = urllib.parse.urlparse(url)
        if u.scheme not in ("http", "https") or not _safe_host(u.hostname or ""):
            raise ValueError(f"Refusing to fetch {url}")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=12) as r:
            ctype = r.headers.get("Content-Type", "")
            if "html" not in ctype and "text" not in ctype:
                raise ValueError(f"Unsupported content type {ctype}")
            raw = r.read(700_000).decode("utf-8", "replace")
        text = html_to_text(raw) if "html" in ctype else raw
        return text[:max_chars]


def make_search_tool(kind: str) -> SearchTool:
    if kind.lower() in ("ddg", "duckduckgo"):
        return FallbackSearch([DuckDuckGoSearch(), YahooSearch(), BingSearch()])
    return SearchTool()
