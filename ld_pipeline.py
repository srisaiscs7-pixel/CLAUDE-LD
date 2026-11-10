"""The generation pipeline. Each stage saves its result, so a stopped or interrupted job resumes
from where it left off instead of starting again."""
from __future__ import annotations

import base64
import math
import re
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import ld_config as config
import ld_prompts as prompts
import ld_sources as src
from ld_docbuilder import build_document
from ld_visuals import render_flowchart

CITE = re.compile(r"\s?\[(S\d+(?:\s*[;,]\s*S\d+)*)\]")
STAGES = ["analyse", "plan", "library", "visuals", "write", "summary", "assemble"]
STAGE_LABEL = {
    "analyse": "Reading the synopsis", "plan": "Planning chapters", "library": "Finding references",
    "visuals": "Designing tables and flowcharts", "write": "Writing chapters",
    "summary": "Writing summary and conclusion", "assemble": "Building the Word file",
}
STAGE_WEIGHT = {"analyse": 0.02, "plan": 0.04, "library": 0.12, "visuals": 0.06, "write": 0.66,
                "summary": 0.04, "assemble": 0.06}


class Stopped(Exception):
    pass


class Ctx:
    def __init__(self, storage, job_id, llm, stop_event=None, pubmed_key="", workers=4):
        self.st = storage
        self.id = job_id
        self.llm = llm
        self.stop_event = stop_event
        self.pubmed_key = pubmed_key
        self.workers = workers
        self.job = storage.read_json(job_id, "job.json")

    def save(self, force=False):
        if self.llm is not None:
            self.job["tokens"] = {"in": self.llm.tokens_in + self.job.get("_tok_in0", 0),
                                  "out": self.llm.tokens_out + self.job.get("_tok_out0", 0)}
        self.job["updated"] = datetime.now().isoformat(timespec="seconds")
        self.st.write_json(self.id, "job.json", self.job, force=force)

    def log(self, msg):
        self.job.setdefault("log", []).append(f"{datetime.now().strftime('%H:%M:%S')}  {msg}")
        self.job["log"] = self.job["log"][-200:]
        self.job["message"] = msg
        self.save()

    def progress(self, stage, frac, msg=None):
        done = sum(STAGE_WEIGHT[s] for s in STAGES[:STAGES.index(stage)])
        self.job["progress"] = round(min(0.999, done + STAGE_WEIGHT[stage] * max(0, min(1, frac))), 4)
        self.job["stage"] = stage
        if msg:
            self.log(msg)
        else:
            self.save()

    def check_stop(self):
        if self.stop_event is not None and self.stop_event.is_set():
            raise Stopped()

    def done(self, stage):
        return stage in self.job.get("stages_done", [])

    def mark(self, stage):
        self.job.setdefault("stages_done", []).append(stage)
        self.progress(stage, 1.0)
        self.save(force=True)


# ---------------------------------------------------------------- helpers
def words(text):
    return len(re.findall(r"\b\w[\w'\-]*\b", CITE.sub("", text or "")))


def _tok(text):
    stop = {"the", "and", "for", "with", "from", "that", "this", "are", "was", "were", "its", "their",
            "into", "using", "use", "used", "based", "between", "study", "review", "patients", "after"}
    return [w for w in re.findall(r"[a-z][a-z0-9\-]{2,}", (text or "").lower()) if w not in stop]


def rank_sources(query, lib, k, boost_ids=(), usage=None):
    """BM25-style relevance of library sources to a query, with a small penalty for overused sources."""
    q = Counter(_tok(query))
    if not lib:
        return []
    docs = {s["sid"]: _tok(s["title"] + " " + s["title"] + " " + s.get("abstract", "")) for s in lib}
    N = len(docs)
    df = Counter(w for d in docs.values() for w in set(d))
    avg = sum(len(d) for d in docs.values()) / N or 1
    scores = {}
    for sid, d in docs.items():
        tf = Counter(d)
        sc = 0.0
        for w in q:
            if w in tf:
                idf = math.log(1 + (N - df[w] + 0.5) / (df[w] + 0.5))
                sc += idf * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * len(d) / avg))
        if sid in boost_ids:
            sc += 2.0
        if usage:
            sc -= 0.6 * usage.get(sid, 0)
        scores[sid] = sc
    by = {s["sid"]: s for s in lib}
    return [by[sid] for sid, _ in sorted(scores.items(), key=lambda x: -x[1])[:k]]


def fmt_sources(lst, abstract_words=230, fulltext_words=600):
    out = []
    for s in lst:
        ab = " ".join((s.get("abstract") or "").split()[:abstract_words])
        line = f"[{s['sid']}] {src.Source.from_dict(s).short_cite()} — {s['title']}. {s.get('journal', '')} {s['year']}."
        if s.get("pubtypes"):
            kinds = [p for p in s["pubtypes"] if p not in ("Journal Article", "research-article", "English Abstract")]
            if kinds:
                line += f" Type: {', '.join(kinds[:3])}."
        line += f"\n    Abstract: {ab}" if ab else "\n    (No abstract available: cite only for what the title itself states.)"
        if s.get("fulltext"):
            line += "\n    Full-text excerpt: " + " ".join(s["fulltext"].split()[:fulltext_words])
        out.append(line)
    return "\n".join(out)


def outline_text(plan):
    return "; ".join(f"{c['title']} ({', '.join(x['title'] for x in c.get('sections', []))})" for c in plan["chapters"])


