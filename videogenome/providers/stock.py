"""Retrieval providers: real, openly licensed media instead of generated media.

``openverse`` searches Openverse (Flickr, Freesound, museums and more) and
``wikimedia-commons`` searches Wikimedia Commons. Both accept only items whose
source declares CC0 or public domain by default, and record per item the title,
creator, source page and licence. That record becomes the asset's rights
evidence. The licence is *as declared by the source*, so a human rights review
still applies before publication.
"""
from __future__ import annotations

import html
import re
import urllib.parse
from pathlib import Path

from videogenome.plugins import Generated, PluginError, Provider
from videogenome.providers.base import api_headers, download, http_json, provider_schema

COMMON = {
    "max_bytes": {"type": "integer", "minimum": 1024, "maximum": 2_000_000_000},
    "candidates": {"type": "integer", "minimum": 1, "maximum": 50},
    "exclude_terms": {"type": "array", "items": {"type": "string"}},
}


def _query(request: dict) -> str:
    query = (request.get("query") or request.get("prompt") or "").strip()
    if not query:
        raise PluginError("Retrieval needs a query or prompt")
    return query[:200]


STOP_WORDS = frozenset("""a an the of and or in on at to for with from by over under above below into onto
    is are be very small large big some its their this that these those clean flat editorial illustration
    image photo picture cinematic footage documentary shot no text style""".split())


def _queries(request: dict) -> list[str]:
    """The full query, then its content words, then the two leading content words."""
    full = _query(request)
    words = [w.strip(".,;:!?()\"'").lower() for w in full.split()]
    content = [w for w in words if w and w not in STOP_WORDS and not w.isdigit()]
    attempts = [full, " ".join(content[:4]), " ".join(content[:2]), content[0] if content else ""]
    return [q for i, q in enumerate(attempts) if q and q not in attempts[:i]]


def _aspect(request: dict) -> str | None:
    width, height = request.get("width"), request.get("height")
    if not width or not height:
        return None
    if width > height * 1.2:
        return "wide"
    if height > width * 1.2:
        return "tall"
    return "square"


def _rank(candidates: list[dict], query: str, title_of_item) -> list[dict]:
    """Prefer items whose title contains the query's content words (stable otherwise)."""
    words = [w for w in query.lower().split() if w not in STOP_WORDS]
    def score(item: dict) -> int:
        title = (title_of_item(item) or "").lower()
        return sum(word in title for word in words)
    return sorted(candidates, key=score, reverse=True)


def _pick(candidates: list[dict], request: dict, limit: int) -> dict:
    if not candidates:
        raise PluginError(f"No openly licensed match for {_query(request)!r}")
    # Deterministic variety: different inputs with similar queries pick differently.
    return candidates[request.get("seed", 0) % min(limit, len(candidates))]


