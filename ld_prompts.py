"""Prompts sent to Gemini. Kept in one place so they are easy to adjust."""

SYSTEM_WRITER = """You are an experienced academic writer helping an MDS (Master of Dental Surgery) resident in India
write a library dissertation. Write in formal British English in the style of an Indian MDS dissertation:
clear, well-organised paragraphs of 120-200 words, past tense when reporting studies, no marketing language,
no first person, no rhetorical questions.

Strict rules for sources:
- Use ONLY the numbered sources supplied in the prompt. Never mention a study, author, year, statistic or
  finding that is not in those sources.
- Put a citation after every sentence or clause that reports a finding, using the source ID in square
  brackets, e.g. [S12] or [S3; S7]. Never cite an ID that was not supplied. Never write ranges like [S3-S7].
- If you name authors in the text, use exactly the surname and year shown for that source, followed by its
  citation, e.g. "Löe et al. (1965) showed ... [S4]".
- General textbook knowledge that needs no citation (definitions, basic anatomy) may be stated briefly, but
  keep it short and do not attach invented numbers to it.
- Write fresh text; do not copy sentences from the abstracts.
"""

ANALYSE = """Read this MDS library dissertation synopsis and extract the details below. Use empty strings or
empty lists for anything that is not stated. Do not invent names.

Topic entered by the user: {topic}
Department: {department}

Return JSON with exactly these keys:
{{"title": "", "candidate_name": "", "guide_name": "", "guide_designation": "", "co_guide_name": "",
  "college": "", "university": "", "academic_year": "", "aim": "", "objectives": [],
  "scope": "", "keywords": [], "methodology": ""}}

Synopsis:
\"\"\"{text}\"\"\"
"""

PLAN = """Plan the chapters of an MDS library dissertation (a dissertation based entirely on published
literature; there is no clinical study, no patients and no results data).

Title: {title}
Department: {department}
Aim: {aim}
Objectives: {objectives}
Scope / notes from synopsis: {scope}
Uploaded text (may contain the headings or table of contents the user wants):
<<<
{source_text}
>>>
Target length of the main text: about {pages} pages ({words} words of prose in total).

Rules:
- If the uploaded text contains a table of contents, chapter list or list of headings, FOLLOW IT: use those
  headings as the chapters and sections, in the same order and with the same wording (fix only spelling),
  and give each one the closest kind below. Do not add chapters the user did not list, except that you may
  add sections inside a chapter. Otherwise build the outline yourself using the order below.
- {aims_rule}
- Default order: "Introduction" (kind "intro"), then 3-{max_topic} topic
  chapters that cover the subject logically (for example historical background, classification, aetiology,
  materials, techniques, clinical applications, complications, recent advances; choose what fits the
  topic) with kind "narrative", then optionally one "Review of Literature" chapter (kind "review"), then
  "Discussion" (kind "discussion"), then "Summary and Conclusion" (kind "summary").
- {review_rule}
- Give every chapter a "weight" (a relative share of the total length; introduction about 6, aims 1,
  summary 3, discussion about 12, review about 20, topic chapters 8-15 each).
- Give every "intro", "narrative" and "discussion" chapter 2-{max_sections} sections, each with a short
  "brief" saying what it must cover.
- Give every chapter except "aims" and "summary" 3-5 literature search queries in Europe PMC / PubMed
  syntax, e.g. (gingival depigmentation) AND (laser OR scalpel). Keep queries broad enough to return many
  papers; use synonyms with OR; avoid more than three AND blocks.
- Suggest up to {n_landmarks} classic or landmark papers on this topic that a dissertation would normally cite
  (only well-known ones you are confident exist), as first author surname, year and title.
- Suggest {n_tables} tables and {n_figs} flowcharts that would help the reader (for example a classification,
  a comparison of materials or techniques, a timeline, a decision pathway, a treatment protocol). For each,
  name the chapter key and the section index (0-based) after which it should appear.

Return JSON:
{{"chapters": [{{"key": "c1", "title": "", "kind": "", "weight": 0,
   "sections": [{{"title": "", "brief": ""}}], "queries": [""]}}],
  "landmarks": [{{"first_author": "", "year": "", "title": ""}}],
  "tables": [{{"chapter": "c3", "after_section": 0, "title": "", "purpose": ""}}],
  "flowcharts": [{{"chapter": "c4", "after_section": 1, "title": "", "purpose": ""}}]}}
"""

SECTION = """Write the section "{section}" of the chapter "{chapter}" for the MDS library dissertation
"{title}" (Department of {department}).

What this section must cover: {brief}
The dissertation outline (for context, do not write other sections): {outline}
{visual_note}
Length: about {words} words (stay within 10% of this). {continuation}

Formatting:
- Plain paragraphs separated by one blank line.
- {subheading_rule}
- A short bulleted list is allowed only where items are genuinely parallel (lines starting with "- ").
- Do not write the section title itself. Do not add a references list.
- Bold a term with **double asterisks** only when it is defined.

Sources you may cite (cite by ID):
{sources}
"""

CONTINUE = """The section so far ends with:
\"\"\"{tail}\"\"\"
It already covers: {covered}
Continue the same section with NEW paragraphs only (about {words} more words). Do not repeat earlier points,
do not restate the section title, and keep the same citation rules."""

REVIEW = """Write review-of-literature entries for an MDS library dissertation on "{title}".
For each source below write one paragraph of {words_each} words describing what the study did (design,
sample, materials or methods) and what it found or concluded, based only on its abstract or excerpt.
Do not begin with the authors' names or the year (they are added automatically); begin with a verb phrase
such as "conducted a randomised clinical trial to ...", "reviewed ...", "evaluated ...".
Do not include citations or numbers that are not in the source.

Return JSON: {{"entries": [{{"sid": "S1", "text": ""}}]}}

Sources:
{sources}
"""

