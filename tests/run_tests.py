#!/usr/bin/env python3
"""
tests/run_tests.py — BGBoard schedule parser regression test suite
==================================================================

Run from the BG Board directory:
    python3 tests/run_tests.py

Each fixture defines:
  pdf         — relative path to the PDF (relative to BG Board dir)
  days        — expected number of shooting days (exact)
  min_roles   — minimum total BG role entries (lower bound, not exact)
  max_roles   — maximum total BG role entries (upper bound sanity check)
  checks      — optional spot-checks: day N has at least M scenes / roles
  layout      — expected layout: 'sequential' or 'columnar' (optional)

To add a new PDF to the test suite:
  1. Run parse_shootsked.py on it and record the output
  2. Add a fixture entry below with those numbers
  3. The test suite will catch regressions immediately

Update a fixture by changing the expected numbers after a deliberate improvement.
"""

import sys
import json
import os
import time
from pathlib import Path

# Add parent directory to path so we can import parse_shootsked
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber not installed. Run: pip install pdfplumber")
    sys.exit(1)

from parse_shootsked import parse_shootsked, detect_column_layout

# ─── TEST FIXTURES ──────────────────────────────────────────────────────────
#
# Each entry is the ground truth for one PDF. These were established by
# running the parser against known-good output and verifying manually.
#
# IMPORTANT: When you improve the parser and intentionally get MORE correct
# results, update the fixture rather than loosening the bounds. The point is
# to lock in progress, not to have ever-wider tolerances.

FIXTURES = [
    {
        'pdf': '217_shootsked_white.pdf',
        'desc': 'SDM 217 — Movie Magic standard',
        'layout': 'sequential',
        'days': 6,
        'min_roles': 15,
        'max_roles': 60,
        'checks': [
            {'day': 1, 'min_scenes': 3},
        ]
    },
    {
        'pdf': '211_shootsked_white.pdf',
        'desc': 'SDM 211 — Movie Magic standard',
        'layout': 'sequential',
        'days_min': 4,
        'days_max': 12,
        'min_roles': 5,
        'max_roles': 120,
    },
    {
        'pdf': 'TP_201-3_ShootSched_White_v20.pdf',
        'desc': 'TP 201-203 — Movie Magic multi-episode (D{N} day headers)',
        'layout': 'sequential',
        'days': 13,
        'min_roles': 140,
        'max_roles': 200,
    },
    {
        'pdf': 'TP_207_ShootingSchedule_White_v14_6Days.pdf',
        'desc': 'TP 207 — EP Scheduling / The Paper (columnar, END OF DAY)',
        'layout': 'columnar',
        'days_min': 6,
        'days_max': 8,
        'min_roles': 10,
        'max_roles': 30,
        'checks': [
            # Scene 27pt (Softees) should be in Day 2, not Day 1
            {'day': 2, 'scene_id': '27pt', 'has_roles': True},
        ]
    },
    {
        'pdf': 'Block 5- White Shooting Schedule.pdf',
        'desc': 'Block 5 — EP Scheduling 1-Line (day_end-only, columnar)',
        # EP 1-Line format: no day_start markers, only END OF DAY / End of DAY N
        'layout': 'columnar',
        'days_min': 3,
        'days_max': 20,
        'min_roles': 0,
        'max_roles': 200,
    },
    {
        'pdf': 'FINAL TOUCH PRELIM WHITE SHOOTING SCHEDULE 4-20-26.pdf',
        'desc': 'Final Touch — scanned PDF (OCR path)',
        # Image-based PDF: requires OCR; BG roles sparse because OCR quality
        'days_min': 1,
        'days_max': 40,
        'min_roles': 0,
        'max_roles': 300,
    },
    {
        'pdf': '211_shootsked_prodmtg.pdf',
        'desc': 'SDM 211 prod-mtg — Movie Magic (production meeting version)',
        'layout': 'sequential',
        'days_min': 4,
        'days_max': 7,
        'min_roles': 40,
        'max_roles': 80,
    },
    {
        'pdf': 'BV B5 SS_WHITE.pdf',
        'desc': 'BV Block 5 — Movie Magic multi-episode (photo-unit tail scenes)',
        'layout': 'sequential',
        'days_min': 10,
        'days_max': 16,
        'min_roles': 35,
        'max_roles': 70,
    },
    {
        'pdf': 'Margo_Vegas_Bingo3SS.pdf',
        'desc': 'Margo Vegas Bingo 3 — Movie Magic',
        'layout': 'sequential',
        'days_min': 2,
        'days_max': 5,
        'min_roles': 10,
        'max_roles': 35,
    },
    {
        'pdf': 'Shooting_Schedule_Pony Fleek_Board 1_portrait.pdf',
        'desc': 'Pony Fleek — Shamelab portrait format (compound Cast+BG headers)',
        'layout': 'sequential',
        'days_min': 15,
        'days_max': 22,
        'min_roles': 30,
        'max_roles': 60,
    },
    {
        'pdf': 'White shooting schedule B3.pdf',
        'desc': 'White B3 — Movie Magic (photo-unit tail scenes)',
        'layout': 'sequential',
        'days_min': 18,
        'days_max': 24,
        'min_roles': 25,
        'max_roles': 60,
    },
]


