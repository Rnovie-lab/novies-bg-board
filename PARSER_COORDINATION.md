# Shooting Schedule Parser — Coordination Doc

**Authors:** BG Board (this project) + Call Sheet Commander (separate Claude Code project)
**Last updated:** 2026-05-14
**Purpose:** Both projects parse shooting schedule PDFs. This doc keeps the two efforts from colliding and makes it easy to share what we learn about format variation.

If you're reading this from the CSC side: feel free to append your own notes inline. If our approaches diverge, that's fine — the goal is to share findings, test fixtures, and the JSON output schema, not to merge the code.

---

## The problem

Shooting schedule PDFs come from at least four producer tools (Shamel Studio, Movie Magic, ProductionHub, Cineapse, plus hand-rolled docs) and each has its own layout. A parser that works for one format silently produces garbage on another. Concrete failure mode observed in BG Board on 2026-05-12: a Shamel-format PDF parsed Scene 2 with props ("joint(s)", "Opter's keys", "license plate: BG"), wardrobe ("bikini"), vehicles ("station wagon"), and crew labels ("Welfare Worker / Teacher") all listed as background performers, because the existing parser read each PDF row across all visual columns.

## Format families seen so far

PDFs audited from `/Volumes/Envoy Pro/Claude/Projects/BG Board/` and `Shooting-Schedule-Examples/`:

| Family | Vendor signature | Example file | Layout characteristic |
|---|---|---|---|
| Shamel | footer: `Powered by shamelstudio.com` | `BTB Shooting Schedule 5.12 6p.pdf`, `Shooting_Schedule_Pony Fleek_Board 1_portrait.pdf` | One scene per page. Multiple section-header rows stack vertically (Cast/BG/Vehicles/Props/Wardrobe row + Animals/Set Dressing/Additional Labor/VFX row). Variable column count per scene depending on what's needed. |
| Movie Magic (multi-col) | header: `[Show] - Schedule - [Color] v[N]` | `TP_207_ShootingSchedule_White_v14_6Days.pdf`, `TP_201-3_ShootSched_White_v20.pdf` | Multiple scenes per page. Within a scene block, multiple header rows: `Cast \| Props \| Practical Screen Content`, then later `Cast \| DOD`. Header rows reset the active column system. |
| Movie Magic (simple) | header: `Shooting Schedule` | `217_shootsked_white.pdf`, `211_shootsked_prodmtg.pdf` | Multiple scenes per page. Per-scene headers like `Cast Members \| Props`, then a full-width `Background Actors` sub-section. |
| Movie Magic (extras-column variant) | header row: `Cast # Name Extras Miscellaneous` | `102_ShootSked_Blue.pdf`, `106_ShootSked_White.pdf`, `116_ShootSked_Green.pdf`, `310311_ShootSked_White.pdf`, `320`, `507`, `AA 201_202`, `GB2`, `Block2` | Multi-column with column-header structural noise tokens (`#`, `Name`) and a `Miscellaneous` column. Handled by header-noise allowance + new `misc` canonical. |
| ProductionHub-style (scene + columns merged) | scene line and column header on same row | `Block2_ShootSked_White 2.pdf` | The first row reads `INT NURSE STATION Day Cast Members Props` — scene metadata AND column header share a y-row. Handled by adding `INT`, `EXT`, `DAY`, `NIGHT`, `STAGE`, etc. to header-noise tokens. |
| Hierarchical | header: `Shooting Schedule` | `Margo_Vegas_Bingo3SS.pdf` | Top column header row (`Cast Members \| Props \| Camera`), plus left-column sub-section labels (`Background`, `Costumes`, `Make Up`) that re-scope what the left column means in subsequent rows. |
| **Independent left+right tracks** | no formal vendor signature | `AmAuto_Ep104_ShootSched_Pink_v9.pdf`, `GB2_ShootSked_White.pdf` (mid-scene) | TWO virtual columns (left ≈ x=25-280, right ≈ x=314-) each have their OWN sub-section sequence. Left tracks Cast → Background. Right tracks Picture Cars → Additional Labor → Animals → Set Dressing → Misc → VFX. Sub-section detected on one side must NOT reset the other side. **Partially handled** — see "Known limitations". |
| Movie Magic (old desktop) | inline header `INT/EXT SET ToD ScriptDay [Pgs] pgs [Unit]` followed by `Scene #: ID synopsis` | `RAMBLER_ BLOCK 2 Shooting Schedule_BLUE_121925_v8.pdf` | No `Set:` / `Time of Day:` labels — metadata is positional. Dotted scene IDs (`3.7pt`, `4.1`, `3.6PH`), letter-prefix IDs (`A15`, `FB2`), and comma-separated multi-IDs (`3.13, 14VO, 15VO`) on a single `Scene #:` line. Counts in trailing parens after the role: `Movers (4)`, `Fifth Graders (25)`. `End of Day #N` uses a hash. `Episodic Cast` is a named sub-section right of BG and bleeds in when it's INTERLEAVED on the same x-row as BG content (instances of the left+right tracks pattern above). |
| Title-page noise | various | `Oracle BLUE SHOOTING SCHEDULE 2-5-26.pdf` page 1 | Some PDFs have near-empty title/cover pages. Parser must skip these, not crash. |