def budget(job):
    st = job["settings"]
    pages = job["pages"]
    wpp = config.words_per_page(st["line_spacing"], st["size"])
    plan = job["plan"]
    n_ch = len(plan["chapters"])
    n_refs = config.reference_target(pages)
    deduct = n_refs / config.refs_per_page(st["line_spacing"])
    deduct += 0.7 * len(plan.get("tables", [])) + 0.8 * len(plan.get("flowcharts", []))
    deduct += 0.35 * n_ch + (n_ch + 1 if st.get("divider_pages") else 0)
    prose = max(600, int((pages - deduct) * wpp))
    body = [c for c in plan["chapters"] if c.get("kind") != "aims"]
    total_w = sum(max(0.5, float(c.get("weight", 5))) for c in body) or 1
    prose -= 150 * (n_ch - len(body))
    for c in plan["chapters"]:
        c["words"] = 150 if c.get("kind") == "aims" else int(prose * max(0.5, float(c.get("weight", 5))) / total_w)
    job["budget"] = {"words_per_page": wpp, "prose_words": prose, "references": n_refs,
                     "deducted_pages": round(deduct, 1)}


# ---------------------------------------------------------------- stages
def stage_analyse(ctx):
    j = ctx.job
    ctx.progress("analyse", 0.1, "Reading the synopsis")
    syn = ctx.st.read_json(ctx.id, "synopsis.json", {}) or {}
    text = syn.get("text", "")
    files = None
    if syn.get("pdf_b64") and len(text.split()) < 80:
        files = [(base64.b64decode(syn["pdf_b64"]), "application/pdf")]
        text = "(The synopsis is attached as a PDF; read it from the attachment.)"
    if not text.strip() and not files:
        text = "(No synopsis uploaded. Use the topic only.)"
    info = ctx.llm.generate(prompts.ANALYSE.format(topic=j["topic"], department=j["department"], text=text[:60000]),
                            task="analyse", json_mode=True, temperature=0.1, files=files, max_tokens=4000)
    d = j.setdefault("details", {})
    for k, v in (info or {}).items():
        if v and not d.get(k):
            d[k] = v
    d["title"] = d.get("title") or j["topic"]
    if j.get("topic") and j["topic"].strip():
        d["title"] = j["topic"].strip()
    ctx.mark("analyse")


# ---------------------------------------------------------------- fixed headings from the user's text
_SKIP = re.compile(r"^(references?|bibliography|annexures?|appendix|appendices|acknowledge?ments?)$", re.I)
_NUM = re.compile(r"^\s*(?:(?:chapter|section)\s+)?(?:\d+(?:\.\d+)*\.?|[ivxlc]+\.|[a-z]\)|\([a-z0-9]+\)|[\-–•*])\s+", re.I)


def _norm(t):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (t or "").lower())).strip()


def guess_kind(title):
    t = title.lower()
    if "introduction" in t:
        return "intro"
    if "aim" in t or "objective" in t:
        return "aims"
    if "review of literature" in t or "literature review" in t or "review of the literature" in t:
        return "review"
    if "discussion" in t:
        return "discussion"
    if "summary" in t or "conclusion" in t:
        return "summary"
    return "narrative"


def extract_headings(llm, text):
    """Headings copied from the user's text. Anything the model returns that is not in the text is dropped,
    so no invented heading can get through."""
    data = llm.generate(prompts.HEADINGS.format(text=" \n".join(text.splitlines())[:120000]),
                        task="headings", json_mode=True, temperature=0, max_tokens=8000)
    src_norm = " " + _norm(text) + " "
    exact = {}  # normalised line -> the line exactly as the user typed it
    for line in text.splitlines():
        raw = _NUM.sub("", line).strip().strip(":").strip()
        if raw and len(raw.split()) <= 20:
            exact.setdefault(_norm(raw), raw)
    out, seen = [], set()
    for h in (data or {}).get("headings", []):
        t = _NUM.sub("", str(h.get("text", ""))).strip().strip(":").strip()
        n = _norm(t)
        if not n or _SKIP.match(n) or len(n.split()) > 20:
            continue
        if " " + n + " " not in src_norm:      # not in the user's text: drop it
            continue
        lvl = 2 if str(h.get("level", 1)) == "2" else 1
        key = (lvl, n)
        if key in seen:
            continue
        seen.add(key)
        out.append({"text": exact.get(n, t), "level": lvl, "pos": src_norm.find(" " + n + " ")})
    # keep the order of the user's text
    out.sort(key=lambda h: h["pos"])
    chapters = []
    for h in out:
        if h["level"] == 1 or not chapters:
            chapters.append({"title": h["text"], "sections": []})
        else:
            chapters[-1]["sections"].append({"title": h["text"], "brief": h["text"]})
    return chapters


