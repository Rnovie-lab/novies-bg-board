#!/usr/bin/env python3
"""
parse_shootsked.py  —  Universal Shooting Schedule PDF → BGBoard JSON
======================================================================

Architecture: classify → assemble  (no per-format parsers)
-----------------------------------------------------------
  1. Layout detection   — sequential text vs. columnar (Cast·BG·VFX side-by-side)
  2. Row extraction     — (structural_text, bg_text, x0) tuples per page row
  3. Row classification — each structural_text → semantic event type
  4. Assembly           — single state machine builds days / scenes / roles
  5. Output             — BGBoard-format JSON

Adding support for a new schedule software = add patterns to CLASSIFIERS,
not a new parser function.

Supported layouts
-----------------
  Sequential  —  Movie Magic Scheduling (standard + multi-episode D{N})
  Columnar    —  EP Scheduling / The Paper / any side-by-side Cast·BG·VFX

Usage
-----
    python3 parse_shootsked.py <schedule.pdf> [output.json]
"""

import sys
import json
import re
import uuid
from pathlib import Path
from collections import defaultdict

try:
    import pdfplumber
except ImportError:
    print("Error: pdfplumber not installed. Run: pip install pdfplumber")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# TERMINOLOGY LOADER
# Merges bg_terminology.json (editable without code changes) with built-in sets.
# ═══════════════════════════════════════════════════════════════════════════════

def _load_terminology():
    """
    Load bg_terminology.json from the same directory as this script.
    Returns (bg_extra, skip_extra, day_start_extra, day_end_extra) where each
    is a list of additional terms / (pattern, extractor) tuples to merge into
    the classifier.  Silently returns empty lists if the file is missing.
    """
    term_path = Path(__file__).parent / 'bg_terminology.json'
    if not term_path.exists():
        return [], [], [], []

    try:
        with open(term_path) as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [terminology] Warning: could not load bg_terminology.json — {e}")
        return [], [], [], []

    bg_extra   = [t.strip().lower() for t in data.get('bg_section', {}).get('terms', [])]
    skip_extra = [t.strip().lower() for t in data.get('skip_section', {}).get('terms', [])]

    def _phrase_to_pattern(phrase, kind):
        """Convert a '{N}' / '{REST}' template string to a (regex, extractor) tuple."""
        escaped = re.escape(phrase)
        # Allow optional "#" before the day number (e.g. "Photography Day # 4")
        escaped = escaped.replace(r'\{N\}',    r'(?:#\s*)?(\d+)')
        escaped = escaped.replace(r'\{REST\}', r'(.*)')
        pat = re.compile(r'^' + escaped + r'\s*(.*)', re.I)
        if kind == 'start':
            # Group 1 = day number, group 2 = rest (date text or trailing)
            return (pat, lambda m: {
                'day': int(m.group(1)),
                'date_text': (m.group(2) if m.lastindex >= 2 else '').strip()
            })
        else:
            return (pat, lambda m: {
                'day': int(m.group(1)),
                'date_text': (m.group(2) if m.lastindex >= 2 else '').strip()
            })

    day_start_extra = []
    for phrase in data.get('day_start_phrases', {}).get('phrases', []):
        try:
            day_start_extra.append(_phrase_to_pattern(phrase, 'start'))
        except Exception:
            pass

    day_end_extra = []
    for phrase in data.get('day_end_phrases', {}).get('phrases', []):
        try:
            day_end_extra.append(_phrase_to_pattern(phrase, 'end'))
        except Exception:
            pass

    return bg_extra, skip_extra, day_start_extra, day_end_extra


_TERMINOLOGY = _load_terminology()


# ─── utilities ───────────────────────────────────────────────────────────────

def uid():
    return str(uuid.uuid4())[:8]

MONTHS = {
    'january':'01','february':'02','march':'03','april':'04',
    'may':'05','june':'06','july':'07','august':'08',
    'september':'09','october':'10','november':'11','december':'12'
}

def parse_date(text):
    """Extract YYYY-MM-DD from 'Monday, October 27, 2025' or 'April 23, 2025'."""
    try:
        m = re.search(r'(\w+)\s+(\d{1,2}),\s+(\d{4})', text or '', re.I)
        if m:
            month = MONTHS.get(m.group(1).lower(), '00')
            return f"{m.group(3)}-{month}-{m.group(2).zfill(2)}"
    except Exception:
        pass
    return ''