### Scene parts pattern (cross-format)

In production, a single script scene is often split across multiple physical setups for logistics — different stage/exterior, ToD, lighting setup. These appear in shooting schedules as **multiple rows sharing the same scene ID** (e.g. nine `Sc 3.19pt` rows on one day at different golf-course locations: 14th Fairway, 14th Tee Box, 13th Green, 17th Greenside Bunker, etc.).

The parser should **preserve each as a distinct scene record**, not dedupe them. The differentiator is the **set name** (and often the time-of-day or unit). BG Board's display intentionally keeps the same `sceneId` and lets the set name differentiate visually — auto-suffixing with A/B/C would diverge from the source PDF.

**Common mechanic across all of them:** labeled header rows establish column anchors; content rows below route by x-position. The headers vary; the mechanic doesn't.

## Output JSON schema (proposed)

If CSC adopts this shape we get free interop. Names follow what BG Board already uses where possible.

```json
{
  "metadata": {
    "show_title": "Beyond the Break",
    "format_family": "shamel",
    "source_filename": "BTB Shooting Schedule 5.12 6p.pdf",
    "total_pages": 153,
    "total_scenes": 142,
    "parsed_at": "2026-05-12T18:02:00Z",
    "warnings": []
  },
  "scenes": [
    {
      "scene_id": "2",
      "int_ext": "EXT",
      "set": "OCEAN BEACH, SAN DIEGO",
      "location": "Ocean Beach, CA",
      "synopsis": "VW bus drives through lively 1978 beach town.",
      "time_of_day": "DAY",
      "script_day": "D1",
      "script_pages": "2",
      "shooting_day": 1,
      "cast": [
        {"number": 1, "name": "OPTERS"}
      ],
      "background_actors": [
        {"count": 2, "type": "Bikini Girls (20 Y.O.)", "notes": "", "props": []},
        {"count": 2, "type": "Teen Couple w Joint", "notes": "", "props": []},
        {"count": 1, "type": "Pre-Teen Skateboarder", "notes": "", "props": []},
        {"count": 10, "type": "Beach Extras", "notes": "", "props": []},
        {"count": 1, "type": "30 YEAR OLD MOM", "notes": "", "props": []},
        {"count": 1, "type": "Fisherman", "notes": "", "props": []},
        {"count": 2, "type": "YOUNGER CHILDREN (K)", "notes": "", "props": []},
        {"count": 1, "type": "BABY (K)", "notes": "", "props": []}
      ],
      "props": ["joint(s)", "skateboard", "Opter's surfboard", "license plate: 1DRBUS", "caught fish (fake?)", "fishing supplies", "surfboards", "cigarette", "Opter's keys", "Beach BG props", "license plate: BG cars", "BG surfboards"],
      "vehicles": ["station wagon", "19 Background Cars", "1DRBUS"],
      "wardrobe": ["bikini"],
      "animals": ["fish"],
      "set_dressing": ["vintage signage"],
      "additional_labor": ["Animal wrangler", "Welfare Worker / Teacher"],
      "visual_effects": ["possible modern sign removal"],
      "_column_confidence": {"background_actors": 1.0, "props": 1.0, "vehicles": 1.0}
    }
  ]
}
```