# ─── TEST RUNNER ─────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.parent


def run_fixture(fixture):
    """Run one fixture. Returns (passed, details_str)."""
    pdf_path = BASE_DIR / fixture['pdf']
    if not pdf_path.exists():
        return ('SKIP', f"PDF not found: {fixture['pdf']}")

    errors = []
    notes  = []

    try:
        t0 = time.time()
        result = parse_shootsked(str(pdf_path))
        elapsed = time.time() - t0
    except Exception as e:
        return ('FAIL', f"Exception: {e}")

    days       = result.get('days', [])
    total_days = len(days)
    total_roles = sum(len(s['roles']) for d in days for s in d['scenes'])
    total_scenes = sum(len(d['scenes']) for d in days)

    # Day count checks
    if 'days' in fixture:
        expected = fixture['days']
        if abs(total_days - expected) > 1:   # allow ±1 for stray tail days
            errors.append(f"days={total_days} (expected {expected})")
        else:
            notes.append(f"days={total_days} ✓")

    if 'days_min' in fixture and total_days < fixture['days_min']:
        errors.append(f"days={total_days} < min {fixture['days_min']}")
    if 'days_max' in fixture and total_days > fixture['days_max']:
        errors.append(f"days={total_days} > max {fixture['days_max']}")

    # Role count bounds
    if total_roles < fixture.get('min_roles', 0):
        errors.append(f"roles={total_roles} < min {fixture['min_roles']}")
    else:
        notes.append(f"roles={total_roles} ✓")

    if total_roles > fixture.get('max_roles', 9999):
        errors.append(f"roles={total_roles} > max {fixture['max_roles']}")

    # Layout check
    if fixture.get('layout'):
        with pdfplumber.open(str(pdf_path)) as pdf:
            col = detect_column_layout(pdf.pages)
        detected = 'columnar' if col else 'sequential'
        expected_layout = fixture['layout']
        if detected != expected_layout:
            errors.append(f"layout={detected} (expected {expected_layout})")
        else:
            notes.append(f"layout={detected} ✓")

    # Spot checks
    for chk in fixture.get('checks', []):
        day_num = chk.get('day')
        day = next((d for d in days if d.get('dayNumber') == day_num), None)

        if day is None:
            errors.append(f"day {day_num} not found")
            continue

        if 'min_scenes' in chk and len(day['scenes']) < chk['min_scenes']:
            errors.append(f"day {day_num}: scenes={len(day['scenes'])} < {chk['min_scenes']}")
        else:
            if 'min_scenes' in chk:
                notes.append(f"day {day_num} scenes={len(day['scenes'])} ✓")

        if 'scene_id' in chk:
            sid = chk['scene_id']
            scene = next((s for s in day['scenes']
                          if s.get('sceneId','').lower() == sid.lower()), None)
            if scene is None:
                errors.append(f"day {day_num}: scene '{sid}' not found")
            elif chk.get('has_roles') and not scene['roles']:
                errors.append(f"day {day_num} scene '{sid}': expected roles, got none")
            elif chk.get('has_roles'):
                notes.append(f"day {day_num} scene '{sid}' has roles ✓")

    summary = f"{total_days}d / {total_scenes}sc / {total_roles}r in {elapsed:.1f}s"
    if errors:
        return ('FAIL', summary + ' — ' + '; '.join(errors))
    return ('PASS', summary + ' — ' + ', '.join(notes))


def main():
    print("\n" + "="*70)
    print("  BGBoard Schedule Parser — Regression Test Suite")
    print("="*70)

    # Optional: filter to specific PDF by name fragment
    filter_arg = sys.argv[1] if len(sys.argv) > 1 else None

    passed = failed = skipped = 0
    results = []

    for fixture in FIXTURES:
        if filter_arg and filter_arg.lower() not in fixture['pdf'].lower():
            continue

        print(f"\n▶ {fixture['desc']}")
        print(f"  {fixture['pdf']}")

        status, detail = run_fixture(fixture)

        if status == 'PASS':
            passed += 1
            print(f"  ✓ PASS   {detail}")
        elif status == 'FAIL':
            failed += 1
            print(f"  ✗ FAIL   {detail}")
        else:
            skipped += 1
            print(f"  ─ SKIP   {detail}")

        results.append((status, fixture['pdf'], detail))

    print("\n" + "="*70)
    print(f"  Results: {passed} passed · {failed} failed · {skipped} skipped")
    print("="*70 + "\n")

    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
