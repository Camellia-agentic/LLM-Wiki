"""URL fetching, HTML extraction, and paste snapshot helpers."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from llm_wiki.text import timestamp, yaml_quote

DEFAULT_TIMEOUT = 15
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 5
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/xhtml+xml",
)


@dataclass(frozen=True)
class FetchedDocument:
    url: str
    canonical_url: str
    title: str
    text: str
    content_type: str
    content_digest: str


class _MainContentExtractor(HTMLParser):
    STRIP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self._ignore_depth = 0
        self._capture_depth = 0
        self._capture_tag: str | None = None
        self._parts: list[str] = []
        self.title = ""
        self._in_title = False
        self.canonical_url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        if tag == "link" and attrs_dict.get("rel", "").lower() == "canonical" and attrs_dict.get("href"):
            self.canonical_url = attrs_dict["href"]
        if tag in self.STRIP_TAGS:
            self._ignore_depth += 1
            return
        if self._ignore_depth:
            return
        if self._capture_depth == 0 and tag in {"article", "main"}:
            self._capture_depth = 1
            self._capture_tag = tag
            return
        if self._capture_depth:
            self._capture_depth += 1
            if tag in {"p", "br", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6", "li"}:
                self._parts.append("\n")
            return
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self.STRIP_TAGS and self._ignore_depth:
            self._ignore_depth -= 1
            return
        if self._capture_depth:
            self._capture_depth -= 1
            if self._capture_depth == 0:
                self._capture_tag = None
            return
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            return
        if self._in_title and not self.title:
            self.title = data.strip()
            return
        if self._capture_depth:
            text = data.strip()
            if text:
                self._parts.append(text)

    @property
    def text(self) -> str:
        joined = "\n".join(part.strip() for part in self._parts if part.strip())
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()


def _digest_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _normalise_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("invalid_url")
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise ValueError("unsupported_scheme")
    if parsed.username or parsed.password:
        raise ValueError("embedded_credentials")
    return parsed._replace(fragment="").geturl()


def _check_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise ValueError("private_network")
    if str(ip) == "169.254.169.254":
        raise ValueError("private_network")


def _resolve_host(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as error:
        raise ValueError("dns_failure") from error
    if not infos:
        raise ValueError("dns_failure")
    for info in infos:
        address = info[4][0]
        try:
            _check_ip(ipaddress.ip_address(address))
        except ValueError:
            raise
        except ipaddress.AddressValueError:
            continue


def validate_url(url: str) -> str:
    """Validate and return a normalised URL or raise ValueError with a code."""
    normalised = _normalise_url(url)
    host = urlparse(normalised).hostname
    if not host:
        raise ValueError("invalid_url")
    host_lower = host.lower()
    if host_lower in {"localhost", "metadata.google.internal"} or host_lower.endswith(".localhost"):
        raise ValueError("private_network")
    _resolve_host(host)
    return normalised


def _content_type_allowed(value: str) -> bool:
    media_type = value.split(";", 1)[0].strip().lower()
    return any(media_type.startswith(allowed) for allowed in ALLOWED_CONTENT_TYPES)


def extract_html_main(html: str, content_type: str = "text/html") -> FetchedDocument:
    parser = _MainContentExtractor()
    parser.feed(html)
    parser.close()
    text = parser.text
    if not text:
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
    return FetchedDocument(
        url="",
        canonical_url=parser.canonical_url,
        title=parser.title,
        text=text,
        content_type=content_type,
        content_digest=_digest_text(text),
    )


def create_paste_snapshot(
    title: str,
    body: str,
    *,
    source_url: str = "",
    captured_at: str | None = None,
) -> str:
    captured = captured_at or timestamp()
    digest = _digest_text(body)
    lines = [
        "---",
        "source_kind: paste",
        f'title: {yaml_quote(title)}',
        f"source_url: {yaml_quote(source_url)}",
        f"canonical_url: {yaml_quote(source_url)}",
        f'captured_at: "{captured}"',
        f'content_digest: "{digest}"',
        'content_type: "text/markdown"',
        'extractor: paste',
        'extractor_version: "1"',
        'user_note: "由用户粘贴"',
        "---",
        "",
        f"# {title}",
        "",
        body.rstrip(),
        "",
    ]
    return "\n".join(lines)


def fetch_url(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    opener: Callable[..., object] | None = None,
) -> FetchedDocument:
    """Fetch a public URL with redirect, timeout, and size limits."""
    current = validate_url(url)
    open_fn = opener or urlopen
    redirects = 0
    last_content_type = "text/plain"

    while True:
        validate_url(current)
        request = Request(
            current,
            headers={"User-Agent": "LLM-Wiki/0.2 (+local acquisition)"},
            method="GET",
        )
        try:
            response = open_fn(request, timeout=timeout)
        except HTTPError as error:
            if error.code in {301, 302, 303, 307, 308} and error.headers.get("Location"):
                location = error.headers["Location"]
                current = validate_url(urljoin(current, location))
                redirects += 1
                if redirects > max_redirects:
                    raise ValueError("too_many_redirects") from error
                continue
            raise ValueError("http_error") from error
        except URLError as error:
            reason = str(getattr(error, "reason", error))
            if "timed out" in reason.lower():
                raise ValueError("timeout") from error
            raise ValueError("connection_error") from error
        except TimeoutError as error:
            raise ValueError("timeout") from error

        with response:
            status = getattr(response, "status", None) or getattr(response, "code", 200)
            headers = getattr(response, "headers", None)
            if status in {301, 302, 303, 307, 308} and headers and headers.get("Location"):
                current = validate_url(urljoin(current, headers["Location"]))
                redirects += 1
                if redirects > max_redirects:
                    raise ValueError("too_many_redirects")
                continue

            content_type = ""
            if headers:
                content_type = headers.get("Content-Type", "")
            last_content_type = content_type or last_content_type
            if content_type and not _content_type_allowed(content_type):
                raise ValueError("unsupported_content_type")

            chunks: list[bytes] = []
            total = 0
            read = getattr(response, "read", None)
            if callable(read):
                while True:
                    block = read(64 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > max_bytes:
                        raise ValueError("response_too_large")
                    chunks.append(block)
                raw = b"".join(chunks)
            else:
                raw = bytes(getattr(response, "content", b""))
                if len(raw) > max_bytes:
                    raise ValueError("response_too_large")

        charset = "utf-8"
        if content_type and "charset=" in content_type.lower():
            charset = content_type.split("charset=", 1)[1].split(";", 1)[0].strip() or charset
        try:
            body = raw.decode(charset, errors="replace")
        except LookupError:
            body = raw.decode("utf-8", errors="replace")

        if "html" in (content_type or last_content_type).lower():
            extracted = extract_html_main(body, content_type or "text/html")
            title = extracted.title or urlparse(current).path.rsplit("/", 1)[-1] or current
            text = extracted.text
            canonical = extracted.canonical_url or current
        else:
            title = urlparse(current).path.rsplit("/", 1)[-1] or current
            text = body.strip()
            canonical = current

        if not text.strip():
            raise ValueError("empty_body")

        return FetchedDocument(
            url=current,
            canonical_url=canonical,
            title=title,
            text=text,
            content_type=content_type or last_content_type,
            content_digest=_digest_text(text),
        )

    raise ValueError("too_many_redirects")
