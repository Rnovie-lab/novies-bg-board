#!/usr/bin/env python3
"""
parse_shootsked.py — Movie Magic Scheduling PDF → BGBoard JSON

Usage:
    python3 parse_shootsked.py <shootsked.pdf> [output.json]

Output is a BGBoard-compatible JSON file imported via the
"↑ Import" button in BGBoard.html.
"""

import sys
import json
import re
import uuid
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("Error: pdfplumber not installed. Run: pip install pdfplumber --break-system-packages")
    sys.exit(1)


# ── helpers ───────────────────────────────────────────────────────────────────

def uid():
    return str(uuid.uuid4())[:8]


MONTHS = {
    'january': '01', 'february': '02', 'march': '03', 'april': '04',
    'may': '05', 'june': '06', 'july': '07', 'august': '08',
    'september': '09', 'october': '10', 'november': '11', 'december': '12'
}

def parse_date(text):
    """Extract 'YYYY-MM-DD' from text containing e.g. 'Monday, October 27, 2025'."""
    try:
        m = re.search(r'(\w+)\s+(\d{1,2}),\s+(\d{4})', text, re.I)
        if m:
            month = MONTHS.get(m.group(1).lower(), '00')
            day = m.group(2).zfill(2)
            year = m.group(3)
            return f"{year}-{month}-{day}"
    except Exception:
        pass
    return ''


def extract_dual_lines(page, x_split=310):
    """
    Returns a list of (left_text, full_text) tuples, one per visual line.

    - left_text: text from words whose x0 < x_split  (left column — BG actors, Cast)
    - full_text: text from ALL words on that line     (includes right-col context)

    Movie Magic Scheduling has a two-column layout at roughly x=310:
      Left:  Schedule data, Cast, Background Actors
      Right: Props, Art Department, Set Dressing, etc.
    """
    words = page.extract_words(x_tolerance=4, y_tolerance=4)
    lines = {}
    for w in words:
        y = round(float(w['top']) / 3) * 3
        lines.setdefault(y, []).append(w)

    result = []
    for y in sorted(lines.keys()):
        all_words = sorted(lines[y], key=lambda w: float(w['x0']))
        left_words = [w for w in all_words if float(w['x0']) < x_split]
        left_text = ' '.join(w['text'] for w in left_words).strip()
        full_text = ' '.join(w['text'] for w in all_words).strip()
        if full_text:
            result.append((left_text, full_text))

    return result


# ── regex patterns ────────────────────────────────────────────────────────────

# "Shoot Day # 1 Monday, October 27, 2025"
RE_SHOOT_DAY = re.compile(r'^Shoot\s+Day\s+#\s*(\d+)\s+(.*)', re.I)

# "End Day # 1 Monday, October 27, 2025 -- ..."
RE_END_DAY = re.compile(r'^End\s+Day\s+#', re.I)

# "Scene # 7, 9" or "Scene # 10" or "Scene # 16pt3" — match scene number start
# We match against LEFT text (clean ID only) and FULL text (includes description)
RE_SCENE = re.compile(r'^Scene\s+#\s*(.+)$', re.I)

# Section headers we recognize as the BG section
BG_HEADERS = {'Background Actors', 'Background Actor', 'Background', 'Extras'}

# Section headers that end the BG section
NON_BG_HEADERS = {
    'Cast Members', 'Cast', 'Special Equipment', 'Props', 'Set Dressing',
    'Vehicles', 'Picture Cars', 'Art Department', 'Special Effects', 'Music',
    'Hair/Makeup', 'Wardrobe', 'Animals', 'Notes', 'Stunts',
    'Mechanical Effects', 'Sound', 'Camera', 'Electric', 'Grip',
    'Location Notes', 'Production', 'Miscellaneous', 'Additional Labor',
}

# Printed noise / page artifacts — match lines that START with any of these
RE_PAGE_NOISE = re.compile(
    r'^(Page\s+\d+|Printed\s+on\s|Day\s+Out\s+Of|DOOD|Total\s+Pages|'
    r'Revision\s|Revised\s|REVISED\s|Locked\s|LOCKED\s|'
    r'Previously\s+Shot|Scene\s+Count)',
    re.I
)

# Lines that are clearly production-side notes, not BG extras
# e.g. "roll to stage", "HAPPY HALLOWEEN!!!!", "show kelly what..."
RE_LIKELY_NOTE = re.compile(
    r'^(roll\s|move\s|shoot\s|see\s|note[:\s]|show\s|per\s|ot\s|tlbd|tbd)',
    re.I
)

