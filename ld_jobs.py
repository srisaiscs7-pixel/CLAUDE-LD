"""Start, stop and resume dissertation jobs in background threads."""
from __future__ import annotations

import base64
import threading
import uuid
from datetime import datetime

import ld_config as config
import ld_pipeline as pipeline
from ld_synopsis import read_text


class JobManager:
    """One per app process (kept with st.cache_resource), so threads survive page reloads."""

    def __init__(self):
        self.threads: dict[str, threading.Thread] = {}
        self.stops: dict[str, threading.Event] = {}
        self.lock = threading.Lock()

    def is_running(self, job_id):
        t = self.threads.get(job_id)
        return bool(t and t.is_alive())

    def start(self, storage, job_id, llm_factory, pubmed_key="", workers=4, only=None):
        with self.lock:
            if self.is_running(job_id):
                return False
            stop = threading.Event()
            self.stops[job_id] = stop

            def target():
                llm = llm_factory()
                ctx = pipeline.Ctx(storage, job_id, llm, stop, pubmed_key=pubmed_key, workers=workers)
                pipeline.run(ctx, only=only)

            t = threading.Thread(target=target, name=f"job-{job_id}", daemon=True)
            self.threads[job_id] = t
            t.start()
            return True

    def stop(self, job_id):
        ev = self.stops.get(job_id)
        if ev:
            ev.set()


def create_job(storage, *, topic, department, pages, settings, synopsis_name=None, synopsis_bytes=None,
               n_tables=3, n_figures=1, include_review=True, review_outline=False, details=None,
               front_matter=False, include_aims=False):
    job_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    text, pdf_b64 = "", ""
    if synopsis_bytes:
        text = read_text(synopsis_name or "synopsis.txt", synopsis_bytes)
        if (synopsis_name or "").lower().endswith(".pdf") and len(text.split()) < 80:
            pdf_b64 = base64.b64encode(synopsis_bytes).decode()
    storage.write_json(job_id, "synopsis.json", {"name": synopsis_name, "text": text, "pdf_b64": pdf_b64}, force=True)
    st = dict(settings)
    st["margins_cm"] = list(st.get("margins_cm", (2.54, 2.54, 2.54, 2.54)))
    job = {
        "id": job_id, "topic": topic.strip(), "department": department, "pages": int(pages),
        "settings": st, "n_tables": int(n_tables), "n_figures": int(n_figures),
        "include_review": include_review, "review_outline": review_outline,
        "front_matter": front_matter, "include_aims": include_aims,
        "details": {k: v for k, v in (details or {}).items() if v},
        "status": "queued", "stage": "analyse", "progress": 0.0, "stages_done": [],
        "created": datetime.now().isoformat(timespec="seconds"), "log": [],
        "message": "Waiting to start",
    }
    storage.write_json(job_id, "job.json", job, force=True)
    return job_id


# ------------------------------------------------------------ outline editing (approve step)
def outline_to_text(plan) -> str:
    lines = []
    for c in plan["chapters"]:
        lines.append(f"# {c['title']} [{c['kind']}] ({c.get('weight', 5)}%)")
        for s in c.get("sections", []):
            lines.append(f"- {s['title']} :: {s.get('brief', '')}")
        lines.append("")
    return "\n".join(lines).strip()


def text_to_outline(text: str, plan: dict) -> dict:
    """Apply an edited outline. Chapters keep their search queries where the title still matches."""
    import re
    old = {c["title"].strip().lower(): c for c in plan["chapters"]}
    chapters = []
    for line in text.splitlines():
        line = line.rstrip()
        if line.startswith("# "):
            m = re.match(r"#\s+(.+?)(?:\s+\[(\w+)\])?(?:\s+\((\d+(?:\.\d+)?)%?\))?\s*$", line)
            title, kind, weight = m.group(1).strip(), (m.group(2) or "narrative").lower(), float(m.group(3) or 8)
            if kind not in ("intro", "aims", "narrative", "review", "discussion", "summary"):
                kind = "narrative"
            prev = old.get(title.lower(), {})
            chapters.append({"title": title, "kind": kind, "weight": weight, "sections": [],
                             "queries": prev.get("queries") or [title], "_old": prev.get("key")})
        elif line.lstrip().startswith("- ") and chapters:
            body = line.lstrip()[2:]
            t, _, b = body.partition("::")
            chapters[-1]["sections"].append({"title": t.strip(), "brief": (b or t).strip()})
    if not chapters:
        raise ValueError("No chapters found. Each chapter line must start with '# '.")
    remap = {}
    for i, c in enumerate(chapters):
        c["key"] = f"c{i + 1}"
        if c.get("_old"):
            remap[c["_old"]] = c["key"]
        c.pop("_old", None)
    new = dict(plan)
    new["chapters"] = chapters
    keys = {c["key"] for c in chapters}
    for kind in ("tables", "flowcharts"):
        items = []
        for v in plan.get(kind, []):
            k = remap.get(v["chapter"])
            if k in keys:
                items.append(dict(v, chapter=k))
        new[kind] = items
    return new


def apply_outline(storage, job_id, text):
    job = storage.read_json(job_id, "job.json")
    job["plan"] = text_to_outline(text, job["plan"])
    pipeline._fill_visual_slots(job["plan"], job.get("n_tables", 3), job.get("n_figures", 1))
    pipeline.budget(job)
    job["status"] = "queued"
    job["review_outline"] = False
    storage.write_json(job_id, "job.json", job, force=True)


def reset_from(storage, job_id, stage):
    """Forget a stage and everything after it, so it runs again."""
    job = storage.read_json(job_id, "job.json")
    idx = pipeline.STAGES.index(stage)
    job["stages_done"] = [s for s in job.get("stages_done", []) if pipeline.STAGES.index(s) < idx]
    later = pipeline.STAGES[idx:]
    if "write" in later:
        storage.write_json(job_id, "texts.json", {}, force=True)
        storage.write_json(job_id, "review_entries.json", {}, force=True)
    if "visuals" in later:
        storage.write_json(job_id, "visuals.json", [], force=True)
    job["status"] = "queued"
    job["progress"] = sum(pipeline.STAGE_WEIGHT[s] for s in pipeline.STAGES[:idx])
    storage.write_json(job_id, "job.json", job, force=True)


def settings_from_preset(name):
    p = dict(config.UNIVERSITY_PRESETS[name])
    p["margins_cm"] = list(p["margins_cm"])
    return p