def stage_plan_fixed(ctx, fixed):
    j = ctx.job
    d = j["details"]
    outline = []
    for i, c in enumerate(fixed, 1):
        outline.append(f"{i}. {c['title']}")
        for k, sct in enumerate(c["sections"]):
            outline.append(f"   {i}.{k + 1} {sct['title']}")
    pages = j["pages"]
    info = ctx.llm.generate(prompts.PLAN_FIXED.format(
        title=d["title"], department=j["department"], outline="\n".join(outline), pages=pages,
        n_landmarks=10 if pages >= 40 else 5, n_tables=j.get("n_tables", 3), n_figs=j.get("n_figures", 1)),
        task="plan", json_mode=True, temperature=0.3, max_tokens=12000) or {}
    by_num = {}
    for c in info.get("chapters", []):
        try:
            by_num[int(c.get("number"))] = c
        except (TypeError, ValueError):
            pass
    default_w = {"intro": 6, "aims": 1, "review": 18, "discussion": 12, "summary": 3, "narrative": 10}
    chapters = []
    for i, c in enumerate(fixed, 1):
        extra = by_num.get(i, {})
        kind = guess_kind(c["title"])
        if kind in ("review", "summary", "aims") and c["sections"]:
            kind = "narrative"          # the user gave sub-headings: write under each of them
        briefs = extra.get("section_briefs") or []
        secs = [{"title": sct["title"], "brief": (briefs[k] if k < len(briefs) and briefs[k] else sct["title"])}
                for k, sct in enumerate(c["sections"])]
        if not secs:
            secs = [{"title": c["title"], "brief": extra.get("brief") or c["title"]}]
        try:
            w = float(extra.get("weight") or default_w[kind])
        except (TypeError, ValueError):
            w = default_w[kind]
        chapters.append({"key": f"c{i}", "title": c["title"], "kind": kind, "weight": w, "sections": secs,
                         "queries": [q for q in (extra.get("queries") or []) if q.strip()] or [f"({c['title']}) AND ({d['title']})"],
                         "fixed": True})

    def place(items, limit):
        res = []
        for v in items or []:
            try:
                n = int(v.get("chapter"))
            except (TypeError, ValueError):
                continue
            if 1 <= n <= len(chapters):
                res.append(dict(v, chapter=f"c{n}"))
        return res[:limit]
    plan = {"chapters": chapters, "landmarks": info.get("landmarks", []),
            "tables": place(info.get("tables"), j.get("n_tables", 3)),
            "flowcharts": place(info.get("flowcharts"), j.get("n_figures", 1)), "fixed_headings": True}
    _fill_visual_slots(plan, j.get("n_tables", 3), j.get("n_figures", 1))
    return plan


def stage_plan(ctx):
    j = ctx.job
    d = j["details"]
    ctx.progress("plan", 0.1, "Planning the chapters")
    pages = j["pages"]
    max_topic = 2 if pages < 25 else 4 if pages < 60 else 7
    max_sections = 3 if pages < 25 else 5 if pages < 80 else 7
    syn_text = (ctx.st.read_json(ctx.id, "synopsis.json", {}) or {}).get("text", "")
    if j.get("strict_headings"):
        fixed = extract_headings(ctx.llm, syn_text) if syn_text.strip() else []
        if not fixed:
            raise RuntimeError("No headings were found in your synopsis text. Put each heading on its own line "
                               "(sub-headings numbered like 2.1), or untick 'Use only my headings'.")
        ctx.log(f"Using your {len(fixed)} headings exactly: " + "; ".join(c["title"] for c in fixed))
        plan = stage_plan_fixed(ctx, fixed)
        j["plan"] = plan
        budget(j)
        ctx.mark("plan")
        if j.get("review_outline"):
            j["status"] = "awaiting_approval"
            ctx.log("Chapter plan ready. Check it and press Approve to continue.")
            ctx.save(force=True)
            raise Stopped()
        return
    plan = ctx.llm.generate(prompts.PLAN.format(
        title=d["title"], department=j["department"], aim=d.get("aim", ""),
        objectives="; ".join(d.get("objectives") or []), scope=(d.get("scope", "") + " " + d.get("methodology", ""))[:3000],
        pages=pages, words=pages * config.words_per_page(j["settings"]["line_spacing"], j["settings"]["size"]),
        max_topic=max_topic, max_sections=max_sections,
        aims_rule=("Include an \"Aims and Objectives\" chapter (kind \"aims\") right after the Introduction."
                   if j.get("include_aims", True) else
                   "Do NOT include an Aims and Objectives chapter and do not use kind \"aims\"."),
        source_text=" ".join(ctx.st.read_json(ctx.id, "synopsis.json", {}).get("text", "").split()[:5000]) or "(none)",
        review_rule=("Include the Review of Literature chapter." if j.get("include_review", True)
                     else "Do NOT include a Review of Literature chapter."),
        n_landmarks=10 if pages >= 40 else 5, n_tables=j.get("n_tables", 3), n_figs=j.get("n_figures", 1)),
        task="plan", json_mode=True, temperature=0.4, max_tokens=12000)
    chapters = plan.get("chapters") or []
    if not j.get("include_aims", True):
        chapters = [c for c in chapters if (c.get("kind") or "").lower() != "aims"]
    for i, c in enumerate(chapters):
        c["key"] = f"c{i + 1}"
        c["kind"] = (c.get("kind") or "narrative").lower()
        c.setdefault("sections", [])
        c.setdefault("queries", [])
    keys = {c["key"] for c in chapters}
    old_keys = {f"c{i + 1}" for i in range(len(chapters))}
    plan["chapters"] = chapters
    plan["tables"] = [t for t in plan.get("tables", []) if t.get("chapter") in keys][: j.get("n_tables", 3)]
    plan["flowcharts"] = [f for f in plan.get("flowcharts", []) if f.get("chapter") in keys][: j.get("n_figures", 1)]
    _fill_visual_slots(plan, j.get("n_tables", 3), j.get("n_figures", 1))
    j["plan"] = plan
    budget(j)
    ctx.mark("plan")
    if j.get("review_outline"):
        j["status"] = "awaiting_approval"
        ctx.log("Chapter plan ready. Check it and press Approve to continue.")
        ctx.save(force=True)
        raise Stopped()


