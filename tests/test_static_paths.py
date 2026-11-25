#!/usr/bin/env python3
"""tests/test_static_paths.py: the server only hands out its own page files.

The static part of do_GET used to join whatever path it was asked for onto
the app folder and send the file back. So it would send the server's own
code, the usage counter, any saved board (skipping the sign-in check that
/saves/<id> has), and, with "..", files outside the folder.

Now a static request gets a file only when all of these hold:
  it is one plain name (no folders, no "..", no leading dot),
  it ends in a page type (html, css, js, png, jpg, jpeg, svg, ico),
  and it really sits in the app folder (a link pointing elsewhere is refused).

This starts the real server on a spare port with a temp saves folder and
asks for each thing over a raw socket, so nothing tidies the path on the way.
No network beyond 127.0.0.1, no keys.

Run from the BG Board directory:
    python3 tests/test_static_paths.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
from http.server import HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

SAVES = Path(tempfile.mkdtemp(prefix='bgb_saves_'))
os.environ['BGBOARD_SAVES_DIR'] = str(SAVES)
(SAVES / 'secretboard.json').write_text(json.dumps({'user_id': 'someone', 'marker': 'PRIVATE-BOARD'}))

import bgboard_server as B  # noqa: E402

FAILS = []


def check(name, cond, detail=''):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f'  ({detail})' if (detail and not cond) else ''))
    if not cond:
        FAILS.append(name)


def get(port, raw_path):
    """One GET with the path sent exactly as given. Returns (status, headers, body)."""
    s = socket.create_connection(('127.0.0.1', port), timeout=10)
    s.sendall(f'GET {raw_path} HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n'.encode('latin-1'))
    data = b''
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    head, _, body = data.partition(b'\r\n\r\n')
    lines = head.decode('latin-1').split('\r\n')
    status = int(lines[0].split()[1]) if lines and len(lines[0].split()) > 1 else 0
    headers = {k.strip().lower(): v.strip() for k, v in (ln.split(':', 1) for ln in lines[1:] if ':' in ln)}
    return status, headers, body


def main():
    server = HTTPServer(('127.0.0.1', 0), B.BGBoardHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # A link in the app folder that points outside it, named like a picture.
    outside = Path(tempfile.mkdtemp(prefix='bgb_outside_')) / 'outside.txt'
    outside.write_text('OUTSIDE-THE-APP-FOLDER')
    link = REPO / 'zz-test-link.png'
    made_link = False
    try:
        link.symlink_to(outside)
        made_link = True
    except OSError:
        pass
    # A real file in a folder below the app folder.
    sub = REPO / 'zz-test-sub'
    sub.mkdir(exist_ok=True)
    (sub / 'page.html').write_text('SUBFOLDER-PAGE')

    try:
        print('the pages and pictures still load')
        st, h, body = get(port, '/')
        check('/ is the board page', st == 200 and b'<html' in body.lower() and h.get('content-type', '').startswith('text/html'), (st, h.get('content-type')))
        st, h, body = get(port, '/BGBoard.html?x=1')
        check('/BGBoard.html loads, with a query string too', st == 200 and b'<html' in body.lower(), st)
        st, h, body = get(port, '/BGBoard_AD_Reference.html')
        check('the reference page loads', st == 200, st)
        for pic in ('bgboard-logo.png', 'csc-logo-silver.png', 'gs-logo.png', 'noviesrules-logo.png', 'radar-logo.png'):
            st, h, body = get(port, '/' + pic)
            check(f'{pic} loads as a picture', st == 200 and h.get('content-type') == 'image/png' and body[:4] == b'\x89PNG',
                  (st, h.get('content-type')))

        print('nothing else in the app folder is handed out')
        for name in ('bgboard_server.py', 'parse_shootsked.py', 'schedule_parser.py', 'requirements.txt', 'Dockerfile',
                     'CLAUDE.md', 'railway.json', 'usage_counter.json', '.gitignore', '.git/config', 'restart.sh',
                     'tests/run_tests.py', 'zz-test-sub/page.html'):
            st, h, body = get(port, '/' + name)
            check(f'/{name} is refused', st == 404 and not body, (st, body[:40]))

        print('no way out of the app folder')
        for p in ('/../bgboard_server.py', '/../../etc/passwd', '/..%2f..%2fetc%2fpasswd', '/%2e%2e/%2e%2e/etc/passwd',
                  '//etc/passwd', '/x/../bgboard_server.py', '/BGBoard.html/../bgboard_server.py',
                  '/..\\..\\etc\\passwd', '/BGBoard.html%00.py', '/bgboard_server.py%00.png', '/%2fetc%2fpasswd'):
            st, h, body = get(port, p)
            check(f'{p} is refused', st == 404 and not body, (st, body[:40]))
        if made_link:
            st, h, body = get(port, '/zz-test-link.png')
            check('a link that points outside the folder is refused', st == 404 and b'OUTSIDE' not in body, (st, body[:40]))

        print('a saved board cannot be read around the sign-in check')
        for p in ('/x/../saves/secretboard.json', '/./saves/secretboard.json', '/%73aves/secretboard.json',
                  '/saves%2fsecretboard.json', '/BGBoard.html/../saves/secretboard.json'):
            st, h, body = get(port, p)
            check(f'{p} gives no board', b'PRIVATE-BOARD' not in body and st in (401, 404), (st, body[:60]))
        st, h, body = get(port, '/saves/secretboard.json')
        check('/saves/<id> still asks for a sign-in', b'PRIVATE-BOARD' not in body and st in (401, 404), (st, body[:60]))

        print('the rule itself')
        ok = B._static_file
        check('a page name gives its file', ok('BGBoard.html') == (REPO / 'BGBoard.html').resolve())
        check('empty, dot and folder names give nothing',
              all(ok(x) is None for x in ('', '.', '..', '.gitignore', 'a/b.html', 'a\\b.html', 'saves', 'tests')))
        check('a type it does not serve gives nothing', all(ok(x) is None for x in ('x.py', 'x.json', 'x.md', 'x.pdf', 'x.mov', 'x')))
        check('a page type that is not there gives nothing', ok('nope.html') is None)
    finally:
        server.shutdown()
        if made_link:
            link.unlink()
        (sub / 'page.html').unlink()
        sub.rmdir()

    print(f'\n{len(FAILS)} failure(s)')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