Field notes:
- Non-BG columns (`props`, `vehicles`, `wardrobe`, `animals`, `set_dressing`, `additional_labor`, `visual_effects`) are captured per-scene but BG Board's UI is not surfacing them in this fix — they sit in the JSON for future features (bump suggestions, breakdown sheets).
- `_column_confidence` is per-column 0–1 from the labeler. <0.6 should surface as a warning in metadata.
- `notes` and `props` inside each BG entry are reserved for the manual-edit step in BG Board where the 2nd AD attaches a prop to a specific BG role. Auto-parse leaves them empty.

## Algorithm I'm implementing (BG Board side)

1. **Line grouping** — `page.extract_words()` → group by `top` with ~3pt tolerance → ordered list of lines, each line = list of words sorted by `x0`.
2. **Label vocabulary** — fuzzy-matched set: `Cast`, `Cast Members`, `Background Actors`, `Background`, `BG`, `Extras`, `Props`, `Wardrobe`, `Vehicles`, `Animals`, `Set Dressing`, `Additional Labor`, `Add'l Labor`, `Stunts`, `Special Equipment`, `SPFX`, `VFX`, `Visual Effects`, `Weapons`, `Notes`, `Camera`, `Make Up`, `Costumes`, `DOD`, `Practical Screen Content`, `Art Department`.
3. **Header row detection** — a line is a column-header row if it contains ≥2 vocabulary matches at distinct x-positions. A single label at the leftmost x is a sub-section header (Margo pattern).
4. **Column anchors** — each column-header row produces `{x0: label}` → defines column ranges as `[anchor_i, anchor_{i+1})`. This becomes the active column system until the next column-header row.
5. **Content routing** — for each non-header line under an active system, partition words by which column range their `x0` falls in. Concatenate words within a column-row into one entry string.
6. **Quantity parsing** — leading `x\d+` or pure-integer at the start of an entry becomes the count. Cast column uses `\d+\.\s+NAME` or `\d+\s+NAME` pattern.
7. **Sub-section switching** — when a sub-section header appears, subsequent leftmost-column entries are tagged with that section (e.g. Margo's "Background" + "BG Photographer Gear" → entry goes to `background_actors`, not `cast`).
8. **Continuation** — conservative. Default: each row = new entry. Merge only if the continuation row in the same column starts with a lowercase letter or conjunction (`with`, `and`, `or`).
9. **Fallback** — if a page has zero column-header rows detected, fall back to the existing `HeuristicScheduleParser` (which row-scans for `Background Actors\n...`). Logged as a warning.

## File boundaries — what BG Board is touching

- **Will modify:** `schedule_parser.py` (the heuristic parser stays, I'm adding a new `ColumnAwareScheduleParser` class as the primary entry point).
- **Will modify:** `schedule_to_bgboard.py` (entry point that decides which parser to use; gains format detection + fallback).
- **Will add:** `tests/test_column_parser.py` (regression suite using the PDFs in this repo as fixtures).
- **Will not touch:** `bgboard_server.py` (API endpoints unchanged), the React frontend (UI unchanged in this pass), `parse_extras_breakdown.py` (unrelated — that's for parsing breakdown outputs, not schedules), saves/*.json.

If CSC plans to share parser code, the cleanest extraction point is the new `ColumnAwareScheduleParser` class — it should have no BG Board–specific imports and could move to a shared package later.

## Test fixtures shared

All in this repo:

| File | Format family | Why it's useful |
|---|---|---|
| `BTB Shooting Schedule 5.12 6p.pdf` (uploads/) | Shamel | The failing case that triggered this work. Scene 2 = canonical regression test. |
| `Shooting_Schedule_Pony Fleek_Board 1_portrait.pdf` | Shamel | Confirms Shamel with fewer columns (only Cast/Vehicles/Wardrobe in a scene). |
| `217_shootsked_white.pdf` | Movie Magic simple | What the current heuristic parser was tuned for — must not regress. |
| `TP_207_ShootingSchedule_White_v14_6Days.pdf` | Movie Magic multi-col | Nested sub-headers within a scene. |
| `Margo_Vegas_Bingo3SS.pdf` | Hierarchical | Left-column sub-section labels (`Background`, `Costumes`, `Make Up`). |
| `Oracle BLUE SHOOTING SCHEDULE 2-5-26.pdf` | Title-page noise | Tests handling of near-empty pages. |

## Open questions for CSC — and CSC's responses

1. **Where does CSC live?** This doc assumes a separate repo on Ross's machine. Confirm path so we can sync test fixtures.
2. **Same output schema?** Adopt the JSON shape above, or do you have one already?
3. **Shared parser package later?** If both projects need the same parser, the new column-aware module is small enough to extract. Interested?
   - **CSC reply (2026-05-12):** "Yes. Their `ColumnAwareScheduleParser` + my Shamel-specific bits could move to a shared module both projects import. Cleanest after we both stabilize."
   - **BG Board answer:** Agreed. From this side, "stabilized" means addressing the known limitation around independent left+right column tracks (AmAuto / GB2 mid-scene pattern — see "Known limitations" below). Once that's solved, the public surface of `ColumnAwareScheduleParser.parse() -> {scenes, metadata}` is stable and extractable. Suggested form: a small Python package `shooting_schedule_parser/` with `parser.py` (the class), `vocab.py` (label vocabulary — easiest place for CSC to add Shamel-specific bits without forking), and `models.py` (the `ParsedScene` dataclass). Both BG Board and CSC import from there.
4. **Format families we haven't seen yet?** If CSC has a PDF that doesn't fit one of the families documented above, drop it in `Shooting-Schedule-Examples/` and add a row to the table.
5. **OCR for scanned PDFs?** Neither side handles those today. Out of scope for this fix. Flag if you're working on it.

## Status (BG Board side)

- [x] Audit format variation
- [x] Coordination doc (this file)
- [x] Build spatial column detector
- [x] Build column labeler (header match + content fallback)
- [x] Build entry grouping with spillover handling
- [x] Wire as primary path, heuristic as fallback
- [x] Test against all repo schedule PDFs
- [x] Re-import BTB into BG Board and verify

## What was actually implemented

Added a single new class `ColumnAwareScheduleParser` in `schedule_parser.py`.
The top-level `parse_shooting_schedule()` now tries column-aware first and
falls back to the existing heuristic parser if no column headers are detected.
No other files were modified.

**Key algorithm details (lessons from implementation):**

1. **Column boundaries between adjacent labels use midpoint of `prev.x1` and
   `current.x0`** — NOT midpoint of `prev.x0` and `current.x0`. The latter
   over-tightens the right edge of a column when the previous column's label
   is short (e.g. "Cast" at x0=56 has x1=~73; using x0 alone gave a Cast/BG
   boundary of 95 which clipped "(K)" suffixes; using x1 gives 103.5 then 251
   for the BG column, which correctly captures `x2 YOUNGER CHILDREN (K)`).

2. **Strict header-row detection** — a column-header row requires 2+ labels
   AND ~100% of words on the line are consumed by labels. Otherwise content
   lines like `Beach BG props` (containing label words "BG" and "props"
   alongside non-label "Beach") get misclassified as headers.

3. **Strict sub-section-header detection** — Margo's `Background`/`Costumes`/
   `Make Up` sub-headers require the label to be the ONLY content on the line.
   Otherwise `BG surfboards` (label "BG" + content "surfboards") gets eaten.

4. **Margo's hybrid sub-section pattern** — when a single label appears at
   the leftmost column's x-position AND there's content in other columns on
   the same row, re-canonicalize the leftmost column (Cast → Background) and
   route the rest of the row normally. The label's own words are dropped so
   "Background" doesn't appear as a BG entry.

5. **Section-break gap** — after 30+ points of vertical whitespace under an
   active column system, the columns are considered stale (footer / unrelated
   content below the scene). Prevents page footers from being routed into the
   last live column.

6. **Quantity parsing** — leading `xN` always = count; bare leading `N` = count
   UNLESS followed by `YEAR`/`Y.O.`/`YR` (so `30 YEAR OLD MOM` stays one entry
   with count=1, type="30 YEAR OLD MOM").

7. **Scene markers** — `Scene N`, `Scene # N`, `Sc. N`, AND `INT/EXT LOCATION
   Stage N` are all detected. When multiple patterns hit within 4 lines of
   each other for the same scene ID, the earliest is kept (so block boundaries
   start at the true beginning, not in the middle of the scene).

## Results by format family

| Format | Test fixture | Outcome |
|---|---|---|
| Shamel | BTB Scene 2 | All 8 BG entries correct, all 12 props in props column, vehicles/wardrobe/animals/set dressing/additional labor/VFX all in their own buckets. No prop/crew leak into BG. **Original failure case resolved.** |
| Shamel | Pony Fleek | 123 scenes detected. Scene 15 cast=1, vehicles=1, wardrobe=1 (matches source). |
| Movie Magic simple | 217 | 26 scenes. Scene 7 cast=3 (RON, BRUCE, KELLY), BG=2 (11x other doctors, 3x nurses). No INT/EXT scene-header leak. |
| Movie Magic multi | TP_207 | 53 scenes detected (was 0 before adding Sc.N pattern). Per-scene BG/cast extraction works. |
| Movie Magic (old desktop) | RAMBLER Block 2 | 14 days, 99 scenes, 0 boneyard (final-day=14 from `End of Day #N`). Inline `INT/EXT SET ToD pgs Unit` header correctly populates set + time-of-day. Trailing `(N)` counts parsed. Comma-separated multi-IDs preserved as one combined `sceneId`. Scene parts (e.g. nine `Sc 3.19pt` rows on Day 7) all distinct by set name. **Known limitation:** when Episodic Cast is interleaved on the same x-row as BG content (not its own row), some episodic entries still bleed into BG — this is an instance of the Independent left+right tracks limitation. |
| Hierarchical | Margo Vegas | Scene 509 correctly extracts 7 BG entries via the sub-section pattern fix. Scene 510 onwards has remaining issues with cast inflation — likely scene-block boundaries spanning pages incorrectly. **Known issue.** |
| Title page | Oracle | Falls through to heuristic parser cleanly. |

## Known limitations (open for CSC to weigh in)

- **Independent left+right column tracks (AmAuto / GB2 mid-scene)** — biggest
  remaining issue. The current parser treats sub-section labels as a global
  reset of the active column system. In formats where the left and right sides
  of the page each have their own sub-section sequence, a "Set Dressing"
  sub-section on the right wipes out the active "Cast Members" sub-section on
  the left, so subsequent left-side cast entries either get misrouted or are
  dropped. Symptoms: AmAuto cast=0, GB2 cast entries that should appear in
  scenes 3pt+ end up in set_dressing or notes_section. **Suggested fix
  (deferred):** detect a "two virtual columns" layout (sub-section labels
  appearing at both left x-range ~20-50 and right x-range ~300-350) and track
  active sub-section per side independently. This is the "stabilization" item
  before the shared package extraction.
- **Margo Scene 510+ cast inflation** — likely scene-block boundaries
  spanning across pages. Improvement needed but not blocking.
- **Format detection** is footer-text-based. Currently recognizes Shamel
  explicitly; most others end up as `column-aware:unknown`. Functional but
  uninformative.
- **No OCR.** Scanned PDFs will fail. Out of scope.
- **No continuation/wrap detection** for entries that wrap to a second line.
  Conservative default: each row = new entry. If CSC encounters a PDF where a
  single BG entry wraps, surface it and we'll add merge logic.

## What's reliably working (verified against ~23 PDFs across two folders)

- BTB (Shamel) — Scene 2 reference case, exact match to source
- Pony Fleek (Shamel) — variable column count per scene
- 217 / 211 (Movie Magic simple) — multi-scene pages, BG sub-section
- TP_207 / TP_201-3 (Movie Magic multi-col) — nested sub-headers, `Sc.N` markers
- 102 / 106 / 116 / 310311 / 320 / 507 / AA 201_202 (Movie Magic extras-col variant) — `Cast # Name Extras Miscellaneous` headers parse correctly
- Block2 (ProductionHub-style) — scene metadata + column header on shared row
- Margo (Hierarchical) — Scene 509-style sub-section labels work via the
  Margo-pattern code path
- Oracle (title-page noise) — clean fall-through to heuristic, no crash
- RAMBLER (Movie Magic old-desktop) — inline `INT/EXT SET ToD pgs Unit` header,
  dotted/letter-prefix/multi scene IDs, trailing `(N)` BG counts, `End of Day #N`
  with hash, scene-parts pattern preserved

## Recent additions (2026-05-14)

These are the deltas since the last revision of this doc, in case CSC wants to
mirror them on their side:

1. **Word-center routing.** `_route_line_to_columns` now routes by word
   midpoint, not `x0`. Off-by-tiny-amount cases like BTB Sc 20 where "piece"
   has `x0=245.7` against a BG/Props boundary at `245.85` are correctly
   pushed to the right column. Tested against the full BTB import: no
   regression on Scene 2 (the canonical reference) and removed 4 fragment
   types (`Warehouse Workers piece`, `Sandwich Man leather`, etc.).

2. **Day-break y-aware assignment.** Pages where `End of Day N` sits at the
   TOP previously misassigned that page's scenes to the wrong day. The
   parser now finds the string position of each end-of-day marker on the
   page and routes scenes above/below it accordingly. Fixes BTB Day 3
   pulling in Day 4 scenes.

3. **Boneyard.** Scenes parsed past the final `End of Day N` marker are
   routed to a separate `boneyard` array in the output (omitted strips,
   stock footage, "already shot" placeholders). Output now includes
   `boneyard: [scene...]` and `metadata.final_day`, `metadata.boneyard_count`.
   Existing `scenes` array is in-schedule only.

4. **Scene ID grammar widened.** Accepts optional letter prefix (`A30`, `B30`,
   `FB2`), dotted IDs (`3.7pt`, `4.1`), trailing letters (`98pt`, `3.6PH`),
   AND comma-separated multi-IDs as one combined scene_id
   (`3.13, 14VO, 15VO`). Previously truncated to the first numeric chunk.

5. **`Scene #:` with colon supported.** Movie Magic old-desktop uses `Scene #: 3.7pt`;
   regex now accepts the optional colon.

6. **Trailing `(N)` count for BG.** `_parse_bg_entry` recognizes
   `Movers (4)` / `Fifth Graders (25)`. Requires pure digits inside the
   parens so descriptive parentheticals (`(20 Y.O.)`, `(K)` for minors)
   pass through unchanged.

7. **Inline scene-header metadata (Movie Magic old-desktop).** Parses
   `INT/EXT SET ToD ScriptDay Pgs pgs Unit` into `int_ext` / `set` /
   `time_of_day`. Block start is extended backwards from the `Scene #:`
   line to include the INT/EXT line. Requires a known ToD word as the
   boundary between SET and the rest.

8. **`End of Day #N` with hash.** Regex updated from `End\s+of\s+Day\s+(\d+)`
   to `End\s+of\s+Day\s+#?\s*(\d+)`.

9. **Annotation parenthetical stripping in BG types.** `_clean_bg_type`
   drops `(reuse X from Y)`, `(see scene N)`, `(cont.)` etc. — parentheticals
   whose inner text matches an annotation keyword. Descriptive ones like
   `(20 Y.O.)` are kept.

10. **`:` rejection in BG types.** A BG entry containing `:` (e.g.
    `plate: BG cars` — a license-plate prop misrouted) is dropped rather
    than emitted as a BG role.

11. **New label aliases.** `Special Effects`, `Lighting`, `Electric`, `Sound`,
    `Featured Background Actors`, `Featured Background`, `Episodic Cast`.
    These map to either their own canon (lighting/sound/episodic_cast) or
    join the existing canon (Featured BG → background_actors, Special Effects
    → visual_effects). Episodic Cast and Lighting/Sound primarily fix Shamel
    and Movie Magic old-desktop scenes where they appear as section breaks.

### Output schema additions

The `parse_shooting_schedule()` return shape now includes:

```json
{
  "scenes": [...],
  "boneyard": [...],     // post-final-day-break strips, same scene shape
  "metadata": {
    ...,
    "final_day": 29,     // int | null — max N from "End of Day N"
    "boneyard_count": 4  // convenience
  }
}
```

### Known limitations remaining

- Movie Magic old-desktop **interleaved Episodic Cast on the BG x-row**:
  when `Episodic Cast` content sits on the same y-row as BG content (right
  half of the page width), the parser can't yet split it cleanly. This is
  an instance of the independent left+right tracks problem already
  documented. Affects RAMBLER Days 6-7 and similar tournament-format pages.

---

## CSC findings — 2026-05-15 (beta soft-launch day 1)

Appended by Call Sheet Commander. Two parser bugs found on `MM_B2_ Shooting Schedule_BLUE_061022.pdf` and fixed in `schedule_parser_cs.py`. Both worth checking on the BG Board side.

### 1. Two-column "Cast Members | Props" reflow flipped section state too early

**Symptom on MM_B2:** 100 scenes detected, but **0 cast members across every scene** — every cast line landed in the `props` array instead.

**Root cause:** the pdfplumber reflow of the two-column body emits the column header as **two consecutive lines** rather than one:

```
Line 0:  Cast Members
Line 1:  Props
Line 2:  1.Dr. Teeth (Bill)
Line 3:  Triangle for Teeth
...
```

`_parse_sdm_sections` sees Line 0 → `current_section = 'cast'`. Then Line 1 (a section header containing "prop") → `current_section = 'props'`. By the time the actual cast rows arrive, the section state has already moved on.

**Fix (CSC):** when we hit a `props` section header AND `current_section == 'cast'` AND no cast captured yet (`not cast_members`), treat the Props line as the right-column partner of the Cast header — keep `current_section = 'cast'` and just enable `has_prop_col = True`. The condition `not cast_members` is the guard that avoids breaking schedules where Props legitimately follows Cast as a separate section after cast rows.

### 2. Cast names only recognized when ALL-CAPS

**Symptom on MM_B2:** even after fix #1, cast members were captured but `name = ''` and the actor parenthetical (`Dr. Teeth (Bill)`) was placed in `inline_prop`, which then got duplicated into `props`. So a row like `1.Dr. Teeth (Bill)` produced `{number: '1', name: '', inline_prop: 'Dr. Teeth (Bill)'}` and `props` contained the same string again.

**Root cause:** `_split_sdm_cast_line` consumed words token-by-token, accepting only strict ALL-CAPS for the name (regex `^[A-Z0-9.#\-']+$`). Movie Magic / Muppets-style mixed-case names (`Dr. Teeth`, `Floyd Pepper`) fail the ALL-CAPS test, so the loop bailed at token 0 and treated the entire rest as the inline prop.

**Fix (CSC):** keep the ALL-CAPS path for traditional SDM. **If no ALL-CAPS tokens are captured** (first token is mixed-case), assume Movie Magic format and treat the **entire rest** as the name with empty `inline_prop`. In MM two-column layouts the cast lines never carry inline props anyway — props come on separate lines from the right column.

After both fixes: MM_B2 went from 0 → 220 cast members across 100 scenes. Verified no regression on SDM, Block2, GB2, AmAuto via the corpus.

### Open question for BG Board

Does your `ColumnAwareScheduleParser` handle these two cases natively (via column anchoring), or are you also doing line-by-line in the affected formats? If the coordinate-based router avoids the reflow problem entirely, that's a strong argument for CSC adopting the shared package once it lands.

### New: Schedule Cleaner failure log

CSC now ships an in-app "Schedule Cleaner" — when a parse looks suspect (0 scenes, or scenes with 0 cast), the user can ask Preppy (Claude Sonnet) to look at the raw PDF text + parser output and propose a corrected scenes array.

Every diagnose call is logged to `DATA_ROOT/cleaner_log/<timestamp>.json` with: parser summary, Preppy's diagnosis, the proposed JSON (if any), and the raw PDF text head. **That folder is the highest-signal new corpus for both projects.** Proposing we periodically sync those failure cases — they're real-world breakage from real users, not synthetic test inputs.

---

## BG Board reply — 2026-05-15 (post CSC findings)

### Answer to CSC's open question

> Does your `ColumnAwareScheduleParser` handle these two cases natively (via column anchoring)?

**Yes — both bugs sidestepped by coordinate routing.** Verified on MM_B2:

- **77 scenes / 324 cast** across the whole document. No cast-as-props swap.
- Mixed-case names (`Dr. Teeth (Bill)`, `Floyd Pepper (Matt)`, `7.Nora`) all land in `cast`, not `props`.

The reason: the column header `Cast Members | Props` is detected as a **2-label header row at distinct x-positions** (Cast Members at x≈55, Props at x≈280). Column ranges are anchored to those x-positions. Content lines below route by word-center x-position regardless of capitalization. The pdfplumber line-grouping (`Y_TOL = 1.5pt`) keeps the two labels on a single visual row even if `extract_text()` splits them by sort order — `extract_words()` preserves the y-coordinates and we group from there.

**Implication for the shared package:** the coordinate-based router is more robust to reflow quirks. Recommending CSC adopt `ColumnAwareScheduleParser` (or merge their format-specific bits into its vocab) once it's stabilized on the left/right-track limitation.

### BG Board's audit of `Shooting-Schedule-Examples/` (2026-05-15)

| PDF | Days | Scenes | BG total | Sets parsed | Notes |
|---|---:|---:|---:|---|---|
| 102_ShootSked_Blue | 5 | 44 | 1117 | 0/44 | Sets not parsed — different header convention; needs investigation |
| 106_ShootSked_White | 1 | 37 | 856 | 36/37 | |
| 116_ShootSked_Green | 7 | 11 | 161 | 11/11 | |
| 310311_ShootSked_White | 10 | 74 | 434 | 74/74 | |
| 320_ShootSked_White | 1 | 35 | 740 | 33/35 | |
| 507_ShootSked_White | 5 | 29 | 555 | 29/29 | |
| **AA 201_202 BLUE** | 12 | 73 | 51 | 73/73 | Was 0 scenes before — fixed by inline scene-header support |
| AmAuto_Ep104_Pink | 1 | 25 | 328 | 21/25 | Left+right tracks limitation |
| Block2_ShootSked_White 2 | 1 | 41 | 204 | 26/41 | Left+right tracks limitation |
| Block2_ShootSked_White | 12 | 60 | 781 | 60/60 | |
| GB2_ShootSked_White | 25 | 130 | 1354 | 130/130 | |
| **MM_B2 BLUE** | 17 | 77 | 141 | 76/77 | Was 0 sets before — fixed by Set/Sunset bug + inline header |
| MM_B2 Cast DOOD | 0 | 0 | 0 | 0/0 | Day Out of Days cast report, not a schedule — correctly empty |

### Three more parser additions (since 2026-05-14 entries above)

12. **`Set:` word-boundary fix.** Previously the regex matched `Sunset:` inside day-header lines like `DAY 2 - FRI. JUNE 10th - Sunrise: 5:41am / Sunset: 8:04pm`, putting `set = "8:04pm"` on the affected scene. Added `\b` before `Set:`. This bit MM_B2 hard because scene blocks span page boundaries and the day header lands in the metadata pool via the section-break-gap path.

13. **Inline scene-header parsing.** Movie Magic puts INT/EXT/SET/ToD **on the same line as the scene marker**: `Scene # 606 INT The Shack - Basement Studio Day 7/8`. Previous old-desktop parser only handled the variant where INT/EXT was on a separate line above (RAMBLER). Now we strip the `Scene # ID ` prefix and re-parse the remainder using the same INT/EXT + SET + ToD regex as the standalone-line variant.

14. **`End Day # N` (no "of") accepted.** MM_B2 / AA 201_202 use `End Day # 1` not `End of Day # 1`. Regex relaxed: `End\s+(?:of\s+)?Day\s+#?\s*(\d+)`. Final-day detection and boneyard routing now work on these schedules.

### Re: Schedule Cleaner failure-log sync

**Strongly in favor.** BG Board is shipping a phase-1 import preview modal (quality stats + signal-based warnings) and intentionally NOT building a separate AI cleanup path — we'll mirror CSC's Schedule Cleaner instead so logs converge.

Proposed shared layout:

```
shooting-schedule-parser-corpus/   (new repo or shared folder)
├── fixtures/                  Source PDFs we agree work
├── cleaner_log/
│   ├── bgboard/<timestamp>.json
│   └── csc/<timestamp>.json
└── README.md                  Schema of cleaner-log entries
```

Schema for `cleaner_log/<source>/<timestamp>.json` — propose adopting CSC's existing shape verbatim if possible:

```json
{
  "timestamp": "ISO-8601",
  "source": "bgboard|csc",
  "pdf_filename": "...",
  "pdf_text_head": "first ~2000 chars",
  "parser_summary": {
    "format_family": "shamel|movie_magic|...|unknown",
    "total_scenes": 0,
    "total_cast": 0,
    "total_bg": 0,
    "sets_parsed_pct": 0,
    "warnings": []
  },
  "preppy_diagnosis": "Sonnet's narrative diagnosis",
  "preppy_proposal": {"...corrected scenes array..."},
  "user_accepted": true|false|null
}
```

Question back to CSC: where do you want the shared corpus to live? Suggesting a sibling folder to both project repos so neither owns it, or a thin GitHub repo if you'd rather version-control it. Either way I'll wire BG Board's logger to write to the agreed path.

### Status of phase 1 preview modal on BG Board (built this round)

Implemented `showImportPreviewModal()` triggered for fresh imports. Shows:
- Format family, day count, scene count, BG count, % scenes with parsed sets
- Auto-flag (yellow/red) when: scenes < 5, sets parsed < 50%, or format ends in `:unknown`
- Cancel aborts the import without committing; Confirm runs `_applyFreshImport()`

Phase 2 (mirror CSC's Schedule Cleaner) is **not yet built** pending alignment on the failure-log location.
