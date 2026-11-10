"""MDS Library Dissertation Builder – Streamlit app.

Run locally:  streamlit run app.py
Secrets (Streamlit Cloud → App settings → Secrets, or .streamlit/secrets.toml):
  APP_PASSWORD (recommended), optional GITHUB_TOKEN, GITHUB_REPO, NCBI_API_KEY
The Gemini API key is typed into the sidebar of the app itself.
"""
from __future__ import annotations

import hmac
import os

import streamlit as st

import ld_config as config
import ld_jobs as jobs
import ld_pipeline as pipeline
import ld_sources as src
from ld_storage import GitHubStorage, LocalStorage

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
NCBI = secret("NCBI_API_KEY")


def api_key():
    """The key typed in the sidebar (kept only for this browser session), or one from Secrets if set."""
    return (st.session_state.get("gemini_key") or "").strip() or secret("GEMINI_API_KEY")


def model_name():
    return st.session_state.get("model") or "gemini-2.5-pro"


def llm_factory(key, model):
    def make():
        from ld_llm import GeminiLLM
        return GeminiLLM(key, model)
    return make


def start(job_id, only=None):
    key = api_key()
    if not key:
        st.error("Enter your Gemini API key in the sidebar first (🔑 Gemini API key).")
        return
    manager.start(storage, job_id, llm_factory(key, model_name()), pubmed_key=NCBI,
                  workers=st.session_state.get("workers", 4), only=only)


@st.cache_data(ttl=3600, show_spinner=False)
def list_models(key):
    from ld_llm import GeminiLLM
    return GeminiLLM(key, "x").list_models()


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("🔑 Gemini")
    st.text_input("Gemini API key", type="password", key="gemini_key",
                  placeholder="Paste your key (AIza…)",
                  help="Get it from aistudio.google.com → Get API key. It is kept only in this browser "
                       "session and is never saved to GitHub or to disk. Enter it again on each new device "
                       "or after refreshing the page.")
    key = api_key()
    opts, err = [], ""
    if key:
        try:
            opts = list_models(key)
        except Exception as e:
            err = str(e)[:200]
    if err:
        st.error(f"Key not accepted: {err}")
    elif key and opts:
        st.success(f"Key OK – {len(opts)} models available")
    preferred = ["gemini-2.5-pro", "gemini-2.5-flash"]
    ordered = [m for m in preferred if m in opts] + [m for m in opts if m not in preferred]
    if not ordered:
        ordered = preferred
    st.selectbox("Model", ordered, index=0, key="model",
                 help="Pro writes the best dissertations; Flash is faster and cheaper. "
                      "Newer models appear here automatically.")
    if st.button("🔌 Test connection", use_container_width=True, disabled=not key):
        with st.spinner("Checking Gemini and the literature databases…"):
            res = {}
            try:
                from ld_llm import GeminiLLM
                reply = GeminiLLM(key, model_name()).generate("Reply with the single word OK.",
                                                             max_tokens=2000, temperature=0)
                res[f"Gemini ({model_name()})"] = "OK" if reply else "Empty reply"
            except Exception as e:
                res[f"Gemini ({model_name()})"] = f"Failed: {str(e)[:200]}"
            res.update(src.check_connections(NCBI))
            import ld_images
            res["Wikimedia Commons (images)"] = ld_images.check()
            if isinstance(storage, GitHubStorage):
                try:
                    res["GitHub storage"] = storage.check()
                except Exception as e:
                    res["GitHub storage"] = f"Failed: {e}"
        for k, v in res.items():
            (st.success if str(v).startswith("OK") else st.error)(f"{k}: {v}")
    st.divider()
    st.slider("Parallel writers", 1, 8, 4, key="workers",
              help="How many sections are written at the same time. Lower it if you see rate-limit errors.")
    st.caption(f"Dissertations are saved in {storage.label}.")

st.title("🦷 MDS Library Dissertation Builder")
tab_new, tab_jobs = st.tabs(["➕ New dissertation", "📚 My dissertations"])

# ---------------------------------------------------------------- new job
with tab_new:
    c1, c2 = st.columns([3, 2])
    with c1:
        topic = st.text_input("Topic / title (optional if your file or text has it)",
                              placeholder="e.g. Lasers in gingival depigmentation – a review")
        dept = st.selectbox("Department *", list(config.DEPARTMENTS))
        syn_mode = st.radio("Synopsis (optional but recommended)", ["📎 Upload file", "📝 Paste text"],
                            horizontal=True)
        syn, syn_text = None, ""
        if syn_mode == "📎 Upload file":
            syn = st.file_uploader("Synopsis file (PDF, Word or text)", type=["pdf", "docx", "txt", "md"])
        else:
            syn_text = st.text_area("Paste the synopsis here", height=260,
                                    placeholder="Title, introduction, aim, objectives, need for the study, "
                                                "methodology, references … paste everything you have.")
            if syn_text.strip():
                st.caption(f"{len(syn_text.split()):,} words pasted")
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
        n_images = st.slider("Images from the web", 0, 7, 6,
                             help="Openly licensed pictures (Wikimedia Commons and open-access journal figures), "
                                  "chosen by Gemini to match your chapters, each credited under the figure.")
        st.markdown("**Headings**")
        strict = st.checkbox("Use ONLY the headings in my synopsis – no new headings", True,
                             help="The chapters and sub-headings are copied exactly from your pasted text or "
                                  "file, in the same order. Nothing is added or renamed. The writer adds no "
                                  "sub-headings of its own.")
        st.markdown("**What to include**")
        front_matter = st.checkbox("Front pages (title page, declaration, certificates, contents lists)", False)
        include_aims = st.checkbox("Aims and Objectives chapter", False)
        include_review = st.checkbox("Review of Literature chapter", True,
                                     help="Ignored if your file lists its own headings.")
        if strict:
            st.caption("Aims and Review of Literature appear only if they are among your headings.")
        review_outline = st.checkbox("Let me check the chapter plan before writing", True)
    wpp = config.words_per_page(p["line_spacing"], p["size"])
    st.caption(f"About {pages * wpp:,} words and roughly {config.reference_target(pages)} references.")
    with st.expander("Front-page details (only used when front pages are ticked)"):
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
    if strict and not (syn or syn_text.strip()):
        st.warning("Paste or upload your synopsis with its headings – the chapters are taken from it.")
    if st.button("🚀 Generate dissertation", type="primary", disabled=not (syn or syn_text.strip()) if strict else not (topic.strip() or syn or syn_text.strip())):
        jid = jobs.create_job(storage, topic=topic, department=dept, pages=pages, settings=p,
                              synopsis_name=syn.name if syn else ("pasted_synopsis.txt" if syn_text.strip() else None),
                              synopsis_bytes=syn.getvalue() if syn else (syn_text.encode("utf-8") if syn_text.strip() else None),
                              n_tables=n_tables, n_figures=n_figs, include_review=include_review,
                              review_outline=review_outline, details=det,
                              front_matter=front_matter, include_aims=include_aims, n_images=n_images,
                              strict_headings=strict and bool(syn or syn_text.strip()))
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
                   "lines starting with `- ` are sections as `- Section :: what it should cover` "
                   "(`-- ` for a sub-section). "
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
            stage = st.selectbox("Redo from", ["write", "visuals", "images", "library", "plan"], key=f"redo{jid}",
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
