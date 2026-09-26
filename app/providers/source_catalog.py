"""Official source catalogue and live connectivity diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SourceCheck:
    source: str
    url: str
    status: int | None
    content_type: str = ""
    error: str | None = None


OFFICIAL_ENTRYPOINTS = {
    "pboc": "https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html",
    "safe": "https://www.safe.gov.cn/safe/ywfb/index.html",
    "customs": "https://www.customs.gov.cn/",
    "mof": "https://gks.mof.gov.cn/tongjishuju/",
}


def check_source(source: str, url: str, timeout: float = 20.0) -> SourceCheck:
    try:
        request = Request(url, headers={"User-Agent": "macro-ledger/0.1 (+official-data-client)", "Accept": "text/html,*/*"})
        with urlopen(request, timeout=timeout) as response:
            return SourceCheck(source, url, response.status, str(response.headers.get("Content-Type", "")))
    except Exception as exc:
        return SourceCheck(source, url, None, error=str(exc))