AIMS = """Write the Aims and Objectives chapter of an MDS library dissertation titled "{title}"
(Department of {department}).
Synopsis aim: {aim}
Synopsis objectives: {objectives}
Chapter outline of the dissertation: {outline}

If the synopsis gives an aim and objectives, keep their meaning and wording as close as possible, only
correcting grammar. If it does not, write one aim and 4-6 objectives that match the chapter outline.
Return JSON: {{"aim": "", "objectives": [""]}}"""

SUMMARY = """Write the "Summary and Conclusion" chapter (about {words} words) of the MDS library dissertation
"{title}". Base it ONLY on the chapter digests below; do not add new facts or citations.
Structure: {summary_structure}

Chapter digests:
{digests}
"""

DIGEST = """Summarise the key points of this dissertation chapter in 5-8 short bullet points (no citations):
\"\"\"{text}\"\"\""""

TABLE = """Create a table for the MDS library dissertation "{title}".
Table title (you may refine it): {vis_title}
Purpose: {purpose}
Base the content on the sources below and standard textbook knowledge consistent with them. Use 3-6
columns and 4-12 rows, with short phrases in the cells (no full paragraphs). List the IDs of the sources
that support the table in "source_sids" (at least one).

Return JSON: {{"title": "", "columns": [""], "rows": [[""]], "source_sids": ["S1"], "note": ""}}

Sources:
{sources}
"""

FLOWCHART = """Design a flowchart for the MDS library dissertation "{title}".
Flowchart title (you may refine it): {vis_title}
Purpose: {purpose}
Use 5-14 boxes. Each box text must be short (at most 9 words). Use kind "start" for the first box, "decision"
for yes/no questions, "end" for final outcomes and "process" for everything else. Edges may carry a short
label such as "Yes" or "No". Base it on the sources below; list the supporting IDs in "source_sids".

Return JSON: {{"title": "", "nodes": [{{"id": "n1", "text": "", "kind": "start"}}],
  "edges": [{{"from": "n1", "to": "n2", "label": ""}}], "source_sids": ["S1"]}}

Sources:
{sources}
"""


HEADINGS = """Below is text pasted or uploaded by the user. List every heading and sub-heading in it, copied
EXACTLY as written (same words, same spelling, same capitalisation). Do not add, rename, merge, shorten, split
or invent headings. Keep their order. Leave out the numbering prefix (such as "1.", "2.1", "I.", "a)") but keep
the words. Leave out "References", "Bibliography" and "Annexure"/"Appendix" headings. Ignore ordinary
sentences: a heading is a short title line.
level 1 = main heading (chapter); level 2 = sub-heading under the previous main heading.
If the text has no headings at all, return an empty list.

Return JSON: {{"headings": [{{"text": "", "level": 1}}]}}

Text:
<<<
{text}
>>>
"""

PLAN_FIXED = """These are the user's chapter and section headings for an MDS library dissertation (a dissertation
based entirely on published literature) titled "{title}" (Department of {department}). The headings are FIXED:
you must not change, add or remove any.

{outline}

Target length of the main text: about {pages} pages.

For each chapter (by its number) give:
- "weight": its relative share of the total length (introduction about 6, aims 1, conclusion/summary 3,
  discussion about 12, review of literature about 20, other topic chapters 8-15),
- "brief": one sentence on what the chapter should cover, consistent with its heading,
- "section_briefs": one short brief per listed section, in the same order (an empty list if it has none),
- "queries": 3-5 literature search queries in Europe PMC / PubMed syntax for that chapter, e.g.
  (gingival depigmentation) AND (laser OR scalpel); broad enough to return many papers (none for aims).
Also suggest up to {n_landmarks} classic papers you are confident exist (first author surname, year, title), and
{n_tables} tables and {n_figs} flowcharts, each placed in a chapter (by number) after a section index (0-based;
use 0 if the chapter has no sections).

Return JSON:
{{"chapters": [{{"number": 1, "weight": 0, "brief": "", "section_briefs": [""], "queries": [""]}}],
  "landmarks": [{{"first_author": "", "year": "", "title": ""}}],
  "tables": [{{"chapter": 1, "after_section": 0, "title": "", "purpose": ""}}],
  "flowcharts": [{{"chapter": 1, "after_section": 0, "title": "", "purpose": ""}}]}}
"""

IMAGE_QUERIES = """Suggest {n} short search phrases (2-4 words, English) to find good illustrative images on
Wikimedia Commons for an MDS library dissertation titled "{title}" (Department of {department}).
Prefer anatomy diagrams, radiographs, clinical or surgical photographs, instruments and classic illustrations
that match these chapters: {outline}
Return JSON: {{"queries": [""]}}"""

IMAGE_PICK = """You are choosing illustrations for the MDS library dissertation "{title}".
The candidate images are attached in the same order as this list (image 1 is the first attachment):
{candidates}

Chapters where an image may be placed (number, then 0-based section indexes):
{outline}

Choose the {n} best images: clearly relevant to the subject, academically appropriate, readable, not
duplicates, and spread across different chapters where possible. Reject logos, unrelated pictures, images
of identifiable patients' full faces, and low-quality pictures. If fewer than {n} are suitable, choose fewer.
For each, give a short factual figure caption (max 20 words) that describes what the image shows.

Return JSON: {{"picks": [{{"id": 1, "chapter": 1, "after_section": 0, "caption": ""}}]}}"""