def _strip(text: str | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


class OpenverseProvider(Provider):
    reports_rights = True
    summary = "Search Openverse for CC0 / public-domain images, music and sounds"
    capabilities = frozenset({"image", "music", "sound"})
    config_schema = provider_schema({
        **COMMON,
        "base_url": {"type": "string", "pattern": "^https://"},
        "licenses": {"type": "array", "items": {"enum": ["cc0", "pdm"]}, "minItems": 1},
        "api_key_env": {"type": "string", "pattern": "^[A-Z_][A-Z0-9_]*$"},
        "sources": {"type": "array", "items": {"type": "string"}},
    })

    def generate(self, capability: str, request: dict, workdir: Path) -> Generated:
        for query in _queries(request):
            try:
                return self._search(capability, request, workdir, query)
            except PluginError as exc:
                if "No openly licensed match" not in str(exc):
                    raise
        raise PluginError(f"No openly licensed match for any of {_queries(request)}")

    def _search(self, capability: str, request: dict, workdir: Path, query: str) -> Generated:
        base = self.config.get("base_url", "https://api.openverse.org/v1").rstrip("/")
        endpoint = "images" if capability == "image" else "audio"
        params = {"q": query, "license": ",".join(self.config.get("licenses", ["cc0", "pdm"])),
                  "page_size": 20, "mature": "false"}  # 20 is the anonymous maximum
        if capability == "image" and _aspect(request):
            params["aspect_ratio"] = _aspect(request)
        if self.config.get("sources"):
            params["source"] = ",".join(self.config["sources"])
        result = http_json("GET", f"{base}/{endpoint}/?{urllib.parse.urlencode(params)}",
                           headers=api_headers(self.config), timeout=60)
        excluded = [term.lower() for term in self.config.get("exclude_terms", [])]
        candidates = []
        for item in result.get("results", []):
            if item.get("license") not in self.config.get("licenses", ["cc0", "pdm"]):
                continue
            context = " ".join(str(item.get(k) or "") for k in ("title", "creator", "description")).lower()
            if any(term in context for term in excluded):
                continue
            if capability == "image":
                if (item.get("width") or 0) < 0.6 * request.get("width", 0):
                    continue
            else:
                needed = request.get("duration_seconds", 0)
                if (item.get("duration") or 0) < needed * 1000:
                    continue
            candidates.append(item)
        if not candidates:
            raise PluginError(f"No openly licensed match for {query!r}")
        candidates = _rank(candidates, query, lambda item: item.get("title"))
        item = _pick(candidates, request, self.config.get("candidates", 5))
        suffix = Path(urllib.parse.urlparse(item["url"]).path).suffix.lower() or (
            ".jpg" if capability == "image" else ".mp3")
        output = download(item["url"], workdir / f"openverse{suffix}",
                          max_bytes=self.config.get("max_bytes", 150_000_000))
        licence = f"{item['license'].upper()} {item.get('license_version') or ''}".strip()
        return Generated(output, {
            "origin_type": "licensed",
            "rights": {"license": licence,
                       "evidence": f"Declared {licence} at {item.get('foreign_landing_url')} "
                                   f"(via Openverse {item.get('id')})"},
            "attribution": {"title": title_of(item), "creator": item.get("creator"),
                            "creator_url": item.get("creator_url"), "source": item.get("source"),
                            "landing_page": item.get("foreign_landing_url"),
                            "license_url": item.get("license_url"), "file_url": item["url"]},
            "query": query, "candidates_considered": len(candidates),
        })


def title_of(item: dict) -> str:
    return (item.get("title") or "untitled").strip()


COMMONS_ALLOWED = ("cc0", "public domain", "pd", "pdm")


class WikimediaCommonsProvider(Provider):
    reports_rights = True
    summary = "Search Wikimedia Commons for CC0 / public-domain footage, images and audio"
    capabilities = frozenset({"video", "image", "music", "sound"})
    config_schema = provider_schema({
        **COMMON,
        "api_url": {"type": "string", "pattern": "^https://"},
        "allow_licenses": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "skip_restricted": {"type": "boolean"},
    })

    def _allowed(self, short_name: str) -> bool:
        allowed = [a.lower() for a in self.config.get("allow_licenses", COMMONS_ALLOWED)]
        name = short_name.lower().strip()
        return any(name == a or name.startswith(a + " ") or name.startswith(a + "-") for a in allowed)

    def generate(self, capability: str, request: dict, workdir: Path) -> Generated:
        for query in _queries(request):
            try:
                return self._search(capability, request, workdir, query)
            except PluginError as exc:
                if "No openly licensed match" not in str(exc):
                    raise
        raise PluginError(f"No openly licensed match for any of {_queries(request)}")

    def _search(self, capability: str, request: dict, workdir: Path, query: str) -> Generated:
        api = self.config.get("api_url", "https://commons.wikimedia.org/w/api.php")
        filetype = {"video": "video", "image": "bitmap"}.get(capability, "audio")
        params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                  "gsrsearch": f"{query} filetype:{filetype}", "gsrlimit": 40}
        if capability == "video":
            params.update(prop="videoinfo", viprop="url|size|mime|extmetadata|derivatives")
        else:
            params.update(prop="imageinfo", iiprop="url|size|mime|extmetadata")
            if capability == "image":
                params["iiurlwidth"] = min(3840, max(1280, 2 * request.get("width", 1280)))
        result = http_json("GET", f"{api}?{urllib.parse.urlencode(params)}", timeout=60)
        pages = sorted(result.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
        excluded = [term.lower() for term in self.config.get("exclude_terms", [])]
        candidates = []
        for page in pages:
            info = (page.get("videoinfo") or page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata", {})
            licence = _strip(meta.get("LicenseShortName", {}).get("value"))
            if not self._allowed(licence):
                continue
            restrictions = _strip(meta.get("Restrictions", {}).get("value"))
            if restrictions and self.config.get("skip_restricted", True):
                continue  # e.g. personality or trademark restrictions
            # Check every human-written field: broadcasters often appear only as Artist or Credit.
            context = " ".join(_strip(meta.get(key, {}).get("value")) for key in
                               ("ImageDescription", "Artist", "Credit", "ObjectName")).lower()
            if any(term in page.get("title", "").lower() or term in context for term in excluded):
                continue
            if capability == "image":
                if (info.get("width") or 0) < 0.6 * request.get("width", 0):
                    continue
                url = info.get("thumburl") or info.get("url")
            elif capability == "video":
                if float(info.get("duration") or 0) < request.get("duration_seconds", 0):
                    continue
                if (info.get("width") or 0) < 0.5 * request.get("width", 0):
                    continue
                url = self._video_url(info, request)
            else:
                if float(info.get("duration") or 0) < request.get("duration_seconds", 0):
                    continue
                url = info.get("url")
            if url:
                candidates.append({"page": page, "info": info, "meta": meta, "licence": licence,
                                   "restrictions": restrictions, "url": url})
        if not candidates:
            raise PluginError(f"No openly licensed match for {query!r}")
        candidates = _rank(candidates, query, lambda item: item["page"].get("title"))
        chosen = _pick(candidates, request, self.config.get("candidates", 5))
        suffix = Path(urllib.parse.urlparse(chosen["url"]).path).suffix.lower() or ".bin"
        output = download(chosen["url"], workdir / f"commons{suffix}",
                          max_bytes=self.config.get("max_bytes", 400_000_000))
        page, meta = chosen["page"], chosen["meta"]
        landing = chosen["info"].get("descriptionurl")
        return Generated(output, {
            "origin_type": "licensed",
            "rights": {"license": chosen["licence"],
                       "evidence": f"Declared {chosen['licence']} on {landing}"},
            "attribution": {"title": page.get("title"), "creator": _strip(meta.get("Artist", {}).get("value")),
                            "landing_page": landing,
                            "license_url": _strip(meta.get("LicenseUrl", {}).get("value")) or None,
                            "credit": _strip(meta.get("Credit", {}).get("value"))[:300] or None,
                            "file_url": chosen["url"]},
            "query": query, "candidates_considered": len(candidates),
        })

    @staticmethod
    def _video_url(info: dict, request: dict) -> str | None:
        """Prefer a web transcode near the output height over the (huge) original."""
        target = request.get("height", 720)
        best = None
        for derivative in info.get("derivatives", []):
            height = derivative.get("height") or 0
            if "webm" not in (derivative.get("type") or "") or height < min(target, 720):
                continue
            if best is None or abs(height - target) < abs(best["height"] - target):
                best = derivative
        if best:
            return best["src"]
        return info.get("url") if (info.get("size") or 0) < 400_000_000 else None
