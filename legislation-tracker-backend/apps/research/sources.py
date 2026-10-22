"""Policy-approved official sources, pinned public DNS and bounded downloads."""
import ipaddress
import re
import socket
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from urllib3 import HTTPSConnectionPool, Timeout
from urllib3.exceptions import HTTPError

USER_AGENT = "LegislationTrackerResearch/1.0"


class SourceUnavailable(ValueError):
    pass


def fetch_bytes(url, allowed_host, max_bytes, allowed_types=None):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != allowed_host or parsed.username
            or parsed.password or parsed.port not in (None, 443) or parsed.fragment
            or re.search(r"[\x00-\x20\x7f]", url)):
        raise SourceUnavailable("invalid_source")
    try:
        addresses = {row[4][0] for row in socket.getaddrinfo(allowed_host, 443, type=socket.SOCK_STREAM)}
    except OSError:
        raise SourceUnavailable("source_dns_unavailable") from None
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise SourceUnavailable("private_destination")
    # Connect to the checked IP, retain hostname TLS verification and SNI, and
    # never resolve the name again or follow redirects/environment proxies.
    pool = HTTPSConnectionPool(sorted(addresses)[0], port=443, server_hostname=allowed_host,
                               assert_hostname=allowed_host, cert_reqs="CERT_REQUIRED",
                               timeout=Timeout(connect=3, read=3), retries=False)
    response = None
    deadline = time.monotonic() + 15
    try:
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        response = pool.request("GET", target, headers={"Host": allowed_host, "User-Agent": USER_AGENT, "Accept-Encoding": "identity"}, preload_content=False, redirect=False)
        if response.status != 200:
            raise SourceUnavailable("source_status_unavailable")
        if response.headers.get("Content-Encoding", "identity") not in ("", "identity"):
            raise SourceUnavailable("compressed_source_rejected")
        mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if allowed_types and mime not in allowed_types:
            raise SourceUnavailable("source_type_rejected")
        length = response.headers.get("Content-Length")
        if length and (not length.isdigit() or int(length) > max_bytes):
            raise SourceUnavailable("source_size_limit")
        body = bytearray()
        while True:
            chunk = response.read(1, decode_content=False)
            if time.monotonic() > deadline:
                raise SourceUnavailable("source_time_limit")
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > max_bytes:
                raise SourceUnavailable("source_size_limit")
        return bytes(body)
    except (HTTPError, OSError):
        raise SourceUnavailable("source_unavailable") from None
    finally:
        if response:
            response.close()
        pool.close()


class BiographyParser(HTMLParser):
    def __init__(self, element_id):
        super().__init__(convert_charrefs=True)
        self.element_id, self.depth, self.skip = element_id, 0, 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "img", "hr", "input", "meta", "link", "source", "wbr", "area", "base", "embed", "param", "track", "col"}:
            if self.depth and not self.skip:
                self.parts.append(" ")
            return
        if self.depth:
            self.depth += 1
        elif dict(attrs).get("id") == self.element_id:
            self.depth = 1
        if self.depth and (self.skip or tag in {"script", "style", "nav", "header", "footer", "noscript", "form"}):
            self.skip += 1

    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1
            if self.skip:
                self.skip -= 1
            else:
                self.parts.append(" ")

    def handle_data(self, data):
        if self.depth and not self.skip:
            self.parts.append(data)


def parse_biography(body, element_id, identity_text):
    parser = BiographyParser(element_id)
    parser.feed(body.decode("utf-8", errors="strict"))
    text = re.sub(r"\s+", " ", "".join(parser.parts)).strip()
    if not text:
        raise SourceUnavailable("biography_unavailable")
    if not identity_text or identity_text.casefold() not in text.casefold():
        raise SourceUnavailable("identity_mismatch")
    return text


def fetch_official_biography(policy):
    if not policy.approved or not policy.license or not policy.attribution:
        raise SourceUnavailable("source_not_approved")
    policy.full_clean()
    host = urlsplit(policy.url).hostname
    robots_url = f"https://{host}/robots.txt"
    robots = RobotFileParser(robots_url)
    robots.parse(fetch_bytes(robots_url, host, 64_000, {"text/plain"}).decode("utf-8").splitlines())
    if not robots.can_fetch(USER_AGENT, policy.url):
        raise SourceUnavailable("robots_denied")
    body = fetch_bytes(policy.url, host, 512_000, {"text/html"})
    return parse_biography(body, policy.element_id, policy.identity_text)