def _fill_visual_slots(plan, n_tables, n_figs):
    """Make sure the requested number of tables and flowcharts exist, in topic chapters."""
    ok = {c["key"] for c in plan["chapters"] if c["kind"] in ("narrative", "discussion", "intro")}
    plan["tables"] = [t for t in plan.get("tables", []) if t.get("chapter") in ok]
    plan["flowcharts"] = [f for f in plan.get("flowcharts", []) if f.get("chapter") in ok]
    topic = ([c for c in plan["chapters"] if c["kind"] in ("narrative", "discussion")]
             or [c for c in plan["chapters"] if c["key"] in ok])
    if not topic:
        return
    i = 0
    while len(plan["tables"]) < n_tables and topic:
        c = topic[i % len(topic)]
        plan["tables"].append({"chapter": c["key"], "after_section": 0,
                               "title": f"Summary of key aspects of {c['title'].lower()}", "purpose": c["title"]})
        i += 1
    while len(plan["flowcharts"]) < n_figs and topic:
        c = topic[(i + 1) % len(topic)]
        plan["flowcharts"].append({"chapter": c["key"], "after_section": max(0, len(c.get("sections", [])) - 1),
                                   "title": f"Flowchart of {c['title'].lower()}", "purpose": c["title"]})
        i += 1