# BG entry: optional leading count, then description
# "11 other doctors" → (11, "other doctors")
# "3 nurses"         → (3, "nurses")
# "nurses"           → (1, "nurses")
# But NOT: "2.RON" (cast members formatted as "N.NAME")
RE_CAST = re.compile(r'^\d+\.[A-Z]')

RE_BG_COUNT = re.compile(r'^(\d+)\s+(.+)$')


def classify_left_line(left_text):
    """Return the semantic type of a left-column line."""
    s = left_text.strip()
    if not s:
        return 'empty'
    if s in BG_HEADERS:
        return 'bg_header'
    if s in NON_BG_HEADERS:
        return 'section_header'
    if RE_PAGE_NOISE.match(s):
        return 'noise'
    if RE_CAST.match(s):
        return 'cast_entry'
    return 'content'


def parse_bg_role(line):
    """
    Parse a BG entry line → (count, description) or None if unrecognizable.
    """
    line = line.strip()
    if not line or len(line) < 2:
        return None
    # Skip obvious noise
    if RE_PAGE_NOISE.match(line):
        return None
    # Skip cast entries
    if RE_CAST.match(line):
        return None

    m = RE_BG_COUNT.match(line)
    if m:
        return (int(m.group(1)), m.group(2).strip())
    else:
        return (1, line)


# ── main parser ───────────────────────────────────────────────────────────────