def make_role(count, desc):
    return {
        'id': uid(), 'type': desc, 'count': int(count),
        'tier': 'sag', 'baseRate': 182, 'hours': 8,
        'bumps': [], 'notes': '', 'minors': False
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ROW CLASSIFIER
# Each pattern list is tried in order; first match wins.
# ═══════════════════════════════════════════════════════════════════════════════

# ── day boundaries ───────────────────────────────────────────────────────────

DAY_START_PATTERNS = [
    # "Shoot Day # 4   Monday, October 7, 2025"
    (re.compile(r'^Shoot\s+Day\s+#\s*(\d+)\s*(.*)', re.I),
     lambda m: {'day': int(m.group(1)), 'date_text': m.group(2).strip()}),
    # "D4 - Monday" or "D 4 – Tuesday May 6"
    (re.compile(r'^D\s*(\d+)\s*[-–]\s*(.*)', re.I),
     lambda m: {'day': int(m.group(1)), 'date_text': m.group(2).strip()}),
    # "Day 4 of 10" or "Day 4"
    (re.compile(r'^Day\s+(\d+)(?:\s+of\s+\d+)?\s*[-–]?\s*(.*)', re.I),
     lambda m: {'day': int(m.group(1)), 'date_text': m.group(2).strip()}),
    # Extended from bg_terminology.json at load time (see below)
]

DAY_END_PATTERNS = [
    # "End Day # 4 ..."  (Movie Magic)
    (re.compile(r'^End\s+Day\s+#\s*(\d+)', re.I),
     lambda m: {'day': int(m.group(1)), 'date_text': ''}),
    # "END OF DAY 4-- Monday, April 21, 2026"  (EP Scheduling / The Paper)
    (re.compile(r'^END\s+OF\s+DAY\s+(\d+)--\s*(.*)', re.I),
     lambda m: {'day': int(m.group(1)), 'date_text': m.group(2).strip()}),
    # "End of DAY 4 Wednesday April 23, 2025"  (EP one-line)
    (re.compile(r'^End\s+of\s+DAY\s+(\d+)\s+(.*)', re.I),
     lambda m: {'day': int(m.group(1)), 'date_text': m.group(2).strip()}),
    # "End of Shoot Day" / "End of Day" (generic)
    (re.compile(r'^End\s+(?:of\s+)?(?:Shoot\s+)?Day\b', re.I),
     lambda m: {'day': None, 'date_text': ''}),
    # Extended from bg_terminology.json at load time (see below)
]

# ── scene headers ─────────────────────────────────────────────────────────────

SCENE_PATTERNS = [
    # "Scene # 27pt,28" or "Scene# 115" (OCR drops the space) or "Scene # A-27"
    (re.compile(r'^Scene\s*#?\s*([^,\s#][^\n]{0,50})', re.I),
     lambda m: {'scene_id': _clean_scene_id(m.group(1)), 'intex': '', 'location': ''}),
    # "Sc. 27pt  INT  OFFICE DAY"  or  "Sc. A25 EXT PARK"  (EP / The Paper)
    (re.compile(r'^Sc\.\s+([\w,\.]+(?:pt|vo)?)\s+(INT/EXT|INT|EXT)\s+(.*)', re.I),
     lambda m: {'scene_id': m.group(1).strip(),
                'intex': m.group(2).upper(),
                'location': _strip_tp_location(m.group(3))}),
    # "Sc. 27pt" alone (location on next line)
    (re.compile(r'^Sc\.\s+([\w,\.]+(?:pt|vo)?)\s*$', re.I),
     lambda m: {'scene_id': m.group(1).strip(), 'intex': '', 'location': ''}),
    # EP one-line: "309 Sc 27 INT LOBBY D1 ..." — three-number episode prefix
    (re.compile(r'^\d{2,3}\s+Sc\s+(\S+)\s+(INT/EXT|INT|EXT)\s+(.+?)\s+[DN]\d', re.I),
     lambda m: {'scene_id': m.group(1).strip(),
                'intex': m.group(2).upper(),
                'location': m.group(3).strip()}),
]

# ── INT/EXT slug lines ────────────────────────────────────────────────────────

INTEX_PATTERN = re.compile(r'^(INT/EXT|INT|EXT)\s+(.*)', re.I)

# ── section markers ───────────────────────────────────────────────────────────
# Built-in terms are merged with bg_terminology.json at module load time.
# To add a new term without editing this file: add it to bg_terminology.json.

_BG_BUILTIN = {
    'background actors', 'background actor', 'background', 'extras', 'extra',
    'bg extras', 'bg actor', 'bg actors',
}

_SKIP_BUILTIN = {
    'cast members', 'cast', 'special equipment', 'props', 'set dressing',
    'vehicles', 'picture cars', 'art department', 'special effects', 'music',
    'hair/makeup', 'makeup/hair', 'wardrobe', 'animals', 'notes', 'stunts',
    'mechanical effects', 'sound', 'camera', 'electric', 'grip',
    'location notes', 'production', 'miscellaneous', 'additional labor',
    'animal wrangler', 'animal wranglers', 'safety bulletins', 'visual effects',
    'synopsis', 'intimacy coordinator', 'vfx',
    # EP Scheduling: named BG cast vs. hired extras
    'bg cast', 'bg dod', 'bg day players',
}

# Merge terminology file additions into live sets
_bg_extra, _skip_extra, _day_start_extra, _day_end_extra = _TERMINOLOGY

BG_SECTION_WORDS   = frozenset(_BG_BUILTIN   | set(_bg_extra))
SKIP_SECTION_WORDS = frozenset(_SKIP_BUILTIN | set(_skip_extra))

# Extend day-boundary pattern lists with any phrases from terminology file
DAY_START_PATTERNS.extend(_day_start_extra)
DAY_END_PATTERNS.extend(_day_end_extra)

if _bg_extra or _skip_extra or _day_start_extra or _day_end_extra:
    print(f"  [terminology] Loaded: +{len(_bg_extra)} BG terms, "
          f"+{len(_skip_extra)} skip terms, "
          f"+{len(_day_start_extra)} day-start phrases, "
          f"+{len(_day_end_extra)} day-end phrases")

# ── noise / skip lines ────────────────────────────────────────────────────────

NOISE_RE = re.compile(
    r'^(Page\s+\d+|Printed\s+on\s|Day\s+Out\s+Of|DOOD|Total\s+Pages|'
    r'Revision\s|Revised\s|REVISED\s|Locked\s|LOCKED\s|'
    r'Previously\s+Shot|Scene\s+Count|Shooting\s+Schedule)',
    re.I
)
PAGE_NUM_RE = re.compile(r'^\d{1,3}$')
NOTE_RE = re.compile(
    # "shoot\s" intentionally excluded — "Shoot Day #" must reach day-start patterns
    r'^(roll\s|move\s|see\s|note[:\s]|show\s|per\s|ot\s|tbd|'
    r'practical\s|table\s+read|lunch|wrap|company\s|pre.rig)',
    re.I
)
CAST_RE  = re.compile(r'^\d+\.\s*[A-Z]')   # "4. BRUCE", "4.BRUCE"
SLUG_RE  = re.compile(r'^(INT|EXT|INT/EXT)\s*[\./\-\s]', re.I)

# ── BG role patterns ─────────────────────────────────────────────────────────

BG_COUNT_RE   = re.compile(r'^(\d+)\s+(.+)$')
BG_LABEL_RE   = re.compile(r'^BG\s+\w', re.I)
BG_ALLCAPS_RE = re.compile(r'^[A-Z][A-Z0-9 \-/\(\)\'\.\_]+$')

# Strip section-header words merged from adjacent column
SECTION_STRIP_RE = re.compile(
    r'\s+(?:Wardrobe|Makeup|Art\s+Dept|Set\s+Dress|Special\s+(?:Effects|Equipment)|'
    r'Animal\s+Wrangler|Sound|Camera|Electric|Grip|Vehicles?|Stunts?|'
    r'Production|Notes?|Synopsis|Safety|Intimacy|Visual\s+Effects?|VFX)\b.*',
    re.I
)
# Strip mid-line prop numbers ("6.sleeping bag")
MID_PROP_RE = re.compile(r'\s+\d+\.\S')

# Strip trailing prop items leaked from the Props column in OCR schedules.
# Handles: "8 ND Oracle Employees Phones" → "8 ND Oracle Employees"
#          "10 X Overseas Oracle Oracle Badges" → "10 X Overseas Oracle"
#          "2 SECURITY GUARDS Phones" → "2 SECURITY GUARDS"
#
# NOTE: do NOT use re.I here — we rely on [A-Z][a-z] being case-sensitive so
# that mixed-case modifier words ("Oracle") are consumed but ALL-CAPS role
# words ("GUARDS") are not.
_PROP_NOUNS = (
    r'[Pp]hone|[Ll]aptop|[Bb]adge|[Cc]amera|[Rr]adio|[Tt]ablet|[Mm]onitor|'
    r'[Cc]ard|[Pp]aper|[Bb]ag|[Bb]ox|[Ff]ile|[Rr]ecorder|[Ww]atch|[Gg]lasses|'
    r'[Ww]allet|[Kk]ey|[Pp]rop|[Ss]ign|[Nn]ote|[Bb]ook|[Pp]en|[Mm]arker|'
    r'[Ff]older|[Bb]inder|[Hh]eadset|[Ee]arpiece|[Cc]lipboard|[Ll]anyard|'
    r'[Cc]able|[Pp]oster|[Bb]anner|[Ff]rame|[Bb]ottle|[Gg]lass|[Cc]up|'
    r'[Mm]ug|[Pp]late|[Bb]owl|[Tt]ray|[Bb]ackpack|[Bb]riefcase|[Pp]urse|'
    r'[Hh]at|[Jj]acket|[Cc]oat|[Ss]hirt|[Ss]uit|[Tt]ie|[Ss]carf|ID'
)
OCR_TRAILING_PROPS_RE = re.compile(
    r'\s+(?:[A-Z][a-z]\w*\'?s?\s+)?'   # optional mixed-case word (e.g. "Oracle ") — NOT all-caps
    r'(?:' + _PROP_NOUNS + r')s?\s*$'
)
# "Stack of Children's books", "Stack of papers" etc.
OCR_STACK_PROPS_RE = re.compile(r'\s+Stack\s+of\b.*$', re.I)

# Reject all-caps strings that are location/directional notes or object props,
# not BG roles. OCR sometimes picks these up from art dept notes under the BG section.
LOCATION_NOTE_RE = re.compile(
    r'\b(?:NORTH|SOUTH|EAST|WEST|NW|NE|SW|SE|SIDE|FLOOR|CUBICLE|HALLWAY|'
    r'LOBBY|STAIRW?|ENTRANCE|EXIT|CORRIDOR|BUILDING|SECTION|CORNER|LEVEL|'
    r'WING|BAY|DOCK|PLATFORM|ZONE|STAGE|DECK|AISLE|ROW|'
    r'WINDOW|DOOR|WALL|CEILING|SCREEN|BACKDROP|PLEXIGLASS|GLASS|MIRROR|'
    r'TABLE|CHAIR|DESK|COUCH|SOFA|SHELF|CABINET|COUNTER|PODIUM|RAILING)\b'
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _clean_scene_id(raw):
    s = raw.strip().rstrip(',').strip()
    # Strip trailing INT/EXT + location: "509 INT FLAMINGO" → "509"
    s = re.sub(r'\s+(INT/EXT|INT|EXT)\b.*$', '', s, flags=re.I).strip()
    # If the entire string IS an INT/EXT location (no scene number prefix),
    # the "Scene #" line had no actual number — return empty so it's ignored.
    if re.match(r'^(INT/EXT|INT|EXT)\b', s, re.I):
        return ''
    return s

def _strip_tp_location(raw):
    """Strip page counts, day indicators, stage info from TP/EP location strings."""
    s = raw.strip()
    s = re.sub(r'\s+(?:DAY\s+)?[DN]\d+\s+.*$', '', s, flags=re.I).strip()
    s = re.sub(r'\s+(?:DAY|NIGHT|NIGH)\s*$', '', s, flags=re.I).strip()
    s = re.sub(r'\s+\d+(?:\s+\d+/\d+|/\d+)?\s*pg.*$', '', s, flags=re.I).strip()
    s = re.sub(r'\s+Stage\s+\d+.*$', '', s, flags=re.I).strip()
    return s


def classify_row(text):
    """
    Classify a single structural text row.

    Returns (event_type, data) where event_type is one of:
      day_start | day_end | scene | intex | bg_section | skip_section
      cast | noise | content

    'content' rows are BG role candidates when inside a bg_section.
    """
    s = (text or '').strip()
    if not s:
        return ('empty', {})

    # Day / scene patterns checked FIRST — structural events must never be
    # suppressed by noise filters (e.g. "Shoot Day #" starts with "Shoot")
    for pat, extractor in DAY_START_PATTERNS:
        m = pat.match(s)
        if m:
            return ('day_start', extractor(m))

    for pat, extractor in DAY_END_PATTERNS:
        m = pat.match(s)
        if m:
            return ('day_end', extractor(m))

    # Scene headers
    for pat, extractor in SCENE_PATTERNS:
        m = pat.match(s)
        if m:
            return ('scene', extractor(m))

    # Noise / page furniture (after structural checks)
    if NOISE_RE.match(s) or PAGE_NUM_RE.match(s) or NOTE_RE.match(s):
        return ('noise', {})

    # INT/EXT slug (location line)
    m = INTEX_PATTERN.match(s)
    if m:
        loc = _strip_tp_location(m.group(2))
        return ('intex', {'intex': m.group(1).upper(), 'location': loc})

    # Section markers — normalise to lowercase for lookup
    sl = s.lower().rstrip(':').strip()

    if sl in BG_SECTION_WORDS:
        return ('bg_section', {})
    if sl in SKIP_SECTION_WORDS:
        return ('skip_section', {'name': sl})

    # Prefix match (handles merged column text like "Background wardrobe note")
    for w in BG_SECTION_WORDS:
        if sl.startswith(w + ' '):
            return ('bg_section', {})

    # Compound header check: some scheduling apps put ALL section names on one
    # line ("Cast Background Actors Props", "Cast Background Actors Wardrobe").
    # If ANY BG section word appears as a whole word, treat the row as bg_section
    # so that subsequent content rows are scanned for BG roles.
    # This check MUST come before skip-section prefix matching.
    for w in BG_SECTION_WORDS:
        m2 = re.search(r'\b' + re.escape(w) + r'\b', sl)
        if m2:
            # Exclude art dept notes like "Background/ Backdrop for Eric"
            # where the BG word is followed by "/" or "for" (not a section header)
            after = sl[m2.end():].strip()
            if after.startswith('/') or re.match(r'^for\b', after, re.I):
                continue
            return ('bg_section', {})

    for w in SKIP_SECTION_WORDS:
        if sl.startswith(w + ' '):
            return ('skip_section', {'name': w})

    # Cast entries
    if CAST_RE.match(s):
        return ('cast', {})

    # Everything else is content (may be a BG role, checked in assembler)
    return ('content', {'text': s})


def parse_bg_role(text):
    """
    Try to extract (count, description) from a BG role text fragment.
    Returns (count, desc) or None.
    """
    s = (text or '').strip()
    if not s or len(s) < 2:
        return None
    if NOISE_RE.match(s) or NOTE_RE.match(s) or CAST_RE.match(s):
        return None

    # Strip section-header words and prop numbers leaked from adjacent columns
    clean = SECTION_STRIP_RE.sub('', s).strip()
    clean = MID_PROP_RE.split(clean)[0].strip()

    # Strip trailing prop items that OCR bleeds in from the Props column
    # e.g. "8 ND Oracle Employees Phones" → "8 ND Oracle Employees"
    clean = OCR_TRAILING_PROPS_RE.sub('', clean).strip()
    clean = OCR_STACK_PROPS_RE.sub('', clean).strip()

    # Strip trailing punctuation left by OCR noise
    clean = clean.rstrip('.,;:').strip()

    if not clean or len(clean) < 2:
        return None

    # "12 Office Workers" / "BG crowd" / "9 softees"
    m = BG_COUNT_RE.match(clean)
    if m:
        count = int(m.group(1))
        desc  = m.group(2).strip()
        # Strip trailing props again after extracting desc
        desc = OCR_TRAILING_PROPS_RE.sub('', desc).strip().rstrip('.,;:').strip()
        if not desc or len(desc) < 2:
            return None
        # Reject narrative fragments that leaked from synopsis
        if re.match(r'^(He|She|They|It|We|His|Her|Their|The\s+\w+\s+(takes|sits|walks))\b',
                    desc, re.I):
            return None
        if len(desc) > 60 and re.search(
                r'\b(takes|sits|stands|walks|runs|into|last|sip|drink)\b', desc, re.I):
            return None
        return (count, desc)

    # "BG Pool Goers" / "BG w/ cars"
    if BG_LABEL_RE.match(clean) and len(clean) > 4:
        return (1, clean)

    # ALL-CAPS multi-word descriptions: "BALLOON DELIVERY PERSON", "SOFTEE WORKER"
    # But reject location/directional notes that OCR picks up from art dept blocks
    if (BG_ALLCAPS_RE.match(clean)
            and len(clean.split()) >= 2
            and 4 < len(clean) <= 80
            and not CAST_RE.match(clean)
            and not LOCATION_NOTE_RE.search(clean)):
        return (1, clean)

    # Named BG performer — single all-caps name, e.g. "JAY", "MIKE"
    # Appears as a standalone line under Background Actors in OCR schedules
    _RESERVED = {'BG', 'NU', 'SAG', 'SI', 'EXT', 'INT', 'VFX', 'SFX', 'SC',
                 'EP', 'FX', 'AD', 'PA', 'DP', 'DOP', 'UPM', 'LP', 'AM'}
    if (re.match(r'^[A-Z]{2,15}$', clean)
            and clean not in _RESERVED):
        return (1, clean)

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# LAYOUT DETECTION & ROW EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

def detect_column_layout(pages, sample_n=8):
    """
    Scan first sample_n pages for a row containing 'Cast' and 'Background'
    as adjacent column headers (EP Scheduling / The Paper layout).

    Returns {'background': (x_start, x_end)} or None for sequential layout.
    """
    bg_header_re = re.compile(r'^Background$', re.I)
    cast_header_re = re.compile(r'^Cast$', re.I)
    vfx_header_re  = re.compile(r'^(VFX|Visual\s+Effects?)$', re.I)

    for page in pages[:sample_n]:
        try:
            words = page.extract_words(x_tolerance=4, y_tolerance=3)
        except Exception:
            continue

        by_y = defaultdict(list)
        for w in words:
            by_y[round(float(w['top']) / 2) * 2].append(w)

        for y, row_words in sorted(by_y.items()):
            row_words = sorted(row_words, key=lambda w: float(w['x0']))
            texts = [w['text'].strip() for w in row_words]

            has_cast = any(cast_header_re.match(t) for t in texts)
            has_bg   = any(bg_header_re.match(t) for t in texts)
            if not (has_cast and has_bg):
                continue

            # Found a column-header row — extract BG column x-range
            bg_words = [w for w in row_words if bg_header_re.match(w['text'].strip())]
            vfx_words = [w for w in row_words if vfx_header_re.match(w['text'].strip())]

            if not bg_words:
                continue

            bg_x0 = float(bg_words[0]['x0']) - 5
            if vfx_words:
                bg_x1 = float(vfx_words[0]['x0']) - 5
            else:
                bg_x1 = bg_x0 + 180  # generous default

            # Sanity check: BG column must start well to the right of the
            # left margin (x > 100) so we don't mistake left-side section
            # headers for column headers.
            if bg_x0 < 100:
                continue

            return {'background': (bg_x0, bg_x1)}

    return None  # sequential layout


def _words_to_rows(words):
    """Group pdfplumber word dicts by y-position into sorted rows."""
    by_y = defaultdict(list)
    for w in words:
        by_y[round(float(w['top']) / 3) * 3].append(w)
    result = []
    for y in sorted(by_y.keys()):
        result.append(sorted(by_y[y], key=lambda w: float(w['x0'])))
    return result


def extract_rows_sequential(page):
    """
    Extract (left_text, full_text) pairs from a sequential-layout page.
    Left column (x < 310) drives classification; full_text used for metadata.
    """
    try:
        words = page.extract_words(x_tolerance=4, y_tolerance=4)
    except Exception:
        return []
    rows = _words_to_rows(words)
    result = []
    for row_words in rows:
        left  = ' '.join(w['text'] for w in row_words if float(w['x0']) < 310).strip()
        full  = ' '.join(w['text'] for w in row_words).strip()
        if full:
            result.append((left, full))
    return result


def extract_rows_columnar(page, bg_x0, bg_x1):
    """
    Extract (left_text, bg_text, full_row_text) triples from a columnar page.

      left_text    — words at x < bg_x0 (structural: day/scene headers, cast)
      bg_text      — words at bg_x0 <= x < bg_x1 (BG role content)
      full_row_text — all words on the row (used for structural classification
                     when markers like END OF DAY span past bg_x1)
    """
    try:
        words = page.extract_words(x_tolerance=4, y_tolerance=3)
    except Exception:
        return []
    rows = _words_to_rows(words)
    result = []
    for row_words in rows:
        if not row_words:
            continue
        full = ' '.join(w['text'] for w in row_words).strip()
        left = ' '.join(
            w['text'] for w in row_words if float(w['x0']) < bg_x0
        ).strip()
        bg = ' '.join(
            w['text'] for w in row_words if bg_x0 <= float(w['x0']) < bg_x1
        ).strip()
        if full:
            result.append((left, bg, full))
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULE ASSEMBLER
# ═══════════════════════════════════════════════════════════════════════════════

SHOW_SKIP_RE = re.compile(
    r'^(Shooting\s+Schedule|WHITE\s+SHOOTING|DIRECTOR|Episode\s+#|1st\s+AD|'
    r'Created\s+by|Based\s+on|Prepared\s+by)',
    re.I
)


def _extract_show_meta(text):
    """Try to pull episode number from an arbitrary text string."""
    m = re.search(r'\bEp(?:isode)?\s*[#:]?\s*(\d{2,3})\b', text, re.I)
    if m:
        return m.group(1)
    m = re.search(r'\b(\d{3})\b', text)   # bare 3-digit number is likely episode
    if m:
        return m.group(1)
    return None


def assemble_schedule(rows, column_mode=False):
    """
    Walk (structural_text, aux_text) row pairs and build schedule.

    column_mode=True : aux_text is BG column content (used for roles directly)
    column_mode=False: aux_text is full row text (used for metadata only)

    Returns (days, show_name, episode).
    """
    days         = []
    current_day  = None
    current_scene = None
    pending_scenes = []
    scene_committed = False
    in_bg        = False        # inside a BG section (sequential mode)
    page_header_fingerprint = set()  # suppress repeated page headers

    # --- helpers ---

    def make_day_obj(day_number, date_text=''):
        return {
            'id': uid(), 'dayNumber': day_number,
            'date': parse_date(date_text), 'scenes': [],
            'standinOff': {}, 'standinHours': {}
        }

    def commit_scene():
        nonlocal scene_committed
        if current_scene is not None and not scene_committed:
            pending_scenes.append(current_scene)
            scene_committed = True

    def flush_day_end():
        nonlocal current_day, pending_scenes, current_scene, scene_committed, in_bg
        commit_scene()
        if current_day is not None:
            current_day['scenes'] = list(pending_scenes)
            days.append(current_day)
        pending_scenes.clear()
        current_day   = None
        current_scene = None
        scene_committed = False
        in_bg = False

    def flush_day_start(day_number, date_text):
        nonlocal current_day, pending_scenes, current_scene, scene_committed, in_bg
        commit_scene()
        if current_day is not None:
            current_day['scenes'] = list(pending_scenes)
            days.append(current_day)
        pending_scenes.clear()
        current_scene = None
        scene_committed = False
        in_bg = False
        current_day = make_day_obj(day_number, date_text)

    # --- show metadata accumulation ---
    show_name = ''
    episode   = ''
    meta_rows_seen = 0

    # Build page-header fingerprint from first 10 structural rows
    for row in rows[:10]:
        left = row[0]
        if left.strip():
            page_header_fingerprint.add(left.strip())

    STRUCTURAL_TYPES = frozenset({
        'day_start','day_end','scene','intex','bg_section','skip_section','cast','noise'
    })
    # BG column words that are structural labels, not role text
    BG_STRUCTURAL_WORDS = frozenset({
        'background','cast','vfx','extras','spfx','props','wardrobe','vehicles',
        'set','lighting','camera','costumes','misc','sound','electric','grip',
        'practical','notes','questions','comments','visual','effects',
    })

    # --- main loop ---
    for row in rows:
        if column_mode:
            # 3-tuple from extract_rows_columnar: (left_text, bg_text, full_row_text)
            left, aux, full_row = row
        else:
            # 2-tuple from extract_rows_sequential: (left_text, full_text)
            left, aux = row
            full_row = aux   # in sequential mode full_row == full_text

        s = left.strip()

        if column_mode:
            # Use full_row (all words on the physical row, including text past bg_x1)
            # for structural classification. This ensures "END OF DAY 1-- Monday,
            # March 23, 2026" is captured in full even when the date words appear
            # past bg_x1. Day headers that appear mid-page (inside the BG column
            # range) are also captured via full_row.
            evt_type_full, evt_data_full = classify_row(full_row)
            if evt_type_full in STRUCTURAL_TYPES:
                evt_type, evt_data = evt_type_full, evt_data_full
            else:
                evt_type, evt_data = classify_row(s)
            # Always attach bg_text so the content handler can extract roles
            evt_data['bg_text'] = aux
        else:
            evt_type, evt_data = classify_row(s)
            # Sequential mode: some schedulers put dates in the right column
            # (past x=310). If a day_end or day_start lacks a date, try the
            # full row text.
            if evt_type in ('day_end', 'day_start') and not evt_data.get('date_text'):
                _, full_data = classify_row(full_row)
                if full_data.get('date_text'):
                    evt_data['date_text'] = full_data['date_text']

        # Accumulate show metadata from early content rows
        if meta_rows_seen < 20 and evt_type in ('content', 'noise'):
            text = evt_data.get('text', s) or aux
            ep = _extract_show_meta(text)
            if ep and not episode:
                episode = ep
            if (not show_name and len(text) > 6
                    and not NOISE_RE.match(text)
                    and not SHOW_SKIP_RE.match(text)
                    and not re.match(r'^\w+\s+\d{1,2},\s+\d{4}$', text, re.I)
                    and re.search(r'[A-Za-z]{3,}', text)):
                show_name = text
            meta_rows_seen += 1

        # ── structural events ────────────────────────────────────────────────

        if evt_type == 'day_start':
            flush_day_start(evt_data['day'], evt_data.get('date_text', ''))

        elif evt_type == 'day_end':
            day_num  = evt_data.get('day')
            date_txt = evt_data.get('date_text', '')
            if current_day is None:
                # 1-Line schedules: day_end is the ONLY day boundary marker.
                # Create the day retroactively so pending_scenes get committed.
                day_n = day_num or (len(days) + 1)
                current_day = make_day_obj(day_n, date_txt)
            else:
                if date_txt:
                    current_day['date'] = parse_date(date_txt)
            flush_day_end()

        elif evt_type == 'scene':
            # Allow scenes before the first day_start — 1-Line schedules use only
            # day_end markers so we must accumulate scenes from the beginning.
            # Any stray pre-day scenes in MM format are harmlessly discarded when
            # flush_day_start() clears pending_scenes.
            # Skip scenes with no usable scene ID (e.g. OCR noise / location-only lines)
            if not evt_data.get('scene_id', '').strip():
                continue
            commit_scene()
            loc = evt_data.get('location', '')
            intex = evt_data.get('intex', '')
            set_str = f"{intex} {loc}".strip() if intex and loc else (loc or intex or '')
            current_scene = {
                'id': uid(),
                'sceneId': evt_data['scene_id'],
                'set': set_str,
                'desc': '',
                'roles': []
            }
            scene_committed = False
            in_bg = False

        elif evt_type == 'intex':
            # Location line following a bare "Sc. N" header
            if current_scene is not None and not current_scene['set']:
                current_scene['set'] = f"{evt_data['intex']} {evt_data['location']}".strip()

        elif evt_type == 'bg_section':
            in_bg = True

        elif evt_type == 'skip_section':
            in_bg = False

        elif evt_type in ('cast', 'noise', 'empty'):
            pass  # ignore

        elif evt_type == 'content':
            if not column_mode:
                # Sequential mode: content is a BG role candidate only inside bg section
                if in_bg and current_scene is not None:
                    if s not in page_header_fingerprint:
                        role = parse_bg_role(s)
                        if role:
                            current_scene['roles'].append(make_role(*role))

        # ── Column mode BG extraction (all event types) ──────────────────────
        # In columnar PDFs, BG roles appear in the BG column regardless of what
        # the left-side structural text says. Try role extraction on every row
        # that has BG column content when we're inside a scene.
        if column_mode and current_scene is not None:
            bg_text = evt_data.get('bg_text', '').strip()
            if bg_text and bg_text.lower() not in BG_STRUCTURAL_WORDS:
                # Don't double-count if the full combined text already classified
                # as a structural event (day_start etc.) — those rows have no roles
                if evt_type not in ('day_start', 'day_end', 'scene', 'intex'):
                    role = parse_bg_role(bg_text)
                    if role:
                        current_scene['roles'].append(make_role(*role))

    # Flush any remaining open day
    if current_day is not None:
        commit_scene()
        current_day['scenes'] = list(pending_scenes)
        days.append(current_day)
    elif pending_scenes:
        # Orphaned scenes at end of file (pickup days, photo unit, etc.)
        # that follow the last day_end without a new day_start.
        # Assign the next sequential day number rather than a confusing "Day 1".
        stub = make_day_obj(len(days) + 1)
        stub['scenes'] = list(pending_scenes)
        days.append(stub)

    return days, show_name, episode


# ═══════════════════════════════════════════════════════════════════════════════
# OCR FALLBACK
# ═══════════════════════════════════════════════════════════════════════════════

def _ocr_available():
    try:
        import importlib
        importlib.import_module('pdf2image')
        import subprocess
        subprocess.run(['tesseract', '--version'], capture_output=True, check=True)
        return True
    except Exception:
        return False


def _ocr_page(args):
    """OCR a single PIL image (used with multiprocessing pool)."""
    img, page_num = args
    import subprocess, tempfile, os
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        tmp = f.name
    try:
        img.save(tmp)
        result = subprocess.run(
            ['tesseract', tmp, 'stdout', '-l', 'eng', '--oem', '1', '--psm', '6'],
            capture_output=True, text=True, timeout=60
        )
        return page_num, result.stdout
    finally:
        os.unlink(tmp)


def _ocr_pages(pdf_path):
    """Return list of page text strings via OCR (tesseract), parallelised."""
    from pdf2image import convert_from_path
    import subprocess, tempfile, os
    from concurrent.futures import ThreadPoolExecutor, as_completed

    images = convert_from_path(str(pdf_path), dpi=200)
    n = len(images)
    print(f"  OCR: {n} pages — running {'parallel' if n > 1 else 'single'} ({min(n, 4)} workers)")

    # Run up to 4 pages in parallel — sweet spot for tesseract on Railway/local
    max_workers = min(n, 4)
    results = [None] * n

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_ocr_page, (img, i)): i for i, img in enumerate(images)}
        for fut in as_completed(futures):
            page_num, text = fut.result()
            results[page_num] = text
            print(f"  OCR: page {page_num + 1}/{n} done")

    return results


