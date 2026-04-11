#!/usr/bin/env python3
"""
parse_extras_breakdown.py — Parse an existing Extras Breakdown PDF into BGBoard JSON.

This handles the OUTPUT format (the finished extras breakdown that a 2nd AD creates),
NOT a shooting schedule. Format looks like:

    DAY 1: 10.27.25
    SCENES: 7,9,8,10,12,15,17,28
    NUMBER ROLE RATES SCENES HOURS BUMPS/NOTES
    11 Doctors (for checkup) $144/8 11 General Care wing
    4 Nurses $144/8 11 General Care wing
    ...
    17 TOTAL BG
"""

import re
import uuid
import pdfplumber


def uid():
    return str(uuid.uuid4())[:8]


def parse_extras_breakdown(pdf_path):
    """Parse an extras breakdown PDF → BGBoard state dict."""

    with pdfplumber.open(pdf_path) as pdf:
        full_text = ''
        for page in pdf.pages:
            full_text += page.extract_text() + '\n'

    lines = [l.strip() for l in full_text.split('\n') if l.strip()]

    # Extract show name from first line
    show_name = ''
    episode = ''
    first = lines[0] if lines else ''
    ep_m = re.search(r'EP\s*(\d{2,3})', first, re.I)
    if ep_m:
        episode = ep_m.group(1)
    # Show name is usually in quotes at the start
    name_m = re.search(r'"([^"]+)"', first)
    if name_m:
        show_name = name_m.group(1)
    else:
        show_name = first.split('-')[0].strip() if '-' in first else first[:40]

    # Parse days
    days = []
    current_day = None
    current_scenes_str = ''
    in_data = False

    # Lines to skip
    RE_SUMMARY = re.compile(
        r'^(\d+\s+)?(Total\s+Stand|Union|NU\s+BG|TOTAL\s+BG|BG\s+Grand|Stand-Ins)',
        re.I
    )
    RE_NOTE = re.compile(r'^\*')
    RE_COLUMN_HDR = re.compile(r'^NUMBER\s+ROLE', re.I)

    for line in lines:
        # Day header: "DAY 1: 10.27.25"
        day_m = re.match(r'^DAY\s+(\d+):\s*(\S+)', line, re.I)
        if day_m:
            # Save previous day
            if current_day:
                days.append(current_day)
            day_num = int(day_m.group(1))
            date_raw = day_m.group(2)
            # Convert 10.27.25 → 2025-10-27
            date_parts = date_raw.split('.')
            if len(date_parts) == 3:
                mm, dd, yy = date_parts
                date_str = f'20{yy}-{mm.zfill(2)}-{dd.zfill(2)}'
            else:
                date_str = date_raw
            current_day = {
                'id': uid(),
                'dayNumber': day_num,
                'date': date_str,
                'scenes': [],
                'standinOff': {},
                'standinHours': {}
            }
            in_data = False
            continue

        # Scenes line: "SCENES: 7,9,8,10,12,15,17,28"
        sc_m = re.match(r'^SCENES?:\s*(.+)', line, re.I)
        if sc_m:
            current_scenes_str = sc_m.group(1).strip()
            continue

        # Column header
        if RE_COLUMN_HDR.match(line):
            in_data = True
            continue

        if not current_day or not in_data:
            continue

        # Skip summary/note lines
        if RE_SUMMARY.match(line):
            continue
        if RE_NOTE.match(line):
            continue

        # Parse data row: "11 Doctors (for checkup - 6 in doc coats) $144/8 11 General Care wing"
        # or: "1 RON SI (Mike) $262/8 10"
        # Format: COUNT ROLE $RATE/HOURS SCENES HOURS NOTES

        # Try to extract count + role + rate
        row_m = re.match(r'^(\d+)\s+(.+?)\s+\$(\d+(?:\.\d+)?)/(\d+)\s*(.*)', line)
        if not row_m:
            # Try without rate (some rows have rate on next line)
            row_m2 = re.match(r'^(\d+)\s+(.+?)(?:\s+(\d+)\s*$|\s*$)', line)
            if row_m2 and not re.match(r'^\d+\s+(Total|Union|NU|TOTAL|BG)', line, re.I):
                count = int(row_m2.group(1))
                role = row_m2.group(2).strip()
                hours = int(row_m2.group(3)) if row_m2.group(3) else 8
                rate = 0
                notes = ''
            else:
                continue
        else:
            count = int(row_m.group(1))
            role = row_m.group(2).strip()
            rate = float(row_m.group(3))
            hours = int(row_m.group(4))
            rest = row_m.group(5).strip()
            # rest might be "11 General Care wing" (scenes + notes) or just notes
            notes_m = re.match(r'^[\d,\s]+(.*)$', rest)
            notes = notes_m.group(1).strip() if notes_m else rest

        # Skip standins (SI in role name)
        if ' SI ' in role or ' SI(' in role or role.endswith(' SI'):
            continue
        # Skip Med Tech (run-of-show crew, not BG)
        if 'Med Tech' in role:
            continue

        # Determine tier from rate
        if rate >= 224:
            tier = 'sag'
            base_rate = 182
        elif rate >= 144:
            tier = 'sag'
            base_rate = 182
        elif rate > 0:
            tier = 'nonunion'
            base_rate = 120
        else:
            tier = 'sag'
            base_rate = 182

        # Clean role name: strip parenthetical details but keep them as notes
        role_clean = role
        paren_m = re.search(r'\(([^)]+)\)', role)
        paren_note = ''
        if paren_m:
            paren_note = paren_m.group(1)
            # Only strip if it's a clarification, not part of the name
            if len(paren_note) > 15:
                role_clean = role[:paren_m.start()].strip()
                if notes:
                    notes = paren_note + '; ' + notes
                else:
                    notes = paren_note

        scene_entry = {
            'id': uid(),
            'sceneId': current_scenes_str,
            'set': '',
            'desc': '',
            'roles': []
        }

        # Check if we already have a scene entry for this day's scenes
        existing = [s for s in current_day['scenes'] if s['sceneId'] == current_scenes_str]
        if existing:
            scene_entry = existing[0]
        else:
            current_day['scenes'].append(scene_entry)

        scene_entry['roles'].append({
            'id': uid(),
            'type': role_clean,
            'count': count,
            'tier': tier,
            'baseRate': base_rate,
            'hours': hours,
            'bumps': [],
            'notes': notes,
            'minors': False
        })

    # Don't forget last day
    if current_day:
        days.append(current_day)

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


if __name__ == '__main__':
    import sys, json
    if len(sys.argv) < 2:
        print('Usage: python3 parse_extras_breakdown.py <breakdown.pdf>')
        sys.exit(1)
    result = parse_extras_breakdown(sys.argv[1])
    print(json.dumps(result, indent=2))
