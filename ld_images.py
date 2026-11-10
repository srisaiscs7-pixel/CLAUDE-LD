"""Find openly licensed images for the dissertation.

Two sources, both with a licence that allows reuse with attribution:
  * Wikimedia Commons (CC BY, CC BY-SA, CC0 or public domain only)
  * figures from open-access articles in Europe PMC whose licence is Creative Commons
Each image keeps its attribution, which is printed under the figure.
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from html import unescape

import requests

from ld_sources import EPMC, UA, _get

COMMONS = "https://commons.wikimedia.org/w/api.php"
OK_LICENCE = re.compile(r"\b(cc[\s\-]?by|cc0|public domain|pd\b|pd-)", re.I)
XLINK = "{http://www.w3.org/1999/xlink}href"


def _clean(html, n=400):
    t = unescape(re.sub(r"<[^>]+>", " ", html or ""))
    return re.sub(r"\s+", " ", t).strip()[:n]


def commons_search(query: str, limit: int = 8) -> list[dict]:
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
              "gsrsearch": f"{query} filetype:bitmap|drawing", "gsrlimit": limit, "prop": "imageinfo",
              "iiprop": "url|extmetadata|mime|size", "iiurlwidth": 1400,
              "iiextmetadatafilter": "LicenseShortName|Artist|ImageDescription|ObjectName"}
    try:
        data = _get(COMMONS, params=params, tries=2)
    except Exception:
        return []
    out = []
    for page in (data.get("query") or {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = _clean((meta.get("LicenseShortName") or {}).get("value", ""), 60)
        if not lic or not OK_LICENCE.search(lic):
            continue
        if info.get("mime") not in ("image/jpeg", "image/png", "image/svg+xml", "image/tiff"):
            continue
        if min(info.get("width", 0), info.get("height", 0)) < 300:
            continue
        thumb = info.get("thumburl") or info.get("url")
        title = page.get("title", "").replace("File:", "")
        out.append({
            "source": "commons", "title": title,
            "desc": _clean((meta.get("ImageDescription") or {}).get("value", "")) or title,
            "artist": _clean((meta.get("Artist") or {}).get("value", ""), 120) or "Unknown author",
            "licence": lic, "url": thumb,
            "small": re.sub(r"/\d+px-", "/320px-", thumb) if "/thumb/" in thumb else thumb,
            "page": info.get("descriptionurl", ""),
        })
    return out


def epmc_figures(pmcid: str) -> list[dict]:
    """Figures of a Creative-Commons open-access article."""
    try:
        xml = _get(f"{EPMC}/{pmcid}/fullTextXML", as_json=False, tries=2)
        root = ET.fromstring(xml.encode("utf-8"))
    except Exception:
        return []
    lic_text = " ".join(" ".join(l.itertext()) + " " + (l.get(XLINK) or "") for l in root.iter("license"))
    if not re.search(r"creativecommons\.org/licenses/by|creative commons attribution|cc by|cc0|publicdomain",
                     lic_text, re.I):
        return []
    m = re.search(r"licenses/(by(?:-[a-z]+)*)/(\d\.\d)", lic_text)
    lic = f"CC {m.group(1).upper()} {m.group(2)}" if m else "CC BY"
    out = []
    for fig in root.iter("fig"):
        g = fig.find(".//graphic")
        if g is None or not g.get(XLINK):
            continue
        href = g.get(XLINK)
        name = href if re.search(r"\.(jpe?g|png|gif)$", href, re.I) else href + ".jpg"
        cap = fig.find("caption")
        label = fig.find("label")
        caption = _clean(" ".join(cap.itertext()) if cap is not None else "", 500)
        url = f"https://europepmc.org/articles/{pmcid}/bin/{name}"
        out.append({"source": "epmc", "title": (label.text if label is not None and label.text else "Figure"),
                    "desc": caption, "licence": lic, "url": url, "small": url, "pmcid": pmcid})
    return out


def download(url: str, max_px: int = 1600) -> bytes | None:
    """Download an image and return it as a JPEG (white background), or None."""
    try:
        r = requests.get(url, headers=UA, timeout=40)
        if r.status_code != 200 or len(r.content) < 2000:
            return None
        from PIL import Image
        im = Image.open(io.BytesIO(r.content))
        im.load()
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, "white")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        if min(im.size) < 200:
            return None
        im.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        return buf.getvalue()
    except Exception:
        return None


def thumbnail(data: bytes, px: int = 320) -> bytes:
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((px, px))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=75)
    return buf.getvalue()


def check() -> str:
    try:
        return "OK" if commons_search("human mandible", 2) else "No results"
    except Exception as e:
        return f"Failed: {e}"