def parse_shootsked(pdf_path):
    print(f"Opening: {pdf_path}")

    all_dual_lines = []
    with pdfplumber.open(pdf_path) as pdf:
        print(f"Pages: {len(pdf.pages)}")
        for i, page in enumerate(pdf.pages, 1):
            pairs = extract_dual_lines(page)
            all_dual_lines.extend(pairs)
            print(f"  Page {i}: {len(pairs)} lines")

    if not all_dual_lines:
        print("ERROR: No text extracted. PDF may be image-based.")
        sys.exit(1)

    # ── detect show info from top of document ────────────────────────────────
    show_name = ''
    episode = ''
    for left, full in all_dual_lines[:15]:
        # Episode: "Ep# 217"
        ep_m = re.search(r'Ep#?\s*(\d{2,3})', full, re.I)
        if ep_m and not episode:
            episode = ep_m.group(1)
        # Show name: first quoted or long non-header line
        if (not show_name and len(left) > 6 and
                not RE_SHOOT_DAY.match(left) and
                not RE_SCENE.match(left) and
                not left.startswith('Shooting Schedule') and
                not left.startswith('DIRECTOR')):
            if re.search(r'[A-Za-z]{3,}', left):
                show_name = left

    print(f"\nShow: '{show_name}', Episode: '{episode}'")

    # Collect page-header fingerprints (lines that repeat at the top of every page)
    # These are the first ~6 left-column lines of the document; skip them throughout.
    page_header_skip = set()
    for left, full in all_dual_lines[:8]:
        if left.strip():
            page_header_skip.add(left.strip())
    # Also add "Shooting Schedule" as a known page header phrase
    page_header_skip.add('Shooting Schedule')

    # ── state machine ─────────────────────────────────────────────────────────
    days = []
    current_day = None
    current_scene = None
    pending_location = ''   # location line seen before Scene #
    in_bg_section = False

    def start_scene(scene_id, set_text, desc=''):
        nonlocal current_scene, in_bg_section
        commit_scene()
        in_bg_section = False
        current_scene = {
            'id': uid(),
            'sceneId': scene_id.strip().rstrip(',').strip(),
            'set': set_text.strip(),
            'desc': desc.strip(),
            'roles': []
        }

    def commit_scene():
        if current_scene is not None and current_day is not None:
            current_day['scenes'].append(current_scene)

    def start_day(day_number, date_text):
        nonlocal current_day, current_scene, in_bg_section, pending_location
        commit_scene()
        current_scene = None
        in_bg_section = False
        pending_location = ''
        d = {
            'id': uid(),
            'dayNumber': day_number,
            'date': parse_date(date_text),
            'scenes': [],
            'standinOff': {},
            'standinHours': {}
        }
        days.append(d)
        current_day = d
        print(f"  Day {day_number}: {parse_date(date_text) or date_text}")

    # ── iterate lines ─────────────────────────────────────────────────────────
    for left, full in all_dual_lines:

        # ── Shoot Day header (use full_text for date) ─────────────────────
        m = RE_SHOOT_DAY.match(full)
        if m:
            start_day(int(m.group(1)), m.group(2))
            continue

        # ── End Day marker ────────────────────────────────────────────────
        if RE_END_DAY.match(full):
            commit_scene()
            current_scene = None
            in_bg_section = False
            pending_location = ''
            continue

        # Skip if no shooting day has started yet
        if current_day is None:
            continue

        # ── Scene header ──────────────────────────────────────────────────
        # Use LEFT text for scene ID (clean, no description bleed-over)
        # Use FULL text for description (may contain dashes, special chars)
        m_left_scene = RE_SCENE.match(left)
        if m_left_scene:
            scene_id = m_left_scene.group(1).strip().rstrip(',').strip()
            # Description: whatever full_text has beyond the left_text prefix
            desc = ''
            if full != left:
                # full starts with left (or close to it); extract the extra part
                # e.g. left="Scene # 10", full="Scene # 10 TH - Bruce..." → "TH - Bruce..."
                desc = full[len(left):].strip()
            # Remove Stage/Day scheduling info that may appear
            desc = re.sub(r'\s*Stage\s+\d+.*$', '', desc, flags=re.I).strip()
            set_text = pending_location or 'TBD'
            start_scene(scene_id, set_text, desc)
            pending_location = ''
            print(f"    Scene {scene_id}: {set_text}")
            continue

        # ── Location line (before Scene #) ────────────────────────────────
        # Location is: "INT/EXT LOCATION" — appears as left_text before Scene#
        # A new location line also signals we've left any active BG section
        if re.match(r'^(INT|EXT)[\s\./]', left, re.I):
            loc = re.sub(r'\s+Stage\s+\d+.*$', '', left, flags=re.I).strip()
            pending_location = loc
            in_bg_section = False   # location boundary always ends BG section
            continue

        # ── Section headers ───────────────────────────────────────────────
        kind = classify_left_line(left)

        if kind == 'bg_header':
            in_bg_section = True
            continue

        if kind == 'section_header':
            in_bg_section = False
            continue

        if kind in ('empty', 'noise', 'cast_entry'):
            continue

        # ── BG entries ────────────────────────────────────────────────────
        if in_bg_section and current_scene is not None:
            # Skip page header / footer lines that repeat on every page
            if left.strip() in page_header_skip:
                continue
            # Skip lines that are clearly page noise ("Printed on...", etc.)
            if RE_PAGE_NOISE.match(left.strip()):
                continue
            # Skip principal performers marked with (p) — not BG extras
            if re.search(r'\(p\)\s*$', left, re.I):
                continue
            # Skip obvious production notes / directions
            if RE_LIKELY_NOTE.match(left.strip()):
                continue
            # Skip lines that are all-caps exclamations / holiday greetings
            if re.match(r'^[A-Z\s!\.]+$', left.strip()) and '!' in left:
                continue
            result = parse_bg_role(left)
            if result:
                count, desc = result
                current_scene['roles'].append({
                    'id': uid(),
                    'type': desc,
                    'count': count,
                    'tier': 'sag',
                    'baseRate': 182,
                    'hours': 8,
                    'bumps': [],
                    'notes': '',
                    'minors': False
                })

    # Commit final scene
    commit_scene()

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\nParsed {len(days)} shooting days:")
    total_roles = 0
    for d in days:
        sc = len(d['scenes'])
        ro = sum(len(s['roles']) for s in d['scenes'])
        total_roles += ro
        print(f"  Day {d['dayNumber']} ({d['date'] or 'no date'}): {sc} scenes, {ro} BG roles")

    print(f"\nTotal BG role entries: {total_roles}")

    return {
        'show': {
            'name': show_name,
            'episode': episode,
            'version': '1',
            'preparedBy': '',
            'contractType': 'tv',
            'sagMin': 25
        },
        'standins': [],
        'days': days
    }


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    state = parse_shootsked(pdf_path)

    out_path = sys.argv[2] if len(sys.argv) >= 3 else \
        str(Path(pdf_path).parent / (Path(pdf_path).stem + '_bgboard.json'))

    with open(out_path, 'w') as f:
        json.dump(state, f, indent=2)

    print(f"\n✓ Saved: {out_path}")
    print("  Import via the '↑ Import' button in BGBoard.html")


if __name__ == '__main__':
    main()
