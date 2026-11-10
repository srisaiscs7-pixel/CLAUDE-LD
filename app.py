"""MDS Library Dissertation Builder – Streamlit app.

Run locally:  streamlit run app.py
Secrets (Streamlit Cloud → App settings → Secrets, or .streamlit/secrets.toml):
  GEMINI_API_KEY, APP_PASSWORD, optional GEMINI_MODEL, GITHUB_TOKEN, GITHUB_REPO, NCBI_API_KEY
"""
from __future__ import annotations

import hmac
import os

import streamlit as st

from dissertation import config, jobs, pipeline
from dissertation import sources as src
from dissertation.storage import GitHubStorage, LocalStorage

st.set_page_config(page_title="MDS Library Dissertation Builder", page_icon="🦷", layout="wide")


def secret(name, default=""):
    try:
        return st.secrets.get(name, os.environ.get(name, default))
    except Exception:
        return os.environ.get(name, default)


# ---------------------------------------------------------------- password
def gate():
    pw = secret("APP_PASSWORD")
    if not pw:
        st.warning("No APP_PASSWORD is set, so anyone with the link can use this app (and your Gemini key). "
                   "Add APP_PASSWORD in the app's Secrets.")
        return
    if st.session_state.get("ok"):
        return
    st.title("🦷 MDS Library Dissertation Builder")
    with st.form("login"):
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Open"):
            if hmac.compare_digest(p.encode(), str(pw).encode()):
                st.session_state.ok = True
                st.rerun()
            st.error("Wrong password")
    st.stop()


gate()


# ---------------------------------------------------------------- shared objects
@st.cache_resource
def get_storage():
    tok, repo = secret("GITHUB_TOKEN"), secret("GITHUB_REPO")
    if tok and repo:
        return GitHubStorage(tok, repo)
    return LocalStorage()


@st.cache_resource
def get_manager():
    return jobs.JobManager()


storage = get_storage()
manager = get_manager()
API_KEY = secret("GEMINI_API_KEY")
NCBI = secret("NCBI_API_KEY")


def model_name():
    return st.session_state.get("model") or secret("GEMINI_MODEL", "gemini-2.5-pro")


def llm_factory(model):
    def make():
        from dissertation.llm import GeminiLLM
        return GeminiLLM(API_KEY, model)
    return make


def start(job_id, only=None):
    if not API_KEY:
        st.error("GEMINI_API_KEY is missing from the app's Secrets.")
        return
    manager.start(storage, job_id, llm_factory(model_name()), pubmed_key=NCBI,
                  workers=st.session_state.get("workers", 4), only=only)


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Settings")
    st.caption(f"Jobs are saved in {storage.label}.")

    @st.cache_data(ttl=3600, show_spinner=False)
    def models(key):
        try:
            from dissertation.llm import GeminiLLM
            return GeminiLLM(key, "x").list_models()
        except Exception:
            return []
    opts = models(API_KEY) if API_KEY else []
    default = secret("GEMINI_MODEL", "gemini-2.5-pro")
    if default not in opts:
        opts = [default] + opts
    st.selectbox("Gemini model", opts, index=0, key="model",
                 help="Pro writes better; Flash is faster and cheaper.")
    st.slider("Parallel writers", 1, 8, 4, key="workers",
              help="How many sections are written at the same time. Lower it if you see rate-limit errors.")
    if st.button("Test connections"):
        with st.spinner("Checking…"):
            res = src.check_connections()
            if API_KEY:
                try:
                    from dissertation.llm import GeminiLLM
                    GeminiLLM(API_KEY, model_name()).generate("Reply with OK", max_tokens=20, temperature=0)
                    res["Gemini"] = "OK"
                except Exception as e:
                    res["Gemini"] = f"Failed: {str(e)[:150]}"
            else:
                res["Gemini"] = "No GEMINI_API_KEY in Secrets"
            if isinstance(storage, GitHubStorage):
                try:
                    res["GitHub storage"] = storage.check()
                except Exception as e:
                    res["GitHub storage"] = f"Failed: {e}"
        for k, v in res.items():
            (st.success if str(v).startswith("OK") else st.error)(f"{k}: {v}")

st.title("🦷 MDS Library Dissertation Builder")
tab_new, tab_jobs = st.tabs(["➕ New dissertation", "📚 My dissertations"])

