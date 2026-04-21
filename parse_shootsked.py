#!/usr/bin/env python3
"""
parse_shootsked.py — Scheduling PDF → BGBoard JSON

Supports two formats automatically:
  • Movie Magic Scheduling  (Shoot Day # / Scene # layout)
  • EP / one-line schedule  (NNN Sc N INT/EXT layout, Background column)

Usage:
    python3 parse_shootsked.py <schedule.pdf> [output.json]
"""

import sys
import json
import re
import uuid
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("Error: pdfplumber not installed. Run: pip install pdfplumber")
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
    """Extract 'YYYY-MM-DD' from text like 'Monday, October 27, 2025' or 'April 23, 2025'."""
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


# ── format detection ──────────────────────────────────────────────────────────

def detect_format(pdf):
    """
    Return 'movie_magic', 'ep_oneline', or 'tp_paper' by scanning the first 8 pages.
    movie_magic: 'Shoot Day #' / 'Scene #' + 'End Day #'
    ep_oneline:  'NNN Sc N INT/EXT' headers + 'End of DAY N'
    tp_paper:    'END OF DAY N--' markers + standalone 'Sc. N' scene numbers
                 (The Paper / EP scheduling export with D{N} day headers)
    """
    sample = ''
    for page in pdf.pages[:min(8, len(pdf.pages))]:
        txt = page.extract_text() or ''
        sample += txt + '\n'

    if re.search(r'Shoot\s+Day\s+#', sample, re.I):
        return 'movie_magic'
    if re.search(r'\bScene\s+#', sample, re.I) and re.search(r'End\s+Day\s+#', sample, re.I):
        return 'movie_magic'
    if re.search(r'\d{3}\s+Sc\s+\S+\s+(INT|EXT)', sample):
        return 'ep_oneline'
    # TP Paper format: END OF DAY N-- markers + standalone Sc. N scene numbers
    if re.search(r'END\s+OF\s+DAY\s+\d+--', sample, re.I) and re.search(r'^Sc\.\s+\d', sample, re.M):
        return 'tp_paper'
    # Movie Magic with D{N} day headers (multi-episode / The Paper style)
    if re.search(r'\bScene\s+#', sample, re.I) and re.search(r'^D\d+\s*[-–]', sample, re.M):
        return 'movie_magic'
    # EP format fallback
    if re.search(r'End\s+of\s+DAY', sample, re.I):
        return 'ep_oneline'
    return 'movie_magic'


# ══════════════════════════════════════════════════════════════════════════════
# PARSER A — Movie Magic Scheduling
# ══════════════════════════════════════════════════════════════════════════════