def stage_library(ctx):
    j = ctx.job
    plan = j["plan"]
    dept = config.DEPARTMENTS.get(j["department"], {})
    journals = {x.lower() for x in dept.get("journals", [])}
    n_target = j["budget"]["references"]
    pool_target = int(n_target * 1.6) + 5
    queries = [(c["key"], q) for c in plan["chapters"] for q in c.get("queries", []) if q.strip()]
    if not queries:
        queries = [(plan["chapters"][0]["key"], j["details"]["title"])]
    per_q = max(15, min(60, math.ceil(pool_target * 2 / len(queries))))
    pool = {}
    rank_score = defaultdict(float)
    found = defaultdict(set)
    for qi, (ck, q) in enumerate(queries):
        ctx.check_stop()
        ctx.progress("library", qi / (len(queries) + 2), f"Searching: {q[:90]}")
        res = src.search(q, per_q, pubmed_key=ctx.pubmed_key)
        if not res and " AND " in q:  # relax an over-narrow query
            res = src.search(q.rsplit(" AND ", 1)[0], per_q, pubmed_key=ctx.pubmed_key)
        for r, s in enumerate(res):
            k = s.key()
            if k not in pool:
                pool[k] = s
            rank_score[k] += 1.0 / (1 + r * 0.15)
            found[k].add(ck)
        time.sleep(0.15)
    ctx.log(f"Found {len(pool)} candidate papers")
    landmarks = []
    for lm in plan.get("landmarks", [])[:12]:
        ctx.check_stop()
        s = src.find_landmark(lm, ctx.pubmed_key)
        if s:
            k = s.key()
            pool.setdefault(k, s)
            rank_score[k] += 3
            landmarks.append(k)
            for c in plan["chapters"]:
                if c["kind"] in ("narrative", "intro"):
                    found[k].add(c["key"])
                    break
    ctx.log(f"Verified {len(landmarks)} landmark papers in the databases")

    def score(k):
        s = pool[k]
        sc = rank_score[k]
        sc += 0.6 if s.abstract else -1.5
        sc += 0.4 if s.journal.lower() in journals else 0
        try:
            y = int(s.year)
            sc += 0.3 if y >= 2015 else 0.1 if y >= 2005 else 0
        except ValueError:
            pass
        sc += min(0.8, math.log10(1 + s.cited_by) * 0.3)
        if any(p in ("Systematic Review", "Meta-Analysis", "Review", "Randomized Controlled Trial") for p in s.pubtypes):
            sc += 0.3
        return sc
    # keep the best papers, with a fair share for every chapter
    chosen = []
    per_ch = defaultdict(list)
    for k in pool:
        for ck in found[k] or {"_"}:
            per_ch[ck].append(k)
    weights = {c["key"]: max(0.5, float(c.get("weight", 5))) for c in plan["chapters"]}
    wsum = sum(weights.values())
    for ck, ks in per_ch.items():
        share = int(pool_target * weights.get(ck, 1) / wsum * 0.6)
        for k in sorted(ks, key=score, reverse=True)[:share]:
            if k not in chosen:
                chosen.append(k)
    for k in sorted(pool, key=score, reverse=True):
        if len(chosen) >= pool_target:
            break
        if k not in chosen:
            chosen.append(k)
    chosen = sorted(chosen, key=score, reverse=True)[:pool_target]
    lib = []
    for i, k in enumerate(chosen, 1):
        s = pool[k]
        s.sid = f"S{i}"
        s.found_by = sorted(found[k])
        lib.append(s)
    # open-access full-text excerpts for the most relevant papers
    oa = [s for s in lib if s.pmcid][: (12 if j["pages"] >= 40 else 5)]
    for i, s in enumerate(oa):
        ctx.check_stop()
        ctx.progress("library", (len(queries) + i / max(1, len(oa))) / (len(queries) + 2),
                     f"Reading open-access full text {i + 1}/{len(oa)}")
        s.fulltext = src.epmc_fulltext_excerpt(s.pmcid)
    ctx.st.write_json(ctx.id, "library.json", [s.to_dict() for s in lib], force=True)
    j["library_count"] = len(lib)
    if len(lib) < max(5, n_target // 3):
        ctx.log(f"Only {len(lib)} papers found. The dissertation will be shorter on references; "
                "consider a broader topic wording.")
    ctx.log(f"Reference library ready: {len(lib)} verified papers")
    _rebalance_review(j, lib)
    ctx.mark("library")


def _rebalance_review(j, lib):
    """If there are too few papers for the review chapter, move its words to the other chapters."""
    plan = j["plan"]
    rev = [c for c in plan["chapters"] if c["kind"] == "review"]
    if not rev:
        return
    c = rev[0]
    each = 160
    possible = sum(1 for s in lib if s.abstract) * each
    if c["words"] > possible:
        spare = c["words"] - possible
        c["words"] = possible
        others = [x for x in plan["chapters"] if x["kind"] in ("narrative", "discussion")]
        for x in others:
            x["words"] += spare // max(1, len(others))


def stage_visuals(ctx):
    j = ctx.job
    plan = j["plan"]
    lib = ctx.st.read_json(ctx.id, "library.json", [])
    order = {c["key"]: i for i, c in enumerate(plan["chapters"])}
    specs = [("table", t) for t in plan.get("tables", [])] + [("flowchart", f) for f in plan.get("flowcharts", [])]
    out = ctx.st.read_json(ctx.id, "visuals.json", []) or []
    have = {(v["kind"], v["chapter"], v["plan_title"]) for v in out}
    for i, (kind, sp) in enumerate(specs):
        ctx.check_stop()
        if (kind, sp["chapter"], sp["title"]) in have:
            continue
        ctx.progress("visuals", i / max(1, len(specs)), f"Designing {kind}: {sp['title']}")
        ch = next(c for c in plan["chapters"] if c["key"] == sp["chapter"])
        rel = rank_sources(f"{sp['title']} {sp.get('purpose', '')} {ch['title']}", lib, 12,
                           boost_ids={s['sid'] for s in lib if ch['key'] in s.get('found_by', [])})
        tmpl = prompts.TABLE if kind == "table" else prompts.FLOWCHART
        try:
            data = ctx.llm.generate(tmpl.format(title=j["details"]["title"], vis_title=sp["title"],
                                                purpose=sp.get("purpose", ""), sources=fmt_sources(rel, 150, 0)),
                                    task=kind, json_mode=True, temperature=0.3, max_tokens=8000)
            if kind == "table":
                cols = data.get("columns") or []
                rows = [r for r in (data.get("rows") or []) if isinstance(r, list) and any(str(x).strip() for x in r)]
                if len(cols) < 2 or len(rows) < 2:
                    raise ValueError("table too small")
            else:
                render_flowchart(data)  # validates that it can be drawn
            sec_n = len(ch.get("sections", []))
            after = int(sp.get("after_section", 0) or 0)
            data.update(kind=kind, chapter=sp["chapter"], plan_title=sp["title"],
                        after_section=max(0, min(after, max(0, sec_n - 1))))
            data["source_sids"] = [x for x in data.get("source_sids", []) if any(s["sid"] == x for s in lib)]
            out.append(data)
            ctx.st.write_json(ctx.id, "visuals.json", out)
        except Exception as e:
            ctx.log(f"Skipped {kind} '{sp['title']}': {e}")
    # number in document order
    for kind in ("table", "flowchart"):
        vs = sorted([v for v in out if v["kind"] == kind], key=lambda v: (order.get(v["chapter"], 99), v["after_section"]))
        for n, v in enumerate(vs, 1):
            v["number"] = n
    ctx.st.write_json(ctx.id, "visuals.json", out, force=True)
    ctx.log(f"{sum(v['kind'] == 'table' for v in out)} tables and {sum(v['kind'] == 'flowchart' for v in out)} flowcharts ready")
    ctx.mark("visuals")


def _section_tasks(j):
    plan = j["plan"]
    tasks = []
    for c in plan["chapters"]:
        if c["kind"] in ("intro", "narrative", "discussion"):
            secs = c.get("sections") or [{"title": c["title"], "brief": c["title"]}]
            c["sections"] = secs
            per = max(150, c["words"] // len(secs))
            for i, s in enumerate(secs):
                tasks.append({"key": f"{c['key']}:{i}", "kind": "section", "chapter": c, "index": i, "words": per})
        elif c["kind"] == "review":
            tasks.append({"key": f"{c['key']}:review", "kind": "review", "chapter": c, "words": c["words"]})
        elif c["kind"] == "aims":
            tasks.append({"key": f"{c['key']}:aims", "kind": "aims", "chapter": c})
    return tasks


def _write_section(ctx, t, lib, visuals, usage):
    j = ctx.job
    c = t["chapter"]
    sec = c["sections"][t["index"]]
    ch_ids = {s["sid"] for s in lib if c["key"] in s.get("found_by", [])}
    rel = rank_sources(f"{j['details']['title']} {c['title']} {sec['title']} {sec.get('brief', '')}", lib,
                       18 if t["words"] > 900 else 12, boost_ids=ch_ids, usage=usage)
    for s in rel:
        usage[s["sid"]] = usage.get(s["sid"], 0) + 1
    notes = []
    for v in visuals:
        if v["chapter"] == c["key"] and v["after_section"] == t["index"]:
            label = "Table" if v["kind"] == "table" else "Figure"
            notes.append(f"{label} {v['number']} (\"{v.get('title') or v['plan_title']}\") is placed at the end of this "
                         f"section; refer to it once in the text as ({label} {v['number']}).")
    visual_note = " ".join(notes)
    target = t["words"]
    first = min(target, 2200)
    text = ctx.llm.generate(prompts.SECTION.format(
        section=sec["title"], chapter=c["title"], title=j["details"]["title"], department=j["department"],
        brief=sec.get("brief", ""), outline=outline_text(j["plan"]), visual_note=visual_note,
        subheading_rule=_subrule(j), words=first, continuation="", sources=fmt_sources(rel)),
        task="section", system=prompts.SYSTEM_WRITER, temperature=0.65, max_tokens=12000)
    loops = 0
    while words(text) < 0.85 * target and loops < 4:
        ctx.check_stop()
        loops += 1
        more = min(2000, target - words(text))
        heads = re.findall(r"^### (.+)$", text, re.M)
        tail = " ".join(text.split()[-350:])
        add = ctx.llm.generate(prompts.SECTION.format(
            section=sec["title"], chapter=c["title"], title=j["details"]["title"], department=j["department"],
            brief=sec.get("brief", ""), outline=outline_text(j["plan"]), visual_note="",
            subheading_rule=_subrule(j), words=more, continuation=prompts.CONTINUE.format(tail=tail, covered="; ".join(heads) or "see text", words=more),
            sources=fmt_sources(rel)), task="continue", system=prompts.SYSTEM_WRITER, temperature=0.65, max_tokens=12000)
        text = text.rstrip() + "\n\n" + add.strip()
    return text.strip()


def _write_review(ctx, t, lib):
    j = ctx.job
    c = t["chapter"]
    each = 150
    n = max(3, t["words"] // (each + 15))
    ch_ids = {s["sid"] for s in lib if c["key"] in s.get("found_by", [])}
    cands = [s for s in lib if s.get("abstract")]
    cands.sort(key=lambda s: (s["sid"] not in ch_ids, int(s["sid"][1:])))
    picked = sorted(cands[:n], key=lambda s: (s.get("year") or "9999", int(s["sid"][1:])))
    entries = ctx.st.read_json(ctx.id, "review_entries.json", {}) or {}
    batches = [picked[i:i + 10] for i in range(0, len(picked), 10)]
    for bi, batch in enumerate(batches):
        ctx.check_stop()
        todo = [s for s in batch if s["sid"] not in entries]
        if not todo:
            continue
        data = ctx.llm.generate(prompts.REVIEW.format(title=j["details"]["title"], words_each=each,
                                                      sources=fmt_sources(todo, 300, 400)),
                                task="review", system=prompts.SYSTEM_WRITER, json_mode=True,
                                temperature=0.5, max_tokens=12000)
        for e in data.get("entries", []):
            if e.get("sid") in {s["sid"] for s in todo} and e.get("text"):
                entries[e["sid"]] = CITE.sub("", e["text"]).strip()
        ctx.st.write_json(ctx.id, "review_entries.json", entries)
        ctx.log(f"Review of literature: {len(entries)}/{len(picked)} entries written")
    return {"order": [s["sid"] for s in picked if s["sid"] in entries]}


def _subrule(j):
    if j.get("plan", {}).get("fixed_headings"):
        return ("Do NOT add any sub-headings or headings of your own; write continuous paragraphs only "
                "(the user's headings are fixed).")
    return 'You may use up to three sub-headings, each on its own line starting with "### ".'


def _strip_headings(text):
    """Remove any heading line the writer added despite the rule (fixed-headings mode)."""
    return re.sub(r"(?m)^\s*#{1,6}\s+.*$\n?", "", text or "")


def stage_write(ctx):
    j = ctx.job
    lib = ctx.st.read_json(ctx.id, "library.json", [])
    visuals = ctx.st.read_json(ctx.id, "visuals.json", [])
    texts = ctx.st.read_json(ctx.id, "texts.json", {}) or {}
    tasks = [t for t in _section_tasks(j) if t["key"] not in texts]
    total = len(_section_tasks(j))
    usage = Counter()
    for k, v in texts.items():
        if isinstance(v, str):
            for m in CITE.finditer(v):
                for sid in re.findall(r"S\d+", m.group(1)):
                    usage[sid] += 0.5

    def run(t):
        ctx.check_stop()
        if t["kind"] == "section":
            return _write_section(ctx, t, lib, visuals, usage)
        if t["kind"] == "review":
            return _write_review(ctx, t, lib)
        d = j["details"]
        return ctx.llm.generate(prompts.AIMS.format(title=d["title"], department=j["department"], aim=d.get("aim", ""),
                                                    objectives="; ".join(d.get("objectives") or []),
                                                    outline=outline_text(j["plan"])),
                                task="aims", json_mode=True, temperature=0.2, max_tokens=3000)

    ctx.progress("write", (total - len(tasks)) / max(1, total), f"Writing {len(tasks)} parts")
    errors = []
    with ThreadPoolExecutor(max_workers=ctx.workers) as ex:
        futs = {ex.submit(run, t): t for t in tasks}
        for f in as_completed(futs):
            t = futs[f]
            try:
                texts[t["key"]] = f.result()
                ctx.st.write_json(ctx.id, "texts.json", texts)
                name = t["chapter"]["title"] + (f" › {t['chapter']['sections'][t['index']]['title']}" if t["kind"] == "section" else "")
                ctx.progress("write", len(texts) / max(1, total), f"Written: {name}")
            except Stopped:
                raise
            except Exception as e:
                errors.append(f"{t['key']}: {e}")
                ctx.log(f"Problem writing {t['key']}: {str(e)[:200]}")
    ctx.st.write_json(ctx.id, "texts.json", texts, force=True)
    if errors:
        raise RuntimeError(f"{len(errors)} parts failed to write; press Resume to retry them. First error: {errors[0][:300]}")
    ctx.mark("write")


def stage_summary(ctx):
    j = ctx.job
    texts = ctx.st.read_json(ctx.id, "texts.json", {})
    summ = [c for c in j["plan"]["chapters"] if c["kind"] == "summary"]
    if summ and f"{summ[0]['key']}:summary" not in texts:
        ctx.progress("summary", 0.2, "Writing the summary and conclusion")
        digests = []
        for c in j["plan"]["chapters"]:
            if c["kind"] in ("intro", "narrative", "discussion"):
                body = " ".join(CITE.sub("", texts.get(f"{c['key']}:{i}", "")) for i in range(len(c.get("sections", []))))
                digests.append(f"## {c['title']}\n" + " ".join(body.split()[:2500]))
        texts[f"{summ[0]['key']}:summary"] = ctx.llm.generate(
            prompts.SUMMARY.format(summary_structure=(
                "continuous paragraphs only, with NO sub-headings of any kind: first summarise the dissertation, "
                "then give the conclusions." if j["plan"].get("fixed_headings") else
                'two to four paragraphs summarising the dissertation, then a line "### Conclusion" followed by one '
                'or two paragraphs of conclusions, then "### Recommendations" with 3-6 short bullet points ("- ") '
                "for clinical practice and future research."), words=summ[0]["words"], title=j["details"]["title"], digests="\n\n".join(digests)),
            task="summary", system=prompts.SYSTEM_WRITER, temperature=0.4, max_tokens=8000)
        ctx.st.write_json(ctx.id, "texts.json", texts, force=True)
    ctx.mark("summary")


# ---------------------------------------------------------------- assembly
def _compress(nums):
    nums = sorted(set(nums))
    out, i = [], 0
    while i < len(nums):
        k = i
        while k + 1 < len(nums) and nums[k + 1] == nums[k] + 1:
            k += 1
        out.append(f"{nums[i]}-{nums[k]}" if k - i >= 2 else ",".join(map(str, nums[i:k + 1])))
        i = k + 1
    return ",".join(out)


def abbreviations(all_text):
    found = {}
    for m in re.finditer(r"((?:[A-Za-z][\w\-]*\s+){1,7})\(([A-Z][A-Za-z0-9\-]{1,7}s?)\)", all_text):
        abbr = m.group(2)
        letters = [c for c in abbr.rstrip("s") if c.isupper()]
        wordsb = m.group(1).split()
        for n in range(len(letters), min(len(wordsb), len(letters) + 3) + 1):
            cand = wordsb[-n:]
            if "".join(w[0].upper() for w in cand if w[0].isalpha() and w.lower() not in ("of", "and", "the", "in", "for", "with"))[:len(letters)] == "".join(letters):
                found.setdefault(abbr.rstrip("s") if abbr.endswith("s") and abbr[:-1].isupper() else abbr,
                                 " ".join(cand).strip(" ,;:").lower().capitalize())
                break
    return sorted(found.items(), key=lambda x: x[0].lower())


def stage_assemble(ctx):
    j = ctx.job
    ctx.progress("assemble", 0.1, "Building the Word file")
    lib = {s["sid"]: s for s in ctx.st.read_json(ctx.id, "library.json", [])}
    visuals = ctx.st.read_json(ctx.id, "visuals.json", [])
    texts = ctx.st.read_json(ctx.id, "texts.json", {})
    entries = ctx.st.read_json(ctx.id, "review_entries.json", {}) or {}
    numbering = {}
    dropped = Counter()
    qa_names = []

    def num(sid):
        if sid not in numbering:
            numbering[sid] = len(numbering) + 1
        return numbering[sid]

    def convert(text):
        def rep(m):
            ids = [x for x in re.findall(r"S\d+", m.group(1))]
            good = [x for x in ids if x in lib]
            for x in ids:
                if x not in lib:
                    dropped[x] += 1
            return "⟦" + _compress([num(x) for x in good]) + "⟧" if good else ""
        out = CITE.sub(rep, text)
        # name checks: "Smith et al. (2010)" must belong to a source cited in the same paragraph
        for para in out.split("\n\n"):
            cited = set(re.findall(r"⟦([^⟧]+)⟧", para))
            nums = set()
            for c in cited:
                for part in c.split(","):
                    if "-" in part:
                        a, b = part.split("-")
                        nums |= set(range(int(a), int(b) + 1))
                    elif part.strip().isdigit():
                        nums.add(int(part))
            surnames = {lib[s]["authors"][0].split(" ")[0].lower() for s, n in numbering.items() if n in nums and lib[s].get("authors")}
            for m in re.finditer(r"\b([A-Z][A-Za-z'\-]+)(?: et al\.?| and [A-Z][A-Za-z'\-]+)? \((\d{4})\)", para):
                if m.group(1).lower() not in surnames:
                    qa_names.append(m.group(0))
        return out

    chapters = []
    words_by_ch = {}
    for c in j["plan"]["chapters"]:
        blocks = []
        w = 0
        if c["kind"] == "aims":
            a = texts.get(f"{c['key']}:aims") or {}
            blocks.append({"type": "aims", "aim": a.get("aim") or j["details"].get("aim", ""),
                           "objectives": a.get("objectives") or j["details"].get("objectives", [])})
            w = words(a.get("aim", "")) + sum(words(o) for o in a.get("objectives", []))
        elif c["kind"] == "review":
            r = texts.get(f"{c['key']}:review") or {}
            for sid in r.get("order", []):
                s = lib.get(sid)
                if not s or sid not in entries:
                    continue
                lead = src.Source.from_dict(s).short_cite()
                blocks.append({"type": "entry", "lead": lead, "text": entries[sid].rstrip(".") + "." + f"⟦{num(sid)}⟧"})
                w += words(entries[sid]) + 4
        elif c["kind"] == "summary":
            t = texts.get(f"{c['key']}:summary", "")
            if j["plan"].get("fixed_headings"):
                t = _strip_headings(t)
            blocks.append({"type": "text", "text": CITE.sub("", t)})
            w = words(t)
        else:
            for i, sec in enumerate(c.get("sections", [])):
                t = texts.get(f"{c['key']}:{i}", "")
                fixed = j["plan"].get("fixed_headings")
                if fixed:
                    t = _strip_headings(t)
                if len(c["sections"]) > 1 or sec["title"].lower() != c["title"].lower():
                    blocks.append({"type": "h2", "text": sec["title"] if fixed else sec["title"].upper()})
                blocks.append({"type": "text", "text": convert(t)})
                w += words(t)
                for v in sorted([v for v in visuals if v["chapter"] == c["key"] and v["after_section"] == i],
                                key=lambda v: (v["kind"] != "table", v["number"])):
                    note = ""
                    if v.get("source_sids"):
                        note = "Source: adapted from references " + "⟦" + _compress([num(x) for x in v["source_sids"]]) + "⟧"
                        note = note.replace("⟦", "").replace("⟧", "")
                    if v["kind"] == "table":
                        blocks.append({"type": "table", "number": v["number"], "title": v.get("title") or v["plan_title"],
                                       "columns": v["columns"], "rows": v["rows"],
                                       "note": (v.get("note", "") + " " + note).strip()})
                    else:
                        blocks.append({"type": "figure", "number": v["number"], "title": v.get("title") or v["plan_title"],
                                       "png": render_flowchart(v), "note": note})
        words_by_ch[c["title"]] = (w, c.get("words", 0))
        chapters.append({"display": c["title"] if j["plan"].get("fixed_headings") else None,
                         "title": c["title"], "header": c["title"].title() if c["title"].isupper() else c["title"],
                         "blocks": blocks})

    refs = [src.Source.from_dict(lib[sid]).vancouver() for sid, _ in sorted(numbering.items(), key=lambda x: x[1])]
    all_text = "\n".join(texts[k] for k in texts if isinstance(texts[k], str))
    d = dict(j["details"])
    d["department_full"] = j["department"]
    d["university"] = d.get("university") or j["settings"].get("university", "")
    model = {"front_matter": j.get("front_matter", True), "settings": j["settings"], "details": d, "chapters": chapters, "references": refs,
             "abbreviations": abbreviations(CITE.sub("", all_text)) if j.get("abbreviations", True) else [],
             "n_tables": sum(v["kind"] == "table" for v in visuals), "n_figures": sum(v["kind"] == "flowchart" for v in visuals)}
    ctx.progress("assemble", 0.6, "Saving the Word file")
    data = build_document(model)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", d["title"])[:60].strip("_") or "Dissertation"
    name = f"{safe}.docx"
    ctx.st.write_bytes(ctx.id, name, data)
    j["output_name"] = name

    # quality report
    wpp = j["budget"]["words_per_page"]
    total_words = sum(v[0] for v in words_by_ch.values())
    est_pages = total_words / wpp + j["budget"]["deducted_pages"] * (len(refs) / max(1, j["budget"]["references"]))
    lines = [f"Quality report – {d['title']}", "",
             f"Estimated length: about {est_pages:.0f} pages (target {j['pages']}).",
             f"References cited: {len(refs)} (all taken from Europe PMC, PubMed or Crossref records).",
             f"Tables: {model['n_tables']}  ·  Flowcharts: {model['n_figures']}", "",
             "Words per chapter (written / planned):"]
    for t, (w, p) in words_by_ch.items():
        lines.append(f"  {t}: {w} / {p}")
    if dropped:
        lines += ["", f"Citations removed because they pointed outside the library: {sum(dropped.values())}"]
    if qa_names:
        lines += ["", "Author names in the text that do not match a citation in the same paragraph (check these):"]
        lines += [f"  {x}" for x in sorted(set(qa_names))[:40]]
    if j.get("front_matter", True):
        lines += ["", "Still to fill in Word (shown in red): candidate, guide, HOD and principal names if missing, "
                      "acknowledgement, place and dates.",
                  "On opening in Word, choose Yes to update fields so the contents, list of tables and list of figures fill in."]
    j["qa"] = "\n".join(lines)
    ctx.st.write_bytes(ctx.id, "quality_report.txt", j["qa"].encode("utf-8"))
    ctx.mark("assemble")


STAGE_FN = {"analyse": stage_analyse, "plan": stage_plan, "library": stage_library, "visuals": stage_visuals,
            "write": stage_write, "summary": stage_summary, "assemble": stage_assemble}


def run(ctx: Ctx, only: str | None = None):
    j = ctx.job
    if ctx.llm is not None:
        j["_tok_in0"] = (j.get("tokens") or {}).get("in", 0)
        j["_tok_out0"] = (j.get("tokens") or {}).get("out", 0)
    j["status"] = "running"
    j.pop("error", None)
    ctx.save(force=True)
    try:
        for stage in STAGES:
            if only and stage != only:
                continue
            if ctx.done(stage) and not only:
                continue
            ctx.check_stop()
            j["stage"] = stage
            STAGE_FN[stage](ctx)
            if only:
                j.setdefault("stages_done", [])
        j["status"] = "done"
        j["progress"] = 1.0
        ctx.log("Finished. The Word file is ready to download.")
    except Stopped:
        if j.get("status") != "awaiting_approval":
            j["status"] = "stopped"
            ctx.log("Stopped. Press Resume to continue from here.")
    except Exception as e:
        j["status"] = "failed"
        j["error"] = f"{e}"
        j["trace"] = traceback.format_exc()[-3000:]
        ctx.log(f"Stopped with an error: {str(e)[:300]}")
    finally:
        ctx.save(force=True)
        ctx.st.flush(ctx.id)
