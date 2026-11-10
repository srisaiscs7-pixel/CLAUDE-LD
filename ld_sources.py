"""Find real papers in Europe PMC, PubMed and Crossref, and format them as Vancouver references.

Every reference in the dissertation comes from here. The writer can only cite a source
that is in this library, so no citation can be invented.
"""
from __future__ import annotations

import re
import time
import html
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict

import requests

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CROSSREF = "https://api.crossref.org"
UA = {"User-Agent": "MDS-Library-Dissertation-Builder/1.0 (personal academic use)"}


@dataclass
class Source:
    sid: str = ""                      # S1, S2 ... inside the library
    title: str = ""
    authors: list = field(default_factory=list)   # ["Smith J", "Rao AK"]
    journal: str = ""
    year: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    pmid: str = ""
    pmcid: str = ""
    kind: str = "journal-article"     # journal-article | book | book-chapter
    publisher: str = ""
    abstract: str = ""
    fulltext: str = ""                # excerpt from open-access full text
    pubtypes: list = field(default_factory=list)
    cited_by: int = 0
    found_by: list = field(default_factory=list)  # chapter keys whose searches found it
    verified: str = ""                # "Europe PMC" | "PubMed" | "Crossref"

    def key(self) -> str:
        if self.pmid:
            return "pmid:" + self.pmid
        if self.doi:
            return "doi:" + self.doi.lower()
        return "t:" + re.sub(r"[^a-z0-9]", "", self.title.lower())[:80]

    def first_author_surname(self) -> str:
        return self.authors[0].split(" ")[0] if self.authors else ""

    def short_cite(self) -> str:
        a = self.first_author_surname() or "Anonymous"
        etal = " et al." if len(self.authors) > 2 else (f" and {self.authors[1].split(' ')[0]}" if len(self.authors) == 2 else "")
        return f"{a}{etal} ({self.year})"

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        return Source(**{k: v for k, v in d.items() if k in Source.__dataclass_fields__})

    def vancouver(self) -> str:
        au = self.authors[:6]
        authors = ", ".join(au) + (", et al" if len(self.authors) > 6 else "")
        title = self.title.rstrip(".")
        if self.kind == "book":
            parts = [authors + "." if authors else "", f"{title}."]
            if self.publisher:
                parts.append(f"{self.publisher};")
            parts.append(f"{self.year}.")
            return " ".join(p for p in parts if p).strip()
        s = f"{authors}. {title}. " if authors else f"{title}. "
        s += f"{self.journal}. " if self.journal else ""
        s += self.year
        if self.volume:
            s += f";{self.volume}"
            if self.issue:
                s += f"({self.issue})"
        if self.pages:
            s += f":{self.pages}"
        s += "."
        if self.doi:
            s += f" doi:{self.doi}"
        return re.sub(r"\s+", " ", s).strip()


def _clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _get(url, params=None, tries=3, timeout=30, as_json=True):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(2 * (i + 1))
                continue
            r.raise_for_status()
            return r.json() if as_json else r.text
        except requests.RequestException as e:  # network hiccup
            last = str(e)
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"Request failed: {url} ({last})")


# ---------------------------------------------------------------- Europe PMC
def _epmc_to_source(r: dict) -> Source:
    ji = r.get("journalInfo") or {}
    j = ji.get("journal") or {}
    authors = []
    for a in (r.get("authorList") or {}).get("author", []) or []:
        if a.get("lastName"):
            authors.append(f"{a['lastName']} {a.get('initials', '')}".strip())
        elif a.get("collectiveName"):
            authors.append(a["collectiveName"])
        elif a.get("fullName"):
            authors.append(a["fullName"])
    if not authors and r.get("authorString"):
        authors = [x.strip().rstrip(".") for x in r["authorString"].split(",") if x.strip()]
    pt = (r.get("pubTypeList") or {}).get("pubType") or []
    if isinstance(pt, str):
        pt = [pt]
    return Source(
        title=_clean(r.get("title", "")).rstrip("."),
        authors=authors,
        journal=(j.get("medlineAbbreviation") or j.get("isoabbreviation") or j.get("title") or "").replace(".", "").strip(),
        year=str(ji.get("yearOfPublication") or r.get("pubYear") or ""),
        volume=str(ji.get("volume") or ""),
        issue=str(ji.get("issue") or ""),
        pages=str(r.get("pageInfo") or ""),
        doi=r.get("doi", "") or "",
        pmid=r.get("pmid", "") or "",
        pmcid=r.get("pmcid", "") or "",
        abstract=_clean(r.get("abstractText", "")),
        pubtypes=pt,
        cited_by=int(r.get("citedByCount") or 0),
        verified="Europe PMC",
    )