def extract_dual_lines(page, x_split=310):
    """
    Returns (left_text, full_text) tuples per visual line.
    Movie Magic has a two-column layout at roughly x=310.
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


RE_SHOOT_DAY = re.compile(r'^Shoot\s+Day\s+#\s*(\d+)\s+(.*)', re.I)
RE_END_DAY   = re.compile(r'^End\s+Day\s+#', re.I)
RE_SCENE_MM  = re.compile(r'^Scene\s+#?\s*(.+)$', re.I)   # "#" optional (some formats omit it)

BG_HEADERS = {'Background Actors', 'Background Actor', 'Background', 'Extras'}
NON_BG_HEADERS = {
    'Cast Members', 'Cast', 'Special Equipment', 'Props', 'Set Dressing',
    'Vehicles', 'Picture Cars', 'Art Department', 'Special Effects', 'Music',
    'Hair/Makeup', 'Makeup/Hair', 'Wardrobe', 'Animals', 'Notes', 'Stunts',
    'Mechanical Effects', 'Sound', 'Camera', 'Electric', 'Grip',
    'Location Notes', 'Production', 'Miscellaneous', 'Additional Labor',
    'Animal Wrangler', 'Animal Wranglers', 'Safety Bulletins', 'Visual Effects',
    'Synopsis', 'Special Equipment', 'Intimacy Coordinator',
}

RE_DATE_LINE  = re.compile(r'^\w+\s+\d{1,2},\s+\d{4}$', re.I)   # "May 29, 2025"

RE_PAGE_NOISE = re.compile(
    r'^(Page\s+\d+|Printed\s+on\s|Day\s+Out\s+Of|DOOD|Total\s+Pages|'
    r'Revision\s|Revised\s|REVISED\s|Locked\s|LOCKED\s|'
    r'Previously\s+Shot|Scene\s+Count)',
    re.I
)
RE_LIKELY_NOTE = re.compile(
    r'^(roll\s|move\s|shoot\s|see\s|note[:\s]|show\s|per\s|ot\s|tlbd|tbd|'
    r'practical\s|table\s+read|lunch|wrap|company\s|pre-rig|pre\s+rig)',
    re.I
)
RE_CAST = re.compile(r'^\d+\.\s*[A-Z]')        # handles "4.BRUCE" and "4. BRUCE"
RE_SLUG = re.compile(r'^(INT|EXT|INT/EXT)\s*[\./\-\s]', re.I)   # slug lines
RE_D_DAY  = re.compile(r'^D(\d+)\s*[-–]\s*(\S.*)', re.I)  # 'D1 - Monday ...' day header
RE_SCENE_HDR = re.compile(r'^Scene\s*#', re.I)  # "Scene # 28 gets Kelly's"
RE_BG_COUNT_MM = re.compile(r'^(\d+)\s+(.+)$')


BG_HEADER_WORDS = tuple(h.lower() for h in BG_HEADERS)
NON_BG_HEADER_WORDS = tuple(h.lower() for h in NON_BG_HEADERS)

def classify_left_line(left_text):
    s = left_text.strip()
    if not s:                   return 'empty'
    if s in BG_HEADERS:         return 'bg_header'
    if s in NON_BG_HEADERS:     return 'section_header'
    if RE_PAGE_NOISE.match(s):  return 'noise'
    if RE_CAST.match(s):        return 'cast_entry'
    if RE_SLUG.match(s):        return 'slug'
    if RE_SCENE_HDR.match(s):   return 'scene_header'
    # Handle merged lines where BG/Extras header is fused with adjacent column content
    sl = s.lower()
    if any(sl.startswith(h + ' ') for h in BG_HEADER_WORDS):   return 'bg_header'
    if any(sl.startswith(h + ' ') for h in NON_BG_HEADER_WORDS): return 'section_header'
    return 'content'


RE_BG_LABEL = re.compile(r'^BG\s+\w', re.I)   # "BG pool goers", "BG w/ cars" etc.

def parse_bg_role_mm(line):
    """Movie Magic BG line → (count, description) or None."""
    line = line.strip()
    if not line or len(line) < 2: return None
    if RE_PAGE_NOISE.match(line): return None
    if RE_CAST.match(line): return None
    if RE_SLUG.match(line): return None
    if RE_SCENE_HDR.match(line): return None
    if RE_LIKELY_NOTE.match(line): return None
    # Strip props merged from adjacent columns — stop at first prop-like word
    # e.g. "100 bg Jinx personal props" → "100 bg"
    # e.g. "Small Group of People BG Pool props" → "Small Group of People"
    clean = re.split(r'\s+(?=[A-Z][a-z]+\s+props|BG\s+\w+\s+props|\bprops\b|\bwardrobe\b|\bart\s+dept|\bset\s+dress|\bcamera\b|\bvehicles?\b|\blocations?\b)', line, flags=re.I)[0].strip()
    m = RE_BG_COUNT_MM.match(clean)
    if m:
        return (int(m.group(1)), m.group(2).strip())
    # No leading count — accept "BG Xxx" labels or ALL-CAPS multi-word descriptions
    if RE_BG_LABEL.match(clean) and len(clean) > 4:
        return (1, clean)
    # All-caps multi-word BG labels: "BALLOON DELIVERY PERSON", "ALEXANDER SOFTEE (Nathan)"
    if (re.match(r'^[A-Z][A-Z0-9 \-/\(\)\'\.\_]+$', clean)
            and len(clean.split()) >= 2 and 4 < len(clean) <= 80
            and not RE_CAST.match(clean)):
        return (1, clean)
    return None


RE_MID_PROP = re.compile(r'\s+\d+\.\S')   # mid-line prop number e.g. "... 6.sleeping"
RE_SECTION_WORD = re.compile(
    r'\s+(?:Wardrobe|Makeup|Art\s+Dept(?:artment)?|Set\s+Dress(?:ing)?|'
    r'Special\s+(?:Effects|Equipment)|Animal\s+Wrangler|Sound|Camera|'
    r'Electric|Grip|Vehicles?|Stunts?|Production|Notes?|Synopsis|Safety|'
    r'Intimacy|Visual\s+Effects)\b',
    re.I
)

def parse_bg_role_ocr(line):
    """BG role parser for OCR text.

    Differences from parse_bg_role_mm:
    - Does NOT apply RE_CAST filter (BG entries look identical to cast: "N.Name")
    - Strips merged right-column props/section text before parsing
    """
    line = line.strip()
    if not line or len(line) < 2: return None
    if RE_PAGE_NOISE.match(line): return None
    if RE_LIKELY_NOTE.match(line): return None

    # Strip anything starting from a mid-line prop number ("6.sleeping bag")
    clean = RE_MID_PROP.split(line)[0].strip()
    # Strip section-header words merged from adjacent column
    clean = RE_SECTION_WORD.split(clean)[0].strip()

    # Match "N. Description", "N.Description", or "N Description"
    m = re.match(r'^(\d+)[\.\s]+(.+)$', clean)
    if m:
        count = int(m.group(1))
        desc  = m.group(2).strip().lstrip('. ').rstrip(',')
        if not desc or len(desc) < 2: return None
        # Reject sentence fragments that leaked in from synopsis / scene description
        if re.match(r'^(He|She|They|It|We|His|Her|Their|The\s+\w+\s+(takes|sits|walks|runs|goes|is|was))\b', desc, re.I):
            return None
        if len(desc) > 60 and re.search(r'\b(takes|sits|stands|walks|runs|goes|into|last|sip|drink)\b', desc, re.I):
            return None
        return (count, desc)

    # Descriptor without number (e.g. "BG farmers", "ND PEDESTRIANS")
    if RE_BG_LABEL.match(clean) and len(clean) > 4:
        return (1, clean)

    return None


def make_role(count, desc):
    return {
        'id': uid(), 'type': desc, 'count': count,
        'tier': 'sag', 'baseRate': 182, 'hours': 8,
        'bumps': [], 'notes': '', 'minors': False
    }


def parse_movie_magic(pdf):
    """Parse Movie Magic Scheduling PDF."""
    print("  Format: Movie Magic Scheduling")

    all_dual_lines = []
    for i, page in enumerate(pdf.pages, 1):
        pairs = extract_dual_lines(page)
        all_dual_lines.extend(pairs)
        print(f"  Page {i}: {len(pairs)} lines")

    if not all_dual_lines:
        raise ValueError("No text extracted. PDF may be image-based.")

    # Show info from top
    show_name = ''
    episode = ''
    for left, full in all_dual_lines[:15]:
        ep_m = re.search(r'Ep#?\s*(\d{2,3})', full, re.I)
        if ep_m and not episode:
            episode = ep_m.group(1)
        if (not show_name and len(left) > 6 and
                not RE_DATE_LINE.match(left) and
                not RE_SHOOT_DAY.match(left) and not RE_SCENE_MM.match(left) and
                not left.startswith('Shooting Schedule') and
                not left.startswith('WHITE SHOOTING') and
                not left.startswith('DIRECTOR') and
                not left.startswith('Episode #') and
                not left.startswith('1st AD') and
                re.search(r'[A-Za-z]{3,}', left)):
            show_name = left

    print(f"\n  Show: '{show_name}', Episode: '{episode}'")

    # Page-header fingerprint
    page_header_skip = set()
    for left, full in all_dual_lines[:8]:
        if left.strip():
            page_header_skip.add(left.strip())
    page_header_skip.add('Shooting Schedule')

    days = []
    current_day = None
    current_scene = None
    pending_location = ''
    in_bg_section = False

    def start_scene(scene_id, set_text, desc=''):
        nonlocal current_scene, in_bg_section
        commit_scene()
        in_bg_section = False
        current_scene = {
            'id': uid(), 'sceneId': scene_id.strip().rstrip(',').strip(),
            'set': set_text.strip(), 'desc': desc.strip(), 'roles': []
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
            'id': uid(), 'dayNumber': day_number,
            'date': parse_date(date_text), 'scenes': [],
            'standinOff': {}, 'standinHours': {}
        }
        days.append(d)
        current_day = d
        print(f"  Day {day_number}: {parse_date(date_text) or date_text}")

    for left, full in all_dual_lines:
        m = RE_SHOOT_DAY.match(full)
        if m:
            start_day(int(m.group(1)), m.group(2))
            continue
        # D{N} - Weekday style day headers (multi-episode / The Paper format)
        m_d = RE_D_DAY.match(full)
        if m_d:
            start_day(int(m_d.group(1)), m_d.group(2))
            continue
        if RE_END_DAY.match(full):
            commit_scene()
            current_scene = None
            in_bg_section = False
            pending_location = ''
            continue
        if current_day is None:
            continue

        m_left_scene = RE_SCENE_MM.match(left)
        if m_left_scene:
            rest = m_left_scene.group(1).strip().rstrip(',').strip()
            # pdfplumber may merge adjacent words: 'EXT FLAMINGO' → 'EXTFLAMINGO'
            # Re-insert the space between INT/EXT and the location name
            rest = re.sub(r'\b(INT/EXT|I/E|INT|EXT)([A-Z\'\(])', r'\1 \2', rest)
            # Some schedules put INT/EXT inline: "509 EXT FLAMINGO HOTEL - HABITAT"
            # Also handles multi-word scene IDs: "522, A523 INT CASINO - TABLE"
            # Non-greedy (.+?) stops at the FIRST INT/EXT token
            loc_m = re.match(r'^(.+?)\s+(INT/EXT|I/E|INT|EXT)\s+(.+)$', rest, re.I)
            if loc_m:
                scene_id = loc_m.group(1)
                inline_loc = loc_m.group(2).upper() + ' ' + loc_m.group(3).strip()
                inline_loc = re.sub(r'\s+Stage\s+\d+.*$', '', inline_loc, flags=re.I).strip()
                set_for_scene = pending_location if pending_location else inline_loc
            else:
                scene_id = rest
                set_for_scene = pending_location or 'TBD'
            desc = ''
            if full != left:
                desc = full[len(left):].strip()
            desc = re.sub(r'\s*Stage\s+\d+.*$', '', desc, flags=re.I).strip()
            start_scene(scene_id, set_for_scene, desc)
            pending_location = ''
            print(f"    Scene {scene_id}: {set_for_scene}")
            continue

        if re.match(r'^(INT|EXT)[\s\./]', left, re.I):
            loc = re.sub(r'\s+Stage\s+\d+.*$', '', left, flags=re.I).strip()
            pending_location = loc
            in_bg_section = False
            continue

        kind = classify_left_line(left)
        if kind == 'bg_header':
            in_bg_section = True
            continue
        if kind == 'section_header':
            in_bg_section = False
            continue
        if kind in ('empty', 'noise', 'cast_entry'):
            continue
        if kind in ('slug', 'scene_header'):
            in_bg_section = False
            continue

        if in_bg_section and current_scene is not None:
            if left.strip() in page_header_skip: continue
            if RE_PAGE_NOISE.match(left.strip()): continue
            if re.search(r'\(p\)\s*$', left, re.I): continue
            if RE_LIKELY_NOTE.match(left.strip()): continue
            if re.match(r'^[A-Z\s!\.]+$', left.strip()) and '!' in left: continue
            result = parse_bg_role_mm(left)
            if result:
                count, desc = result
                current_scene['roles'].append(make_role(count, desc))

    commit_scene()
    return days, show_name, episode


# ══════════════════════════════════════════════════════════════════════════════
# PARSER B — EP / One-Line Schedule Format
# ══════════════════════════════════════════════════════════════════════════════

# Scene header: "309 Sc 3 INT WELLS FOUNDATION - BULLPEN D1 4, 5 Stage 17"
# Day/night indicator must have a digit (D1, N2, FBD1) — NOT generic words like DRESSING
RE_EP_SCENE = re.compile(
    r'^(\d{2,3})\s+Sc\s+(\S+)\s+(INT/EXT|INT|EXT)\s+(.+?)\s+(D\d+\w*|N\d+\w*|FBD\w+)\s',
    re.I
)
# Also catch scenes without trailing space (end of line)
RE_EP_SCENE2 = re.compile(
    r'^(\d{2,3})\s+Sc\s+(\S+)\s+(INT/EXT|INT|EXT)\s+(.+?)\s+(D\d+\w*|N\d+\w*|FBD\w+)\s*$',
    re.I
)

# "End of DAY 1 Wednesday April 23, 2025"
RE_EP_DAY_END = re.compile(
    r'^End\s+of\s+DAY\s+(\d+)\s+\w+\s+(\w+\s+\d+,\s+\d{4})',
    re.I
)

# Trailing (n) count
RE_EP_BG_COUNT = re.compile(r'\((\d+)\)\s*$')

# Section header words that terminate the BG column
EP_NON_BG_SECTION_STARTS = {
    'Wardrobe', 'Makeup/Hair', 'Set', 'Video', 'Special',
    'Questions', 'Comments', 'Visual', 'Notes', 'Vehicles'
}


def parse_ep_oneline(pdf):
    """Parse EP / one-line schedule format (e.g., Showbiz Scheduling exports)."""
    print("  Format: EP One-Line Schedule")

    # Collect all word rows with x,y positions
    all_rows = []
    for i, page in enumerate(pdf.pages, 1):
        words = page.extract_words(x_tolerance=3, y_tolerance=3)
        rows = {}
        for w in words:
            y = round(w['top'], 0)
            rows.setdefault(y, []).append(w)
        page_rows = []
        for y in sorted(rows.keys()):
            page_rows.append(sorted(rows[y], key=lambda w: w['x0']))
        all_rows.extend(page_rows)
        print(f"  Page {i}: {len(page_rows)} rows")

    # Show name detection from first ~10 rows
    show_name = ''
    episode = ''
    skip_patterns = re.compile(
        r'^(Created|Block|Shooting\s+Schedule|LOOT\s+-\s+BLOCK|BASED\s+ON|\d{3}\s+Sc)',
        re.I
    )
    for ws in all_rows[:12]:
        line = ' '.join(w['text'] for w in ws)
        # Episode: look for 3-digit number that looks like an ep number
        if not episode:
            ep_m = re.search(r'\b(3\d{2}|[1-9]\d{2})\b', line)
            if ep_m:
                episode = ep_m.group(1)
        # Show title
        if not show_name and 6 < len(line) < 60 and not skip_patterns.match(line):
            if re.search(r'[A-Za-z]{4,}', line):
                show_name = line.strip()

    print(f"\n  Show: '{show_name}', Episode: '{episode}'")

    # State
    pending_scenes = []   # scenes collected before an "End of DAY"
    current_scene = None
    in_bg_section = False
    bg_x_start = None
    bg_x_end = None
    bg_pending = []       # accumulate multi-line BG text
    days = []

    def emit_pending_bg():
        """Flush accumulated BG text as a role on current_scene."""
        nonlocal bg_pending
        if not bg_pending or current_scene is None:
            bg_pending = []
            return
        full = ' '.join(bg_pending).strip()
        bg_pending = []
        m = RE_EP_BG_COUNT.search(full)
        if not m:
            return  # incomplete / no count — skip
        count = int(m.group(1))
        desc = full[:m.start()].strip()
        # Clean up: strip surrounding quotes, normalize PP prefix
        desc = desc.strip('"\'')
        # PP "quoted description" → extract just the quoted part
        # PP - DJ, PP - Security guard → keep the PP prefix (meaningful in production)
        if desc.startswith('PP ') and '"' in desc:
            m_q = re.search(r'"([^"]+)"', desc)
            if m_q:
                desc = m_q.group(1).strip()   # extract between quotes
            else:
                desc = desc[3:].strip('"\'').strip()
        if not desc:
            desc = 'Background'
        current_scene['roles'].append(make_role(count, desc))

    def commit_scene():
        emit_pending_bg()
        if current_scene is not None:
            pending_scenes.append(current_scene)

    def close_day(day_num, date_text):
        nonlocal current_scene, in_bg_section, bg_x_start, bg_x_end, bg_pending
        commit_scene()
        current_scene = None
        in_bg_section = False
        bg_x_start = None
        bg_x_end = None
        bg_pending = []
        d = {
            'id': uid(), 'dayNumber': day_num,
            'date': parse_date(date_text),
            'scenes': list(pending_scenes),
            'standinOff': {}, 'standinHours': {}
        }
        pending_scenes.clear()
        days.append(d)
        print(f"  Day {day_num}: {parse_date(date_text) or date_text} — {len(d['scenes'])} scenes")

    for ws in all_rows:
        full_text = ' '.join(w['text'] for w in ws)

        # ── End of DAY marker ─────────────────────────────────────────────────
        m_day = RE_EP_DAY_END.match(full_text)
        if m_day:
            close_day(int(m_day.group(1)), m_day.group(2))
            continue

        # ── Scene header ──────────────────────────────────────────────────────
        m_sc = RE_EP_SCENE.match(full_text) or RE_EP_SCENE2.match(full_text)
        if m_sc:
            emit_pending_bg()
            commit_scene()
            episode_num = m_sc.group(1)
            scene_id = m_sc.group(2)
            int_ext = m_sc.group(3)
            location_raw = m_sc.group(4).strip()
            # Strip trailing Stage info
            location = re.sub(r'\s+Stage\s+\d+.*$', '', location_raw, flags=re.I).strip()
            set_text = f"{int_ext} {location}"
            if not episode:
                episode = episode_num

            current_scene = {
                'id': uid(),
                'sceneId': scene_id.strip(),
                'set': set_text.strip(),
                'desc': '',
                'roles': []
            }
            in_bg_section = False
            bg_x_start = None
            bg_x_end = None
            bg_pending = []
            print(f"    Scene {scene_id}: {set_text}")
            continue

        # ── Section header row containing "Cast" ──────────────────────────────
        # These rows look like: "Cast  Background  Props"
        if ws and ws[0]['text'] == 'Cast':
            emit_pending_bg()
            bg_cols = [w for w in ws if w['text'] == 'Background']
            if bg_cols:
                bx = bg_cols[0]['x0']
                others = [w['x0'] for w in ws if w['x0'] > bx + 10]
                bg_x_start = bx - 5
                bg_x_end = (min(others) - 5) if others else 9999
                in_bg_section = True
            else:
                in_bg_section = False
                bg_x_start = None
                bg_x_end = None
            continue

        # ── Other section headers (Wardrobe, Set Dressing, etc.) ──────────────
        if ws and ws[0]['text'] in EP_NON_BG_SECTION_STARTS and len(ws) <= 8:
            emit_pending_bg()
            in_bg_section = False
            continue

        # ── BG content extraction from Background column ───────────────────────
        if in_bg_section and bg_x_start is not None and current_scene is not None:
            bg_words = [
                w['text'] for w in ws
                if bg_x_start <= w['x0'] < bg_x_end
            ]
            if bg_words:
                chunk = ' '.join(bg_words)
                bg_pending.append(chunk)
                # If this chunk ends with (n), it's a complete entry
                if RE_EP_BG_COUNT.search(chunk):
                    emit_pending_bg()

    # Finalize: any scenes that came after the last End of DAY
    commit_scene()
    if pending_scenes:
        days.append({
            'id': uid(), 'dayNumber': len(days) + 1,
            'date': '', 'scenes': list(pending_scenes),
            'standinOff': {}, 'standinHours': {}
        })
        pending_scenes.clear()

    return days, show_name, episode



# ══════════════════════════════════════════════════════════════════════════════
# PARSER C — TP Paper / EP Multi-Column Schedule (e.g. The Paper ep 207)
# ══════════════════════════════════════════════════════════════════════════════
# Day start:  "D{N} - Weekday (crew call)"
# Day end:    "END OF DAY {N}-- Mon, March 23, 2026-- 8 2/8 Pgs."
# Scene:      INT/EXT LOCATION DAY D{N} {pages} pg Stage {N} ...
#             followed by "Sc. {scene_id}" on next line
#           OR "Sc. {scene_id} INT/EXT LOCATION ..." all on one line
# BG column:  identified by "Background" in "Cast Background X" header rows
#             OR standalone "Background" section header

RE_TP_D_DAY   = re.compile(r'^D(\d+)\s*[-\u2013]\s*(\S.*)', re.I)
RE_TP_DAY_END = re.compile(r'^END\s+OF\s+DAY\s+(\d+)--\s*\w+,\s*(\w+\s+\d+,\s+\d{4})', re.I)
RE_TP_SC_INLINE = re.compile(r'^Sc\.\s+(\S+)\s+(INT/EXT|INT|EXT)\s+(.+)', re.I)
RE_TP_SC_ALONE  = re.compile(r'^Sc\.\s+([\w,\s\.]+?)(?:\s+[A-Z])?\s*$', re.I)
RE_TP_INTXT     = re.compile(r'^(INT/EXT|INT|EXT)\s+(.+)', re.I)

TP_NON_BG = {'Cast', 'Cast DOD', 'BG Cast', 'Props', 'Wardrobe', 'Costumes',
             'Makeup/Hair', 'Set Lighting', 'Set Dressing', 'Sound', 'Camera',
             'Electric', 'Grip', 'VFX', 'SPFX', 'Notes', 'Misc', 'Location Notes',
             'Practical Screen Content', 'Screen Content for Burn in', 'Video Assist'}


def _strip_tp_location(raw):
    """Strip page count, day/night indicator, stage and timing from an INT/EXT line."""
    s = raw.strip()
    # Strip DAY/NIGH[T] + D{n}/N{n} indicator + everything after
    s = re.sub(r'\s+(?:DAY\s+)?[DN]\d+\s+.*$', '', s, flags=re.I).strip()
    s = re.sub(r'\s+(?:DAY|NIGHT|NIGH)\s*$', '', s, flags=re.I).strip()
    # Strip trailing page count: "1/8 pg", "3 7/8", "2 pg"
    s = re.sub(r'\s+\d+(?:\s+\d+/\d+|/\d+)?\s*pg.*$', '', s, flags=re.I).strip()
    s = re.sub(r'\s+Stage\s+\d+.*$', '', s, flags=re.I).strip()
    return s


def parse_tp_paper(pdf):
    """Parse EP-style multi-column schedule (The Paper / similar shows)."""
    print("  Format: TP Paper (EP multi-column schedule)")

    all_rows = []
    for i, page in enumerate(pdf.pages, 1):
        words = page.extract_words(x_tolerance=3, y_tolerance=3)
        rows = {}
        for w in words:
            y = round(float(w['top']), 0)
            rows.setdefault(y, []).append(w)
        page_rows = []
        for y in sorted(rows.keys()):
            page_rows.append(sorted(rows[y], key=lambda w: float(w['x0'])))
        all_rows.extend(page_rows)
        print(f"  Page {i}: {len(page_rows)} rows")

    # Show/episode detection
    show_name = ''
    episode = ''
    skip_re = re.compile(r'^(TP\s|The\s+Paper\s+-\s+Schedule|Printed|END\s+OF\s+DAY|D\d+\s*[-\u2013]|\.)', re.I)
    for ws in all_rows[:15]:
        line = ' '.join(w['text'] for w in ws)
        if not episode:
            ep_m = re.search(r'\bEp(?:isode)?\s+(\d{2,3})\b', line, re.I)
            if ep_m:
                episode = ep_m.group(1)
        if not show_name and 4 < len(line) < 70 and not skip_re.match(line):
            if re.search(r'[A-Za-z]{4,}', line):
                show_name = line.strip()
    # If show name looks like a schedule header, try to extract show title
    if show_name and re.search(r'Schedule|White|v\d+', show_name, re.I):
        m_show = re.search(r'(The\s+\w+(?:\s+\w+)?)', show_name, re.I)
        if m_show:
            show_name = m_show.group(1)
    print(f"\n  Show: '{show_name}', Episode: '{episode}'")

    days = []
    pending_scenes = []
    current_scene = None
    scene_committed = False   # guard against double-appending to pending_scenes
    current_day_num = None    # just track the day number, not a full dict
    current_day = None        # reference to the current day dict (for finalize)
    pending_location = ''
    in_bg_col = False     # column-based BG extraction active
    in_bg_sec = False     # standalone Background section active
    bg_x_start = None
    bg_x_end = None
    bg_buf = []           # accumulates BG column words across rows

    def flush_bg():
        nonlocal bg_buf
        if not bg_buf or current_scene is None:
            bg_buf = []
            return
        text = ' '.join(bg_buf).strip()
        bg_buf = []
        m = re.match(r'^(\d+)\s+(.+)', text)
        if m:
            count = int(m.group(1))
            desc = m.group(2).strip().rstrip(',')
            # Strip merged column text: stop at known section-header words
            desc = re.split(
                r'\s+(?:Cast\s+DOD|Practical\s+Screen|Set\s+Light|Screen\s+Content|Costumes?|Makeup|SPFX|VFX|Props|Notes|Misc)\b',
                desc, flags=re.I
            )[0].strip().rstrip(',')
            if desc and len(desc) > 1:
                current_scene['roles'].append(make_role(count, desc))
        else:
            # All-caps label without number: 1 person
            if re.match(r'^[A-Z][A-Z0-9 \-/\(\)]+$', text) and len(text.split()) >= 2:
                current_scene['roles'].append(make_role(1, text))

    def commit_scene():
        nonlocal scene_committed
        flush_bg()
        if current_scene is not None and not scene_committed:
            pending_scenes.append(current_scene)
            scene_committed = True

    for ws in all_rows:
        texts = [w['text'] for w in ws]
        full = ' '.join(texts)

        # ── END OF DAY ────────────────────────────────────────────────────────
        m_end = RE_TP_DAY_END.match(full)
        if m_end:
            commit_scene()  # flush BG and add last scene to pending_scenes
            current_scene = None
            scene_committed = False
            in_bg_col = in_bg_sec = False
            bg_x_start = bg_x_end = None
            bg_buf = []
            day_num = int(m_end.group(1))
            d = {
                'id': uid(), 'dayNumber': day_num,
                'date': parse_date(m_end.group(2)),
                'scenes': list(pending_scenes),
                'standinOff': {}, 'standinHours': {}
            }
            pending_scenes.clear()
            days.append(d)
            current_day = d
            print(f"  Day {day_num}: {parse_date(m_end.group(2)) or m_end.group(2)} — {len(d['scenes'])} scenes")
            continue

        # ── Day start header (after END OF DAY) ───────────────────────────────
        m_dday = RE_TP_D_DAY.match(full)
        if m_dday:
            # Don't start a new day here — day boundaries are END OF DAY markers
            # But if we've seen no day yet, initialise
            if not days and current_day is None:
                current_day = {'id': uid(), 'dayNumber': int(m_dday.group(1)),
                               'date': '', 'scenes': [], 'standinOff': {}, 'standinHours': {}}
                pending_scenes.clear()
                print(f"  Day {m_dday.group(1)}: (start)")
            continue

        if current_day is None:
            continue

        # ── Scene: Sc. N INT/EXT LOCATION (inline) ───────────────────────────
        m_sc_inline = RE_TP_SC_INLINE.match(full)
        if m_sc_inline:
            flush_bg()
            commit_scene()
            scene_id = m_sc_inline.group(1).strip().rstrip(',').strip()
            ie = m_sc_inline.group(2).upper()
            rest = m_sc_inline.group(3)
            location = _strip_tp_location(ie + ' ' + rest)
            current_scene = {'id': uid(), 'sceneId': scene_id, 'set': location, 'desc': '', 'roles': []}
            scene_committed = False
            in_bg_col = in_bg_sec = False
            bg_x_start = bg_x_end = None
            bg_buf = []
            pending_location = ''
            print(f"    Scene {scene_id}: {location}")
            continue

        # ── Scene: standalone Sc. N (uses pending_location) ──────────────────
        m_sc = RE_TP_SC_ALONE.match(full)
        if m_sc:
            flush_bg()
            commit_scene()
            raw_id = m_sc.group(1).strip()
            # Clean up: "4, 6, 8" → "4,6,8"; strip trailing T/N indicator
            scene_id = re.sub(r'\s*,\s*', ',', raw_id).strip(',').strip()
            scene_id = re.sub(r'^(.*\w)\s+[TN]$', r'\1', scene_id)
            location = pending_location or 'TBD'
            current_scene = {'id': uid(), 'sceneId': scene_id, 'set': location, 'desc': '', 'roles': []}
            scene_committed = False
            in_bg_col = in_bg_sec = False
            bg_x_start = bg_x_end = None
            bg_buf = []
            pending_location = ''
            print(f"    Scene {scene_id}: {location}")
            continue

        # ── INT/EXT location line (may precede the Sc. line) ─────────────────
        m_loc = RE_TP_INTXT.match(full)
        if m_loc:
            pending_location = _strip_tp_location(full)
            in_bg_col = in_bg_sec = False
            bg_buf = []
            continue

        # ── Column header row: "Cast Background VFX" ─────────────────────────
        if texts and texts[0] == 'Cast':
            flush_bg()
            if 'Background' in texts:
                bg_word = next(w for w in ws if w['text'] == 'Background')
                bx = float(bg_word['x0'])
                others = [float(w['x0']) for w in ws if float(w['x0']) > bx + 10]
                bg_x_start = bx - 5
                bg_x_end = (min(others) - 5) if others else 9999.0
                in_bg_col = True
                in_bg_sec = False
            else:
                in_bg_col = False
                in_bg_sec = False
                bg_x_start = bg_x_end = None
            continue

        # ── Standalone "Background" section header ────────────────────────────
        if texts == ['Background'] or texts == ['Background', 'Actors']:
            flush_bg()
            in_bg_col = False
            in_bg_sec = True
            bg_x_start = 0.0
            bg_x_end = 9999.0
            continue
        # "Background" appearing mid-row (merged from adjacent column)
        if 'Background' in texts and texts[0] not in ('Cast', 'Background') and not in_bg_col:
            # Check if it looks like a standalone BG header mixed into another row
            bg_idx = texts.index('Background')
            if bg_idx >= len(texts) - 2:  # Background near end of row
                flush_bg()
                in_bg_col = False
                in_bg_sec = True
                bg_x_start = 0.0
                bg_x_end = 9999.0
                continue

        # ── BG Cast section (skip — these are named cast in BG, not extras) ──
        if full.strip() in ('BG Cast', 'BG DOD'):
            flush_bg()
            in_bg_col = False
            in_bg_sec = False
            continue

        # ── Non-BG section terminators ────────────────────────────────────────
        if texts and texts[0] in TP_NON_BG:
            flush_bg()
            in_bg_col = False
            in_bg_sec = False
            continue

        # ── BG column extraction ──────────────────────────────────────────────
        if in_bg_col and bg_x_start is not None and current_scene is not None:
            bg_words = [w['text'] for w in ws if bg_x_start <= float(w['x0']) < bg_x_end]
            if bg_words:
                chunk = ' '.join(bg_words)
                bg_buf.append(chunk)

        # ── Standalone BG section extraction ─────────────────────────────────
        elif in_bg_sec and current_scene is not None:
            line = full.strip()
            if not line or RE_PAGE_NOISE.match(line):
                pass
            elif re.match(r'^\d+\s+', line):
                # Count + description
                flush_bg()
                bg_buf.append(line)
                flush_bg()
            elif re.match(r'^[A-Z][A-Z0-9 \-/\(\)]+$', line) and len(line.split()) >= 2:
                # All-caps label
                current_scene['roles'].append(make_role(1, line))
            else:
                in_bg_sec = False

    # Finalize: collect any scenes after the last END OF DAY marker
    commit_scene()
    if pending_scenes:
        # Schedule had no final END OF DAY marker — collect remaining scenes
        d = {
            'id': uid(), 'dayNumber': (days[-1]['dayNumber'] + 1) if days else 1,
            'date': '', 'scenes': list(pending_scenes),
            'standinOff': {}, 'standinHours': {}
        }
        pending_scenes.clear()
        days.append(d)

    return days, show_name, episode

# ══════════════════════════════════════════════════════════════════════════════
# OCR FALLBACK — for PDFs with text rendered as vector paths
# ══════════════════════════════════════════════════════════════════════════════

RE_SCENE_OCR = re.compile(
    r'^Scene\s*#\s*(\S+)\s+(INT/EXT|INT|EXT)\s+(.+)',
    re.I
)

def _ocr_available():
    try:
        from pdf2image import convert_from_path  # noqa
        import pytesseract                        # noqa
        return True
    except ImportError:
        return False


def extract_text_via_ocr(pdf_path, dpi=150):
    """Rasterise PDF pages and OCR them. Returns list of page text strings or None."""
    try:
        from pdf2image import convert_from_path
        import pytesseract
        print("  Using OCR fallback (pdf has path-rendered text) …")
        images = convert_from_path(pdf_path, dpi=dpi)
        texts = []
        for i, img in enumerate(images, 1):
            texts.append(pytesseract.image_to_string(img))
            if i % 10 == 0:
                print(f"  OCR: {i}/{len(images)} pages done")
        return texts
    except Exception as e:
        print(f"  OCR failed: {e}")
        return None


def parse_movie_magic_from_ocr(ocr_pages):
    """Parse Movie Magic schedule from OCR-extracted text lines."""
    all_lines = []
    for page_text in ocr_pages:
        for line in page_text.split('\n'):
            line = line.strip()
            if line:
                all_lines.append(line)

    days       = []
    current_day   = None
    current_scene = None
    in_bg_section = False
    show_name = ''
    episode   = ''

    # Grab show name / episode from opening lines
    SKIP_RE = re.compile(
        r'^(Shoot\s+Day|Scene\s*#|Shooting\s+Schedule|PRELIM|FINAL|BASED\s+ON|'
        r'Printed\s+on|Page\s+\d+|\*\*)',
        re.I
    )
    for line in all_lines[:30]:
        if SKIP_RE.match(line): continue
        ep_m = re.search(r'Ep#?\s*(\d{2,3})', line, re.I)
        if ep_m and not episode:
            episode = ep_m.group(1)
        if (not show_name and 6 < len(line) < 80
                and re.search(r'[A-Za-z]{4,}', line)
                and not RE_DATE_LINE.match(line)):
            show_name = line

    def commit_scene():
        if current_scene is not None and current_day is not None:
            current_day['scenes'].append(current_scene)

    for line in all_lines:
        # ── Day header ──────────────────────────────────────────────────────
        m = RE_SHOOT_DAY.match(line)
        if m:
            commit_scene()
            current_scene = None
            in_bg_section = False
            d = {
                'id': uid(), 'dayNumber': int(m.group(1)),
                'date': parse_date(m.group(2)), 'scenes': [],
                'standinOff': {}, 'standinHours': {}
            }
            days.append(d)
            current_day = d
            print(f"  Day {m.group(1)}: {parse_date(m.group(2)) or m.group(2)}")
            continue

        if RE_END_DAY.match(line):
            commit_scene()
            current_scene = None
            in_bg_section = False
            continue

        if current_day is None:
            continue

        # ── Noise ───────────────────────────────────────────────────────────
        if RE_PAGE_NOISE.match(line):
            continue

        # ── Scene header: "Scene# 115 EXT FARM - LATER DAY 3/8" ────────────
        m = RE_SCENE_OCR.match(line)
        if m:
            commit_scene()
            in_bg_section = False
            scene_id = m.group(1).strip().rstrip(',')
            ie       = m.group(2).upper()
            rest     = m.group(3).strip()
            # Strip trailing page-fraction "DAY 3/8", "DAY 3", or OCR artefact "DAY 38"
            rest = re.sub(r'\s+(?:DAY|NIGHT|D|N)\s+\d+(?:/\d+)?\s*$', '', rest, flags=re.I).strip()
            location = ie + ' ' + rest
            current_scene = {
                'id': uid(), 'sceneId': scene_id,
                'set': location, 'desc': '', 'roles': []
            }
            print(f"    Scene {scene_id}: {location}")
            continue

        # ── Section headers ─────────────────────────────────────────────────
        sl = line.lower()
        if any(sl == h.lower() or sl.startswith(h.lower() + ' ') for h in BG_HEADERS):
            in_bg_section = True
            continue
        if any(sl == h.lower() or sl.startswith(h.lower() + ' ') for h in NON_BG_HEADERS):
            in_bg_section = False
            continue

        # ── BG role lines ────────────────────────────────────────────────────
        if in_bg_section and current_scene is not None:
            # Merged two-column lines sometimes have a section header LATER in the line
            # (e.g. "2. Pedestrians 6.sleeping bag Set Dressing").
            # Parse any BG role from the START of the line first, then close section.
            non_bg_mid = re.search(
                r'\b(?:' + '|'.join(re.escape(h) for h in NON_BG_HEADERS) + r')\b',
                line, re.I
            )
            result = parse_bg_role_ocr(line)
            if result:
                count, desc = result
                current_scene['roles'].append(make_role(count, desc))
            if non_bg_mid:
                in_bg_section = False

    commit_scene()
    return days, show_name, episode


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY — auto-detect format
# ══════════════════════════════════════════════════════════════════════════════

def parse_shootsked(pdf_path):
    print(f"Opening: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        print(f"Pages: {len(pdf.pages)}")

        # Detect if PDF has path-rendered text (very low char density)
        sample_pages = pdf.pages[:min(5, len(pdf.pages))]
        avg_chars = sum(len(p.chars) for p in sample_pages) / len(sample_pages)
        print(f"Avg chars/page (sample): {avg_chars:.0f}")

        fmt = detect_format(pdf)
        print(f"Detected format: {fmt}")

        # OCR path: text baked as vectors — pdfplumber can't read it
        # Normal schedules have 800–2000 chars/page; path-rendered PDFs have <200
        if avg_chars < 200 and fmt == 'movie_magic':
            if not _ocr_available():
                raise RuntimeError(
                    "This PDF uses path-rendered text (non-selectable) and requires OCR to parse, "
                    "but OCR tools (tesseract / pdf2image) are not installed on this server.\n\n"
                    "To fix: re-export the schedule from your scheduling software as a standard PDF "
                    "(look for 'Export as PDF' rather than 'Print to PDF'), then try importing again."
                )
            ocr_pages = extract_text_via_ocr(pdf_path)
            if ocr_pages:
                days, show_name, episode = parse_movie_magic_from_ocr(ocr_pages)
            else:
                print("  OCR returned no pages — falling back to standard parse")
                days, show_name, episode = parse_movie_magic(pdf)
        elif fmt == 'tp_paper':
            days, show_name, episode = parse_tp_paper(pdf)
        elif fmt == 'ep_oneline':
            days, show_name, episode = parse_ep_oneline(pdf)
        else:
            days, show_name, episode = parse_movie_magic(pdf)

    # Summary
    print(f"\nParsed {len(days)} shooting days:")
    total_roles = 0
    for d in days:
        sc_c = len(d['scenes'])
        ro_c = sum(len(s['roles']) for s in d['scenes'])
        total_roles += ro_c
        print(f"  Day {d['dayNumber']} ({d['date'] or 'no date'}): {sc_c} scenes, {ro_c} BG roles")
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
