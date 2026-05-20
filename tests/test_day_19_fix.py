#!/usr/bin/env python3
"""
test_day_19_fix.py — Targeted regression test for beta #4 (Day-19 start bug).

Simulates a partial shooting schedule that starts at Day 19 (not Day 1).
Verifies that:
  1. classify_row picks up "End of Day 19" and captures the day number
     even without the picky "--" or all-caps formatting.
  2. assemble_schedule produces days numbered 19, 20, 21 — NOT 1, 2, 3.

Run: python3 tests/test_day_19_fix.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from parse_shootsked import classify_row, assemble_schedule


def test_classify_end_of_day_19():
    """Generic 'End of Day 19' (no --, mixed case) must capture day=19."""
    # The picky patterns require "--" or all-caps "DAY"; this row has neither.
    evt_type, evt_data = classify_row("End of Day 19  Monday, October 27, 2025")
    assert evt_type == 'day_end', f"Expected day_end, got {evt_type}"
    assert evt_data.get('day') == 19, f"Expected day=19, got {evt_data.get('day')}"
    print("  PASS: 'End of Day 19' captures day=19")


def test_classify_end_of_day_no_number():
    """Plain 'End of Day' (no number) still falls through cleanly to day=None."""
    evt_type, evt_data = classify_row("End of Day")
    assert evt_type == 'day_end', f"Expected day_end, got {evt_type}"
    assert evt_data.get('day') is None, f"Expected day=None, got {evt_data.get('day')}"
    print("  PASS: 'End of Day' (no number) → day=None")


def test_assemble_starts_at_19():
    """A schedule that starts at Day 19 must produce dayNumber=19 — not 1."""
    # Sequential mode: (left_text, full_text) tuples
    rows = [
        ("Sc. 100  INT  OFFICE  DAY",    "Sc. 100  INT  OFFICE  DAY"),
        ("Background Actors",             "Background Actors"),
        ("3 OFFICE WORKERS",              "3 OFFICE WORKERS"),
        ("End of Day 19  Monday Oct 27",  "End of Day 19  Monday Oct 27, 2025"),
        ("Sc. 101  EXT  STREET  DAY",    "Sc. 101  EXT  STREET  DAY"),
        ("Background Actors",             "Background Actors"),
        ("2 PEDESTRIANS",                 "2 PEDESTRIANS"),
        ("End of Day 20  Tuesday Oct 28", "End of Day 20  Tuesday Oct 28, 2025"),
    ]
    days, _show, _ep = assemble_schedule(rows, column_mode=False)
    day_numbers = [d['dayNumber'] for d in days]
    assert day_numbers == [19, 20], (
        f"Day-19-start regression: got dayNumbers={day_numbers}, expected [19, 20]"
    )
    print(f"  PASS: Day-19 start produces dayNumbers={day_numbers}")


def test_assemble_starts_at_19_with_unknown_first_end():
    """Schedule with bare 'End of Day' (no number) as the first marker should
    still infer days from the next labeled marker."""
    rows = [
        ("Sc. 100  INT  OFFICE  DAY",    "Sc. 100  INT  OFFICE  DAY"),
        ("Background Actors",             "Background Actors"),
        ("3 OFFICE WORKERS",              "3 OFFICE WORKERS"),
        ("End of Day",                    "End of Day"),  # no number — falls to day_n=1 (cold start)
        ("Sc. 101  EXT  STREET  DAY",    "Sc. 101  EXT  STREET  DAY"),
        ("2 PEDESTRIANS",                 "2 PEDESTRIANS"),
        ("End of Day 20  Tuesday Oct 28", "End of Day 20  Tuesday Oct 28, 2025"),
    ]
    days, _show, _ep = assemble_schedule(rows, column_mode=False)
    day_numbers = [d['dayNumber'] for d in days]
    # First marker had no number — cold start, falls back to 1.
    # Second marker is explicit Day 20.
    # The previous code defaulted second unknown to len(days)+1 = 2;
    # behavior unchanged for this edge case since we have a real number on day 2.
    assert day_numbers == [1, 20], (
        f"Mixed-marker case: got dayNumbers={day_numbers}, expected [1, 20]"
    )
    print(f"  PASS: Mixed known/unknown end markers → dayNumbers={day_numbers}")


def test_assemble_starts_with_day_19_header():
    """Schedule with 'Day 19' day_start header should also produce Day 19."""
    rows = [
        ("Day 19 - Monday October 27",    "Day 19 - Monday October 27, 2025"),
        ("Sc. 100  INT  OFFICE  DAY",    "Sc. 100  INT  OFFICE  DAY"),
        ("Background Actors",             "Background Actors"),
        ("3 OFFICE WORKERS",              "3 OFFICE WORKERS"),
        ("Day 20 - Tuesday October 28",   "Day 20 - Tuesday October 28, 2025"),
        ("Sc. 101  EXT  STREET  DAY",    "Sc. 101  EXT  STREET  DAY"),
        ("2 PEDESTRIANS",                 "2 PEDESTRIANS"),
    ]
    days, _show, _ep = assemble_schedule(rows, column_mode=False)
    day_numbers = [d['dayNumber'] for d in days]
    assert day_numbers == [19, 20], (
        f"Day-19 header start: got dayNumbers={day_numbers}, expected [19, 20]"
    )
    print(f"  PASS: 'Day 19' header start → dayNumbers={day_numbers}")


if __name__ == '__main__':
    print("Testing beta #4 fix (Day-19 start)...")
    tests = [
        test_classify_end_of_day_19,
        test_classify_end_of_day_no_number,
        test_assemble_starts_at_19,
        test_assemble_starts_at_19_with_unknown_first_end,
        test_assemble_starts_with_day_19_header,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"  FAIL: {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print()
    if failed:
        print(f"✗ {failed} of {len(tests)} tests failed")
        sys.exit(1)
    print(f"✓ All {len(tests)} tests passed")
