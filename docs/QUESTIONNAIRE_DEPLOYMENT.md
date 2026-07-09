# Questionnaire Deployment Spec — replacing placeholders with real items

_How to load the real questionnaire content into the platform configs, correctly and
copyright-safely. The repo is PUBLIC, so copyrighted item text must live in gitignored
local files, never in the tracked config._

---

## 0. Read this first — three rules

1. **Verbatim or nothing.** These are validated instruments. A single altered word
   invalidates the scoring. Extract item text **exactly** from the source documents; do not
   paraphrase, re-order, or "clean up" wording.
2. **Public repo → copyrighted text goes in gitignored local files.** Demographics is the
   study's own instrument (safe to commit). BFI-2-S, RoSAS, and ERQ are copyrighted:
   their item text must be loaded from local files that are **gitignored**, with only
   structure/IDs/scoring in the tracked config. (BFI-2-S grants "personal and research use,"
   which does not clearly cover public redistribution — so keep it local too.)
3. **Version strings are exact and must not be normalized.** Use the registry values as-is.
   In particular, `dqel` and `manipulation_checks` keep their placeholder version strings
   (`0.1.0-placeholder`) — do NOT bump them to `1.0.0`.

---

## 1. Source documents (place these where Claude Code can read them on the server)

| Questionnaire | Source document | Status |
| --- | --- | --- |
| demographics | demographic_questionnaire_social_hri_download | uploaded — own instrument |
| bfi2s | BFI-2-S_questionnaire_download | uploaded — copyrighted, research-use permission |
| rosas_trainer | RoSAS_post_questionnaire_download | uploaded — copyrighted |
| rosas_child | (same RoSAS items, asked about the child robot) | uploaded — copyrighted |
| erq | english_0 (Gross & John ERQ) | uploaded — copyrighted; item order is load-bearing |
| dqel | — | keep placeholder (`0.1.0-placeholder`) |
| manipulation_checks | — | keep placeholder (`0.1.0-placeholder`) |

All four instrument sources (demographics, bfi2s, rosas, erq) are now available. `dqel` and
`manipulation_checks` remain intentional placeholders.

---

## 2. Registry / version strings (use exactly)

- `demographics` → `1.0.0`
- `bfi2s` → `1.0.0`
- `rosas_trainer` → `1.0.0`
- `rosas_child` → `1.0.0`
- `erq` → `1.0.0` (deploy only when source provided)
- `dqel` → `0.1.0-placeholder` (unchanged)
- `manipulation_checks` → `0.1.0-placeholder` (unchanged)

---

## 3. Copyright handling (gitignore-local pattern)

- **Tracked config** (safe to commit): questionnaire key, version, item **IDs**, response
  scale, subscale/dimension mapping, scoring key, reverse-scored flags — i.e. everything
  EXCEPT the copyrighted item wording.
- **Gitignored local file** (never committed): the verbatim item **text** for bfi2s,
  rosas_trainer, rosas_child, erq. The loader reads item text from the local file at runtime
  and joins it to the tracked structure by item ID.
- **Demographics** is the study's own instrument → its full content may live in the tracked
  config.
- Confirm the local item-text files are covered by `.gitignore` and run
  `git ls-files | grep -i questionnaire` to prove no copyrighted text is tracked before any
  commit/push.

---

## 4. DEMOGRAPHICS — own instrument, full content (safe to commit)

15 items, mixed response types. Skippable ("prefer not to answer" where shown).

A. Basic
1. Age — number (years)
2. Gender identity (check all) — Woman / Man / Non-binary / Prefer to self-describe (text) / Prefer not to answer
3. Race/ethnicity (check all) — American Indian or Alaska Native / Asian / Black or African American / Hispanic, Latino, or Spanish origin / Middle Eastern or North African / Native Hawaiian or Other Pacific Islander / White / Another identity (text) / Prefer not to answer
4. Country of birth — text
5. Primary language(s) spoken — text
6. Fluent in English? — Yes / No

