#!/usr/bin/env python3
"""
bgboard_server.py — Local server for BGBoard with PDF import support.

Usage:
    python3 bgboard_server.py

Then open: http://localhost:8765

Serves BGBoard.html and handles PDF-to-JSON parsing via POST /parse-pdf.
Requires: pdfplumber  (pip install pdfplumber --break-system-packages)
"""

import sys
import os
import json
import re
import uuid
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import webbrowser
import threading

# ── Parser (same logic as parse_shootsked.py) ─────────────────────────────────

def uid():
    return str(uuid.uuid4())[:8]

MONTHS = {
    'january':'01','february':'02','march':'03','april':'04',
    'may':'05','june':'06','july':'07','august':'08',
    'september':'09','october':'10','november':'11','december':'12'
}

def parse_date(text):
    m = re.search(r'(\w+)\s+(\d{1,2}),\s+(\d{4})', text, re.I)
    if m:
        month = MONTHS.get(m.group(1).lower(), '00')
        return f"{m.group(3)}-{month}-{m.group(2).zfill(2)}"
    return ''

def extract_dual_lines(page, x_split=310):
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

RE_SHOOT_DAY  = re.compile(r'^Shoot\s+Day\s+#\s*(\d+)\s+(.*)', re.I)
RE_END_DAY    = re.compile(r'^End\s+Day\s+#', re.I)
RE_SCENE      = re.compile(r'^Scene\s+#\s*(.+)$', re.I)
BG_HEADERS    = {'Background Actors','Background Actor','Background','Extras'}
NON_BG_HEADERS= {
    'Cast Members','Cast','Special Equipment','Props','Set Dressing',
    'Vehicles','Picture Cars','Art Department','Special Effects','Music',
    'Hair/Makeup','Wardrobe','Animals','Notes','Stunts',
    'Mechanical Effects','Sound','Camera','Electric','Grip',
    'Location Notes','Production','Miscellaneous','Additional Labor',
}
RE_PAGE_NOISE = re.compile(
    r'^(Page\s+\d+|Printed\s+on\s|Day\s+Out\s+Of|DOOD|Total\s+Pages|'
    r'Revision\s|Revised\s|REVISED\s|Locked\s|LOCKED\s|'
    r'Previously\s+Shot|Scene\s+Count)', re.I)
RE_LIKELY_NOTE = re.compile(
    r'^(roll\s|move\s|shoot\s|see\s|note[:\s]|show\s|per\s|ot\s|tlbd|tbd)', re.I)
RE_CAST = re.compile(r'^\d+\.[A-Z]')
RE_BG_COUNT = re.compile(r'^(\d+)\s+(.+)$')

def classify_left(left):
    s = left.strip()
    if not s: return 'empty'
    if s in BG_HEADERS: return 'bg_header'
    if s in NON_BG_HEADERS: return 'section_header'
    if RE_PAGE_NOISE.match(s): return 'noise'
    if RE_CAST.match(s): return 'cast_entry'
    return 'content'

def parse_bg_role(line):
    line = line.strip()
    if not line or len(line) < 2: return None
    if RE_PAGE_NOISE.match(line): return None
    if RE_CAST.match(line): return None
    m = RE_BG_COUNT.match(line)
    if m:
        return (int(m.group(1)), m.group(2).strip())
    return (1, line)