def search_europepmc(query: str, limit: int = 25, years: tuple | None = None) -> list[Source]:
    q = f"({query}) AND SRC:MED AND LANG:eng"
    if years:
        q += f" AND PUB_YEAR:[{years[0]} TO {years[1]}]"
    data = _get(f"{EPMC}/search", {"query": q, "format": "json", "resultType": "core",
                                   "pageSize": min(limit, 100)})
    out = []
    for r in (data.get("resultList") or {}).get("result", []) or []:
        s = _epmc_to_source(r)
        if s.title and s.year:
            out.append(s)
    return out


def strip_numeric_citations(text: str) -> str:
    """Remove citation marks such as [2], [3-5], [12, 81], ( 4 ) copied from another paper."""
    text = re.sub(r"\s?\[\s*\d+(?:\s*[,;–\-]\s*\d+)*\s*\]", "", text or "")
    text = re.sub(r"\s?\[\s*[,;–\-\s]*\]", "", text)
    return re.sub(r"\s+([.,;:])", r"\1", text)


def epmc_fulltext_excerpt(pmcid: str, max_words: int = 1500) -> str:
    """Introduction + Discussion paragraphs from an open-access article, shortened."""
    try:
        xml = _get(f"{EPMC}/{pmcid}/fullTextXML", as_json=False, tries=2)
        root = ET.fromstring(xml.encode("utf-8"))
    except Exception:
        return ""
    keep = []
    for sec in root.iter("sec"):
        t = sec.find("title")
        name = (t.text or "").lower() if t is not None and t.text else ""
        if any(k in name for k in ("intro", "background", "discussion", "review", "conclusion")):
            for p in sec.findall("p"):
                for parent in p.iter():               # drop the article's own reference numbers
                    for x in list(parent):
                        if x.tag == "xref":
                            tail = x.tail
                            parent.remove(x)
                            if tail:
                                parent.text = (parent.text or "") + tail
                keep.append(strip_numeric_citations(_clean(ET.tostring(p, encoding="unicode"))))
    words = " ".join(keep).split()
    return " ".join(words[:max_words])


# ---------------------------------------------------------------- PubMed
def search_pubmed(query: str, limit: int = 25, api_key: str = "") -> list[Source]:
    params = {"db": "pubmed", "term": query + " AND english[la]", "retmode": "json",
              "retmax": limit, "sort": "relevance"}
    if api_key:
        params["api_key"] = api_key
    ids = (_get(f"{EUTILS}/esearch.fcgi", params).get("esearchresult") or {}).get("idlist", [])
    return pubmed_fetch(ids, api_key) if ids else []


def pubmed_fetch(ids: list[str], api_key: str = "") -> list[Source]:
    params = {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}
    if api_key:
        params["api_key"] = api_key
    xml = _get(f"{EUTILS}/efetch.fcgi", params, as_json=False)
    root = ET.fromstring(xml.encode("utf-8"))
    out = []
    for art in root.iter("PubmedArticle"):
        mc = art.find("MedlineCitation")
        a = mc.find("Article")
        authors = []
        for au in a.findall("AuthorList/Author"):
            ln, ini, coll = au.findtext("LastName"), au.findtext("Initials"), au.findtext("CollectiveName")
            if ln:
                authors.append(f"{ln} {ini or ''}".strip())
            elif coll:
                authors.append(coll)
        ji = a.find("Journal/JournalIssue")
        year = (ji.findtext("PubDate/Year") or (ji.findtext("PubDate/MedlineDate") or "")[:4]) if ji is not None else ""
        doi = ""
        for e in a.findall("ELocationID"):
            if e.get("EIdType") == "doi":
                doi = e.text or ""
        for e in art.findall("PubmedData/ArticleIdList/ArticleId"):
            if e.get("IdType") == "doi" and not doi:
                doi = e.text or ""
        pmcid = ""
        for e in art.findall("PubmedData/ArticleIdList/ArticleId"):
            if e.get("IdType") == "pmc":
                pmcid = e.text or ""
        abstract = " ".join(_clean(ET.tostring(t, encoding="unicode")) for t in a.findall("Abstract/AbstractText"))
        out.append(Source(
            title=_clean(ET.tostring(a.find("ArticleTitle"), encoding="unicode")).rstrip("."),
            authors=authors,
            journal=(mc.findtext("MedlineJournalInfo/MedlineTA") or a.findtext("Journal/ISOAbbreviation") or "").replace(".", ""),
            year=year,
            volume=(ji.findtext("Volume") or "") if ji is not None else "",
            issue=(ji.findtext("Issue") or "") if ji is not None else "",
            pages=a.findtext("Pagination/MedlinePgn") or "",
            doi=doi, pmid=mc.findtext("PMID") or "", pmcid=pmcid, abstract=abstract,
            pubtypes=[p.text for p in a.findall("PublicationTypeList/PublicationType") if p.text],
            verified="PubMed",
        ))
    return out