B. Education & role
7. Highest education completed — High school/GED / Some college / Associate / Bachelor's / Master's / Doctoral or professional / Prefer not to answer
8. Current employment status — Employed full-time / Employed part-time / Student / Unemployed / Retired / Prefer not to answer
9. Current primary role or occupation — text

C. Experience
10. Work/volunteer in training, teaching, caregiving, counseling, customer service, or service-oriented interaction? — Yes / No
11. If yes, role(s) (check all) — Caregiver / Parent-family support / Teacher or educator / Counselor or therapist / Customer service / Healthcare or patient support / Social services / Other (text)
12. Years of experience — <1 / 1–3 / 4–6 / 7–10 / >10

D. Robots/agents
13. Ever interacted with a social robot before? — Yes / No
14. Ever interacted with a virtual avatar/conversational agent (research/training/assistance)? — Yes / No
15. Familiarity with social robots or virtual agents — None / Low / Moderate / High / Very high

---

## 5. BFI-2-S — structure (item TEXT from source → local file)

- 30 items, response scale **1–5**: 1 Disagree strongly, 2 Disagree a little, 3 Neutral,
  4 Agree a little, 5 Agree strongly.
- Instruction (from source): participants indicate agreement with each characteristic.
- Item IDs: `bfi2s_1` … `bfi2s_30`, in the source document's order.
- **Item text:** extract verbatim from the source document into the gitignored local file.
- **Scoring key (domains/facets + reverse-scored items):** take from the authoritative
  source — Soto & John (2017), *J. Research in Personality*, 68, 69–81 — and record it in
  the tracked config. Do NOT guess the reverse-scored set; verify against the paper.

---

## 6. RoSAS — structure (TWO configs: trainer + child)

- 18 items, response scale **1–7**: 1 Not at all associated … 7 Completely associated.
- Dimensions (scoring structure): **Warmth** (6), **Competence** (6), **Discomfort** (6).
- Two deployments, SAME items, DIFFERENT target agent:
  - `rosas_trainer` — asked about the **trainer robot**
  - `rosas_child` — asked about the **child robot**
  - Adjust only the instruction/target wording ("the embodied agent you just interacted
    with" → the specific agent); the 18 item words are identical.
- Item IDs: `rosas_1` … `rosas_18`, tagged with their dimension in the tracked config.
- **Item text (the 18 words):** extract verbatim from the source document into the
  gitignored local file.

---

## 7. ERQ — structure (item TEXT from source → local file)

- Source: Gross & John (2003), *J. Personality and Social Psychology*, 85, 348–362.
  Copyrighted → item text in the gitignored local file.
- 10 items, response scale **1–7**: 1 strongly disagree … 4 neutral … 7 strongly agree.
- **Scoring (NO reversals):** Reappraisal = items 1, 3, 5, 7, 8, 10; Suppression = items
  2, 4, 6, 9. (Confirmed from the source document.)
- Item IDs: `erq_1` … `erq_10`.
- **ITEM ORDER IS LOAD-BEARING — do not reorder.** The source states items 1 and 3 define
  the terms "positive emotion" and "negative emotion" used by later items, so the original
  order must be preserved exactly. Record this constraint in the config/data dictionary.
- **Item text:** extract verbatim from the source document into the gitignored local file.
- Instruction (from source): questions about how the participant controls/regulates/manages
  emotions; extract the full instruction verbatim.

---

## 8. Acceptance checks after deployment

- [ ] Each deployed questionnaire renders on the tablet with the correct items, order, and
      response scale.
- [ ] Version strings match the registry exactly; `dqel`/`manipulation_checks` still show
      `0.1.0-placeholder`.
- [ ] `git ls-files | grep -i questionnaire` shows NO copyrighted item text tracked; the
      local item-text files are gitignored.
- [ ] A submitted response saves and scores correctly (subscales compute from the scoring
      keys).
- [ ] `rosas_trainer` and `rosas_child` both exist, share the 18 items, differ only in the
      target agent wording.
- [ ] `erq` deployed with items in the ORIGINAL order (items 1 and 3 must precede the
      items that depend on their definitions); order constraint noted in the data dictionary.
