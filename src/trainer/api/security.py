from __future__ import annotations

from urllib.parse import urlparse


def request_has_same_origin(host: str | None, origin: str | None, referer: str | None, fetch_site: str | None) -> bool:
    if not host or (fetch_site and fetch_site not in {"same-origin", "none"}):
        return False
    source = origin or referer
    if not source:
        return False
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == host.lower()