# ---------------------------------------------------------------- new job
with tab_new:
    c1, c2 = st.columns([3, 2])
    with c1:
        topic = st.text_input("Dissertation topic / title *",
                              placeholder="e.g. Lasers in gingival depigmentation – a review")
        dept = st.selectbox("Department *", list(config.DEPARTMENTS))
        syn = st.file_uploader("Synopsis (PDF, Word or text) – optional but recommended",
                               type=["pdf", "docx", "txt", "md"])
        pages = st.slider("Number of pages (main text, excluding front pages)", 1, 150, 60)
        wpp_preview = None
    with c2:
        preset = st.selectbox("University format", list(config.UNIVERSITY_PRESETS))
        p = jobs.settings_from_preset(preset)
        with st.expander("Page format (change if your university differs)"):
            p["font"] = st.selectbox("Font", config.FONTS, index=config.FONTS.index(p["font"]))
            p["size"] = st.selectbox("Font size", [11, 12, 13], index=[11, 12, 13].index(p["size"]))
            p["line_spacing"] = st.selectbox("Line spacing", [1.0, 1.15, 1.5, 2.0],
                                             index=[1.0, 1.15, 1.5, 2.0].index(p["line_spacing"]))
            m = p["margins_cm"]
            mc = st.columns(4)
            p["margins_cm"] = [mc[i].number_input(lab, 1.0, 5.0, float(m[i]), 0.1)
                               for i, lab in enumerate(["Top", "Right", "Bottom", "Left (binding)"])]
            p["page_border"] = st.checkbox("Page border", p["page_border"])
            p["divider_pages"] = st.checkbox("Chapter divider pages", p["divider_pages"])
            p["page_number_pos"] = st.radio("Page number", ["center", "right"],
                                            index=0 if p["page_number_pos"] == "center" else 1, horizontal=True)
        n_tables = st.slider("Tables", 2, 4, 3)
        n_figs = st.slider("Flowcharts", 1, 2, 1)
        include_review = st.checkbox("Include a 'Review of Literature' chapter", True)
        review_outline = st.checkbox("Let me check the chapter plan before writing", True)
    wpp = config.words_per_page(p["line_spacing"], p["size"])
    st.caption(f"About {pages * wpp:,} words and roughly {config.reference_target(pages)} references.")
    with st.expander("Front-page details (optional – read from the synopsis if left blank)"):
        d1, d2 = st.columns(2)
        det = {
            "candidate_name": d1.text_input("Candidate name (without Dr.)"),
            "guide_name": d1.text_input("Guide name (without Dr.)"),
            "guide_designation": d1.text_input("Guide designation", placeholder="Professor and Head"),
            "hod_name": d1.text_input("HOD name (without Dr.)"),
            "principal_name": d2.text_input("Principal name (without Dr.)"),
            "college": d2.text_input("College"),
            "university": d2.text_input("University", value=p.get("university", "")),
            "academic_year": d2.text_input("Academic year", placeholder="2024–2027"),
            "place": d2.text_input("Place"),
        }
    if st.button("🚀 Generate dissertation", type="primary", disabled=not topic.strip()):
        jid = jobs.create_job(storage, topic=topic, department=dept, pages=pages, settings=p,
                              synopsis_name=syn.name if syn else None, synopsis_bytes=syn.getvalue() if syn else None,
                              n_tables=n_tables, n_figures=n_figs, include_review=include_review,
                              review_outline=review_outline, details=det)
        start(jid)
        st.session_state.open_job = jid
        st.success("Started. Follow it in **My dissertations** – you can close this page and come back later "
                   "from any device.")


# ---------------------------------------------------------------- job list
STATUS_ICON = {"queued": "⏳", "running": "⚙️", "awaiting_approval": "📝", "done": "✅", "failed": "⚠️",
               "stopped": "⏸️", "interrupted": "⏸️"}