def parse_shootsked_pdf(pdf_path):
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber not installed. Run: pip install pdfplumber --break-system-packages")

    all_lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            all_lines.extend(extract_dual_lines(page))

    # Show info
    show_name, episode = '', ''
    for left, full in all_lines[:15]:
        ep_m = re.search(r'Ep#?\s*(\d{2,3})', full, re.I)
        if ep_m and not episode:
            episode = ep_m.group(1)
        if (not show_name and len(left) > 6 and
                not RE_SHOOT_DAY.match(left) and not RE_SCENE.match(left) and
                not left.startswith('Shooting') and not left.startswith('DIRECTOR')):
            if re.search(r'[A-Za-z]{3,}', left):
                show_name = left

    # Collect page header fingerprints
    page_header_skip = set(left.strip() for left, _ in all_lines[:8] if left.strip())
    page_header_skip.add('Shooting Schedule')

    # State machine
    days, current_day, current_scene, pending_location, in_bg = [], None, None, '', False

    def commit_scene():
        if current_scene is not None and current_day is not None:
            current_day['scenes'].append(current_scene)

    def start_day(num, date_text):
        nonlocal current_day, current_scene, in_bg, pending_location
        commit_scene()
        current_scene = None; in_bg = False; pending_location = ''
        d = {'id':uid(),'dayNumber':num,'date':parse_date(date_text),
             'scenes':[],'standinOff':{},'standinHours':{}}
        days.append(d); current_day = d

    def start_scene(scene_id, set_text, desc=''):
        nonlocal current_scene, in_bg
        commit_scene()
        in_bg = False
        current_scene = {'id':uid(),'sceneId':scene_id.strip().rstrip(',').strip(),
                         'set':set_text.strip(),'desc':desc.strip(),'roles':[]}

    for left, full in all_lines:
        m = RE_SHOOT_DAY.match(full)
        if m:
            start_day(int(m.group(1)), m.group(2)); continue

        if RE_END_DAY.match(full):
            commit_scene(); current_scene = None; in_bg = False; pending_location = ''; continue

        if current_day is None: continue

        m_scene = RE_SCENE.match(left)
        if m_scene:
            scene_id = m_scene.group(1).strip().rstrip(',').strip()
            desc = full[len(left):].strip() if full != left else ''
            desc = re.sub(r'\s*Stage\s+\d+.*$', '', desc, flags=re.I).strip()
            start_scene(scene_id, pending_location or 'TBD', desc)
            pending_location = ''; continue

        if re.match(r'^(INT|EXT)[\s\./]', left, re.I):
            loc = re.sub(r'\s+Stage\s+\d+.*$', '', left, flags=re.I).strip()
            pending_location = loc; in_bg = False; continue

        kind = classify_left(left)
        if kind == 'bg_header':   in_bg = True;  continue
        if kind == 'section_header': in_bg = False; continue
        if kind in ('empty','noise','cast_entry'): continue

        if in_bg and current_scene is not None:
            if left.strip() in page_header_skip: continue
            if RE_PAGE_NOISE.match(left.strip()): continue
            if re.search(r'\(p\)\s*$', left, re.I): continue
            if RE_LIKELY_NOTE.match(left.strip()): continue
            if re.match(r'^[A-Z\s!\.]+$', left.strip()) and '!' in left: continue
            result = parse_bg_role(left)
            if result:
                count, desc = result
                current_scene['roles'].append({
                    'id':uid(),'type':desc,'count':count,
                    'tier':'sag','baseRate':182,'hours':8,
                    'bumps':[],'notes':'','minors':False
                })

    commit_scene()

    return {
        'show':{'name':show_name,'episode':episode,'version':'1',
                'preparedBy':'','contractType':'tv','sagMin':25},
        'standins':[], 'days':days
    }


# ── HTTP Server ────────────────────────────────────────────────────────────────

SERVER_DIR = Path(__file__).parent
PORT = int(os.environ.get('PORT', 8765))
IS_LOCAL = PORT == 8765  # running locally vs hosted

class BGBoardHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Use the parent's format string correctly, then print cleanly
        try:
            msg = format % args
            print(f"  {msg}")
        except Exception:
            pass  # never let logging crash the server

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0].lstrip('/')
        if path == '' or path == 'BGBoard.html':
            path = 'BGBoard.html'
        file_path = SERVER_DIR / path
        if not file_path.exists() or not file_path.is_file():
            self.send_response(404); self.end_headers()
            return
        suffix = file_path.suffix.lower()
        types = {'.html':'text/html','.js':'text/javascript',
                 '.css':'text/css','.json':'application/json'}
        ctype = types.get(suffix, 'application/octet-stream')
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        if self.path == '/parse-pdf':
            self._handle_parse_pdf()
        else:
            self.send_response(404); self.end_headers()

    def _handle_parse_pdf(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            ctype  = self.headers.get('Content-Type', '')
            print(f"  POST /parse-pdf  Content-Length={length}  Content-Type={ctype[:60]}")

            # Read however many bytes the browser says it's sending
            if length > 0:
                pdf_data = self.rfile.read(length)
            else:
                # No Content-Length — read in chunks until connection closes
                chunks = []
                while True:
                    chunk = self.rfile.read(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                pdf_data = b''.join(chunks)

            print(f"  Read {len(pdf_data)} bytes")

            if len(pdf_data) < 100:
                self.send_json({'error': f'Upload too small ({len(pdf_data)} bytes) — try again'}, 400)
                return

            # Write to temp file and parse
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tf:
                tf.write(pdf_data)
                tmp_path = tf.name

            try:
                state = parse_shootsked_pdf(tmp_path)
                scene_count = sum(len(d['scenes']) for d in state['days'])
                role_count  = sum(len(s['roles']) for d in state['days'] for s in d['scenes'])
                print(f"  ✓ Parsed: {len(state['days'])} days, {scene_count} scenes, {role_count} BG roles")
                self.send_json({'ok': True, 'state': state})
            finally:
                os.unlink(tmp_path)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_json({'error': str(e)}, 500)


def main():
    # Check pdfplumber
    try:
        import pdfplumber
    except ImportError:
        print("ERROR: pdfplumber not installed.")
        print("Run: pip install pdfplumber --break-system-packages")
        sys.exit(1)

    host = '0.0.0.0'  # bind all interfaces (required for Railway)
    print(f"\n{'═'*50}")
    print(f"  Novie's BG Board Server")
    print(f"{'═'*50}")
    print(f"  Listening on {host}:{PORT}")
    if IS_LOCAL:
        print(f"  Open: http://localhost:{PORT}")
        print(f"  Press Ctrl+C to stop")
    print(f"{'═'*50}\n")

    # Auto-open browser only when running locally
    if IS_LOCAL:
        def open_browser():
            import time; time.sleep(0.5)
            webbrowser.open(f"http://localhost:{PORT}")
        threading.Thread(target=open_browser, daemon=True).start()

    server = HTTPServer((host, PORT), BGBoardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")


if __name__ == '__main__':
    main()
