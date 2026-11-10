# MDS Library Dissertation Builder

A private web app: upload a synopsis, type the topic, choose the department and the number of pages
(1–150), and it builds a formatted Word dissertation with:

- front pages (title page, declaration, guide certificate, HOD/principal endorsement, copyright,
  acknowledgement, contents, list of tables, list of figures, abbreviations)
- Introduction, Aims and Objectives, topic chapters, Review of Literature, Discussion, Summary and Conclusion
- 2–4 tables and 1–2 flowcharts, numbered and captioned
- Vancouver references, numbered in order of citation, **all taken from real Europe PMC, PubMed or Crossref
  records** – the writer can only cite papers found in those databases, so no reference is invented

It runs on Streamlit Community Cloud (free), so you can open it from your phone, laptop or any computer.

---

## One-time setup (about 20 minutes)

### 1. Put the code on GitHub
1. Sign in at **github.com** → top-right **+** → **New repository**.
2. Name it `mds-dissertation-app`, choose **Private**, tick nothing else, press **Create repository**.
3. On the next page click **uploading an existing file**.
4. Unzip `mds-dissertation-app.zip` on your computer, open the folder, select **everything inside it**
   (including the `.streamlit` folder – on Mac press ⌘⇧. to show hidden folders) and drag it into the page.
5. Press **Commit changes**.

### 2. (Recommended) Make a second private repo for saving your work
Streamlit's free servers forget files when the app restarts. To keep every dissertation safe and
available on all your devices, give the app a place to store them:

1. Create another **Private** repository called `mds-dissertation-data`. This time tick
   **Add a README file** (the repo must not be empty).
2. Go to **github.com/settings/personal-access-tokens** → **Generate new token** (fine-grained).
   - Name: `dissertation app`, Expiration: 1 year
   - Repository access: **Only select repositories** → `mds-dissertation-data`
   - Permissions → Repository permissions → **Contents: Read and write**
   - **Generate token** and copy it (starts with `github_pat_`). You will not see it again.

### 3. Deploy on Streamlit Community Cloud
1. Go to **share.streamlit.io** and sign in with GitHub (allow access to private repos when asked).
2. **Create app** → **Deploy a public app from GitHub** (the app itself is still protected by your password).
3. Repository: `your-username/mds-dissertation-app`, Branch: `main`, Main file: `app.py`.
4. Open **Advanced settings** → Python 3.11 or 3.12, and paste into **Secrets**:

```toml
GEMINI_API_KEY = "your Gemini key"
APP_PASSWORD = "a password you will remember"
GEMINI_MODEL = "gemini-2.5-pro"

GITHUB_TOKEN = "github_pat_...."
GITHUB_REPO = "your-username/mds-dissertation-data"
```

5. Press **Deploy**. After 2–3 minutes you get a link like `https://something.streamlit.app`.
   Bookmark it on every device.
6. Optional: in the app's **Settings → Sharing**, set "Who can view this app" to only you.

### 4. First check
Open the app, enter the password, and press **Test connections** in the sidebar. All four lines
(Europe PMC, PubMed, Crossref, Gemini – and GitHub storage if set) should say OK.

---

## Using it
1. **New dissertation** tab: topic, department, synopsis file, pages, university format, number of tables
   and flowcharts. Front-page names are optional (they are read from the synopsis when present; anything
   missing appears in **red** in Word for you to fill in).
2. Press **Generate**. Keep "Let me check the chapter plan" ticked: after about a minute it stops and shows
   the chapter plan. Edit the chapter and section lines if you want, then press **Approve and continue**.
3. Writing runs on the server. You can close the browser and come back later from any device:
   **My dissertations** shows progress. If it stops (error or app restart) press **Resume** – finished
   parts are kept.
4. When it says done, press **Download Word file**. When Word asks to **update fields**, press **Yes**
   so the contents, list of tables and list of figures fill in with page numbers.
5. Read the **Quality report** and check the list of author names it flags.

Typical time: 60 pages ≈ 15–30 minutes; 150 pages ≈ 40–70 minutes (depends on the Gemini model).

**Changing the Gemini model:** pick it in the sidebar (Pro writes best; Flash is faster and cheaper).
If you see rate-limit errors, lower **Parallel writers**.

---

## Please read before submitting
- The text is written fresh by Gemini from the abstracts (and open-access full texts) of the papers it
  found, with a citation on each finding. It is a strong first draft, **not a finished dissertation**:
  read every chapter, check the key facts against the papers (each reference has a DOI/PubMed link in
  the app's "Reference library"), and rewrite in your own words where needed. Your guide and
  university expect the work to be yours.
- Very short targets (under ~15 pages) come out a little longer than asked, because every chapter needs
  a minimum amount of text.
- The app never pastes text from websites, so the plagiarism score is normally low, but run your
  college's checker anyway.

## Files
| Path | What it does |
|---|---|
| `app.py` | the web app (password, forms, progress, downloads) |
| `dissertation/sources.py` | Europe PMC / PubMed / Crossref search, Vancouver formatting |
| `dissertation/pipeline.py` | plan → references → tables/flowcharts → writing → Word |
| `dissertation/prompts.py` | all instructions sent to Gemini (edit here to change style) |
| `dissertation/docbuilder.py` | Word layout: margins, borders, headers, page numbers, captions |
| `dissertation/config.py` | departments, university formats, words-per-page maths |
| `dissertation/storage.py` | saving jobs locally and in your private GitHub repo |
| `tests/test_offline.py` | test run without internet or a key (`python -m tests.test_offline 40`) |

## Running on your own computer instead
```
pip install -r requirements.txt
copy .streamlit/secrets.toml.example to .streamlit/secrets.toml and fill it in
streamlit run app.py
```