def job_view(jid):
    job = storage.read_json(jid, "job.json")
    if not job:
        st.error("Job not found")
        return
    running = manager.is_running(jid)
    if job["status"] in ("running", "queued") and not running:
        job["status"] = "interrupted"
    st.subheader(job["details"].get("title") or job["topic"])
    st.caption(f"{job['department']} · {job['pages']} pages · started {job['created'].replace('T', ' ')}")
    st.progress(float(job.get("progress", 0)),
                text=f"{STATUS_ICON.get(job['status'], '')} {pipeline.STAGE_LABEL.get(job.get('stage'), '')} – "
                     f"{job.get('message', '')}")
    tok = job.get("tokens") or {}
    if tok:
        st.caption(f"Gemini usage so far: {tok.get('in', 0):,} input and {tok.get('out', 0):,} output tokens")

    b = st.columns(5)
    if running:
        if b[0].button("⏸ Stop", key=f"stop{jid}"):
            manager.stop(jid)
            st.info("Stopping after the current step…")
    elif job["status"] in ("failed", "stopped", "interrupted", "queued"):
        if b[0].button("▶ Resume", key=f"res{jid}", type="primary"):
            start(jid)
            st.rerun()

    if job["status"] == "awaiting_approval" and not running:
        st.markdown("#### Check the chapter plan")
        st.caption("Edit freely: lines starting with `# ` are chapters as `# Title [kind] (weight%)`; "
                   "lines starting with `- ` are sections as `- Section :: what it should cover`. "
                   "Kinds: intro, aims, narrative, review, discussion, summary.")
        txt = st.text_area("Chapter plan", jobs.outline_to_text(job["plan"]), height=420, key=f"ol{jid}")
        bud = job.get("budget", {})
        st.caption(f"≈ {bud.get('prose_words', 0):,} words of text, {bud.get('references', 0)} references planned.")
        if st.button("✅ Approve and continue", key=f"ap{jid}", type="primary"):
            try:
                jobs.apply_outline(storage, jid, txt)
                start(jid)
                st.rerun()
            except Exception as e:
                st.error(str(e))

    if job["status"] == "done" and job.get("output_name"):
        data = storage.read_bytes(jid, job["output_name"])
        if data:
            st.download_button("⬇️ Download Word file", data, file_name=job["output_name"], type="primary",
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               key=f"dl{jid}")
        st.info("When Word asks to update fields, press **Yes** – that fills the contents, list of tables and "
                "list of figures. Red text marks details still to fill in.")
        with st.expander("Quality report"):
            st.text(job.get("qa", ""))

    if job.get("error"):
        st.error(job["error"])
    if not running and job["status"] != "awaiting_approval" and "plan" in job:
        with st.expander("✏️ Edit front-page details and rebuild the Word file (no new writing)"):
            d = job["details"]
            keys = ["title", "candidate_name", "guide_name", "guide_designation", "hod_name", "principal_name",
                    "college", "university", "academic_year", "place"]
            cols = st.columns(2)
            new = {k: cols[i % 2].text_input(k.replace("_", " ").capitalize(), d.get(k, ""), key=f"{k}{jid}")
                   for i, k in enumerate(keys)}
            if st.button("Rebuild Word file", key=f"rb{jid}"):
                job = storage.read_json(jid, "job.json")
                job["details"].update(new)
                storage.write_json(jid, "job.json", job, force=True)
                if "summary" in job.get("stages_done", []):
                    jobs.reset_from(storage, jid, "assemble")
                    start(jid)
                    st.rerun()
                else:
                    st.success("Saved. They will be used when the job finishes.")
        with st.expander("🔁 Redo part of the work"):
            stage = st.selectbox("Redo from", ["write", "visuals", "library", "plan"], key=f"redo{jid}",
                                 format_func=lambda s: pipeline.STAGE_LABEL[s])
            st.caption("Everything after this step is redone (costs Gemini tokens again).")
            if st.button("Redo", key=f"rd{jid}"):
                jobs.reset_from(storage, jid, stage)
                start(jid)
                st.rerun()
    with st.expander("Activity log"):
        st.code("\n".join(job.get("log", [])[-60:]) or "—", language=None)
    lib = storage.read_json(jid, "library.json", [])
    if lib:
        with st.expander(f"Reference library ({len(lib)} papers found)"):
            for s in lib[:200]:
                link = f"https://doi.org/{s['doi']}" if s.get("doi") else (
                    f"https://pubmed.ncbi.nlm.nih.gov/{s['pmid']}/" if s.get("pmid") else "")
                st.markdown(f"- {src.Source.from_dict(s).vancouver()} " + (f"[link]({link})" if link else ""))
    if not running and st.button("🗑 Delete this dissertation", key=f"del{jid}"):
        storage.delete_job(jid)
        st.session_state.pop("open_job", None)
        st.rerun()


with tab_jobs:
    ids = storage.list_jobs()
    if not ids:
        st.info("No dissertations yet.")
    else:
        labels = {}
        for i in ids[:50]:
            j = storage.read_json(i, "job.json") or {}
            status = j.get("status", "?")
            if status in ("running", "queued") and not manager.is_running(i):
                status = "interrupted"
            labels[i] = f"{STATUS_ICON.get(status, '')} {(j.get('details') or {}).get('title') or j.get('topic', i)[:80]}  ·  {i[:8]}"
        cur = st.session_state.get("open_job", ids[0])
        jid = st.selectbox("Dissertation", list(labels), index=list(labels).index(cur) if cur in labels else 0,
                           format_func=lambda x: labels[x])
        st.session_state.open_job = jid

        @st.fragment(run_every=5)
        def live():
            job_view(jid)
        if manager.is_running(jid):
            live()
        else:
            job_view(jid)