# ---------------------------------------------------------------- Crossref
def _crossref_to_source(m: dict) -> Source:
    authors = []
    for au in m.get("author", []) or []:
        fam = au.get("family") or au.get("name") or ""
        giv = au.get("given") or ""
        ini = "".join(w[0] for w in re.split(r"[\s\-\.]+", giv) if w)
        if fam:
            authors.append(f"{fam} {ini}".strip())
    dp = ((m.get("issued") or {}).get("date-parts") or [[None]])[0]
    ctype = m.get("type", "journal-article")
    kind = "book" if ctype in ("book", "monograph", "edited-book", "reference-book") else \
        "book-chapter" if ctype == "book-chapter" else "journal-article"
    return Source(
        title=_clean((m.get("title") or [""])[0]).rstrip("."),
        authors=authors,
        journal=(m.get("short-container-title") or m.get("container-title") or [""])[0],
        year=str(dp[0] or ""), volume=m.get("volume", "") or "", issue=m.get("issue", "") or "",
        pages=m.get("page", "") or "", doi=m.get("DOI", "") or "", kind=kind,
        publisher=m.get("publisher", "") or "", abstract=_clean(m.get("abstract", "")),
        cited_by=int(m.get("is-referenced-by-count") or 0), verified="Crossref",
    )


def crossref_search(text: str, rows: int = 3) -> list[Source]:
    data = _get(f"{CROSSREF}/works", {"query.bibliographic": text, "rows": rows})
    return [_crossref_to_source(m) for m in (data.get("message") or {}).get("items", [])]


def crossref_doi(doi: str) -> Source | None:
    try:
        return _crossref_to_source(_get(f"{CROSSREF}/works/{doi}", tries=2)["message"])
    except Exception:
        return None


def _norm(t: str) -> set:
    return set(re.findall(r"[a-z0-9]{3,}", (t or "").lower()))


def title_match(a: str, b: str) -> float:
    x, y = _norm(a), _norm(b)
    return len(x & y) / max(1, min(len(x), len(y)))


def find_landmark(hint: dict, api_key: str = "") -> Source | None:
    """Look up a classic paper the model remembers (author, year, title words).
    Returned only if a database record matches; otherwise it is dropped."""
    title = hint.get("title", "")
    author = hint.get("first_author", "")
    year = str(hint.get("year", ""))
    try:
        q = f'TITLE:"{title}"' if title else ""
        if author:
            q += f" AND AUTH:{author}" if q else f"AUTH:{author}"
        if year:
            q += f" AND PUB_YEAR:{year}"
        for s in search_europepmc(q, limit=5) if q else []:
            if title_match(s.title, title) >= 0.6:
                return s
    except Exception:
        pass
    try:
        for s in crossref_search(f"{author} {year} {title}", rows=5):
            if title_match(s.title, title) >= 0.7 and (not year or s.year == year):
                return s
    except Exception:
        pass
    return None


def search(query: str, limit: int, prefer: str = "europepmc", pubmed_key: str = "",
           years: tuple | None = None) -> list[Source]:
    """Search one database, falling back to the other on failure or no results."""
    order = ["europepmc", "pubmed"] if prefer == "europepmc" else ["pubmed", "europepmc"]
    for db in order:
        try:
            res = search_europepmc(query, limit, years) if db == "europepmc" else search_pubmed(query, limit, pubmed_key)
            if res:
                return res
        except Exception:
            continue
    return []


def check_connections(pubmed_key: str = "") -> dict:
    out = {}
    for name, fn in [("Europe PMC", lambda: search_europepmc("dental plaque", 1)),
                     ("PubMed", lambda: search_pubmed("dental plaque", 1, pubmed_key)),
                     ("Crossref", lambda: crossref_search("experimental gingivitis in man", 1))]:
        try:
            out[name] = "OK" if fn() else "No results"
        except Exception as e:
            out[name] = f"Failed: {e}"[:200]
    return out
