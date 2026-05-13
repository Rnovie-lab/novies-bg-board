# Shooting Schedule Parser — Coordination Doc

**Authors:** BG Board (this project) + Call Sheet Commander (separate Claude Code project)
**Last updated:** 2026-05-12
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
| Title-page noise | various | `Oracle BLUE SHOOTING SCHEDULE 2-5-26.pdf` page 1 | Some PDFs have near-empty title/cover pages. Parser must skip these, not crash. |

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
