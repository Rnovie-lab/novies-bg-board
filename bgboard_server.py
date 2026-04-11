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

# ── Parser — delegate to parse_shootsked.py ───────────────────────────────────
# Both files live in the same directory; import the shared module.

import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))

try:
    from parse_shootsked import parse_shootsked as _parse_shootsked
    def parse_shootsked_pdf(pdf_path):
        return _parse_shootsked(pdf_path)
except ImportError:
    # Fallback: inline minimal Movie Magic parser if module missing
    def parse_shootsked_pdf(pdf_path):
        raise RuntimeError("parse_shootsked.py not found in the same directory as bgboard_server.py")

try:
    from schedule_parser import parse_shooting_schedule
    from schedule_to_bgboard import convert_schedule_to_bgboard
    HAS_SCHEDULE_PARSER = True
except ImportError:
    HAS_SCHEDULE_PARSER = False

try:
    from parse_extras_breakdown import parse_extras_breakdown
    HAS_BREAKDOWN_PARSER = True
except ImportError:
    HAS_BREAKDOWN_PARSER = False


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
        elif self.path == '/parse-schedule':
            self._handle_parse_schedule()
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

    def _handle_parse_schedule(self):
        """Handle /parse-schedule endpoint for Shamel and other formats"""
        if not HAS_SCHEDULE_PARSER:
            self.send_json({'error': 'Schedule parser not available'}, 501)
            return

        try:
            length = int(self.headers.get('Content-Length', 0))
            ctype  = self.headers.get('Content-Type', '')
            print(f"  POST /parse-schedule  Content-Length={length}  Content-Type={ctype[:60]}")

            # Read PDF bytes
            if length > 0:
                pdf_data = self.rfile.read(length)
            else:
                chunks = []
                while True:
                    chunk = self.rfile.read(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                pdf_data = b''.join(chunks)

            print(f"  Read {len(pdf_data)} bytes")

            if len(pdf_data) < 100:
                self.send_json({'error': f'Upload too small ({len(pdf_data)} bytes)'}, 400)
                return

            # Write to temp file and parse with schedule parser
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tf:
                tf.write(pdf_data)
                tmp_path = tf.name

            try:
                # Detect format — EP one-line (Cineapse/Showbiz) needs column-aware parsing
                import pdfplumber as _pdfplumber
                with _pdfplumber.open(tmp_path) as _pdf:
                    _sample = ''
                    for _p in _pdf.pages[:2]:
                        _words = _p.extract_words(x_tolerance=3, y_tolerance=3)
                        _sample += ' '.join(w['text'] for w in _words) + ' '
                # Detect format
                is_extras_breakdown = bool(
                    re.search(r'EXTRAS\s+BREAKDOWN', _sample, re.I) or
                    re.search(r'NUMBER\s+ROLE\s+RATES', _sample, re.I)
                )
                is_shootsked = bool(
                    re.search(r'\d{3}\s+Sc\s+\S+\s+(INT|EXT)', _sample) or  # EP one-line
                    'End of DAY' in _sample or                                 # EP one-line
                    re.search(r'Shoot\s+Day\s+#', _sample, re.I) or           # Movie Magic
                    re.search(r'End\s+Day\s+#', _sample, re.I)                # Movie Magic
                )

                if is_extras_breakdown and HAS_BREAKDOWN_PARSER:
                    print('  Format detected: Extras Breakdown')
                    bgboard_data = parse_extras_breakdown(tmp_path)
                elif is_shootsked:
                    print('  Format detected: Shooting Schedule (Movie Magic / EP one-line)')
                    bgboard_data = parse_shootsked_pdf(tmp_path)
                else:
                    print('  Format detected: heuristic (Shamel/other)')
                    bgboard_data = convert_schedule_to_bgboard(tmp_path)

                total_scenes = sum(len(day['scenes']) for day in bgboard_data['days'])
                total_roles = sum(len(scene['roles']) for day in bgboard_data['days'] for scene in day['scenes'])
                print(f"  ✓ Imported: {bgboard_data['show']['name']} — {len(bgboard_data['days'])} days, {total_scenes} scenes, {total_roles} BG roles")
                self.send_json({'ok': True, 'state': bgboard_data})
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