def parse_from_ocr(ocr_pages):
    """
    Parse a list of OCR page strings using the universal assembler
    (sequential mode, since OCR gives plain text).
    """
    rows = []
    for page_text in ocr_pages:
        for line in page_text.splitlines():
            s = line.strip()
            if s:
                rows.append((s, s))   # left == full for OCR
    return assemble_schedule(rows, column_mode=False)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PARSE ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def parse_shootsked(pdf_path):
    print(f"Opening: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        print(f"Pages: {n_pages}")

        # Estimate text density
        sample_pages = pdf.pages[:min(5, n_pages)]
        avg_chars = sum(len(p.chars) for p in sample_pages) / len(sample_pages)
        print(f"Avg chars/page (sample): {avg_chars:.0f}")

        # OCR path for image-based (path-rendered) PDFs
        if avg_chars < 200:
            if not _ocr_available():
                raise RuntimeError(
                    "This PDF uses path-rendered text (non-selectable) and requires OCR, "
                    "but tesseract / pdf2image are not installed on this server.\n\n"
                    "Fix: re-export the schedule from your software as a standard PDF "
                    "(Export as PDF rather than Print to PDF), then try again."
                )
            print("  Low char density — running OCR")
            ocr_texts = _ocr_pages(pdf_path)
            days, show_name, episode = parse_from_ocr(ocr_texts)
        else:
            # Detect layout: columnar (EP/TP) vs sequential (MM)
            col_layout = detect_column_layout(pdf.pages)

            if col_layout:
                bg_x0, bg_x1 = col_layout['background']
                print(f"  Layout: Columnar  (BG column x={bg_x0:.0f}–{bg_x1:.0f})")
                all_rows = []
                for i, page in enumerate(pdf.pages, 1):
                    page_rows = extract_rows_columnar(page, bg_x0, bg_x1)
                    all_rows.extend(page_rows)
                    print(f"  Page {i}: {len(page_rows)} rows")
                days, show_name, episode = assemble_schedule(all_rows, column_mode=True)

            else:
                print("  Layout: Sequential")
                all_rows = []
                for i, page in enumerate(pdf.pages, 1):
                    page_rows = extract_rows_sequential(page)
                    # Convert (left, full) → (left, full) for assembler
                    all_rows.extend(page_rows)
                    print(f"  Page {i}: {len(page_rows)} lines")
                days, show_name, episode = assemble_schedule(all_rows, column_mode=False)

    # ── summary ──────────────────────────────────────────────────────────────
    print(f"\n  Show: '{show_name}', Episode: '{episode}'")
    print(f"\nParsed {len(days)} shooting days:")
    total_roles = 0
    for d in days:
        sc_c = len(d['scenes'])
        ro_c = sum(len(s['roles']) for s in d['scenes'])
        total_roles += ro_c
        dt = d.get('date') or 'no date'
        print(f"  Day {d['dayNumber']} ({dt}): {sc_c} scenes, {ro_c} BG roles")
        for s in d['scenes']:
            if s['roles']:
                print(f"    Scene {s['sceneId']}: {s['set']}")
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


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    state = parse_shootsked(pdf_path)

    out_path = (sys.argv[2] if len(sys.argv) >= 3
                else str(Path(pdf_path).parent / (Path(pdf_path).stem + '_bgboard.json')))

    with open(out_path, 'w') as f:
        json.dump(state, f, indent=2)

    print(f"\n✓ Saved: {out_path}")
    print("  Import via the '↑ Import' button in BGBoard.html")


if __name__ == '__main__':
    main()
