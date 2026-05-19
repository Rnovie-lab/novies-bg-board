#!/usr/bin/env python3
"""
migrate_saves_to_user.py — one-time migration tagging legacy saves with a
Clerk user_id so they appear in that user's workspace after auth ships.

Use this once, after Ross signs in to BG Board for the first time, to claim
the 2 existing saves (0s88shc7.json and nbhxs20l.json) that were created
before auth existed.

How to get your Clerk user_id:
  1. Sign in to bgboard.up.railway.app
  2. Open browser DevTools console (F12)
  3. Type:  window.__clerk.user.id
  4. Copy the value (looks like "user_2ab3cd4ef5gh6ij...")

Usage:
    python3 migrate_saves_to_user.py user_2ab3cd4ef5gh6ij...

Idempotent: skips saves that already have a _userId set.
"""

import json
import sys
from pathlib import Path

SAVES_DIR = Path(__file__).parent / 'saves'

def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    user_id = sys.argv[1]
    if not user_id.startswith('user_'):
        print(f"⚠ '{user_id}' doesn't look like a Clerk user_id (should start with 'user_')")
        print("  Continuing anyway — but double-check the value.")

    if not SAVES_DIR.exists():
        print(f"✗ No saves directory at {SAVES_DIR}")
        sys.exit(1)

    files = sorted(SAVES_DIR.glob('*.json'))
    if not files:
        print(f"ℹ No saves to migrate in {SAVES_DIR}")
        return

    touched, skipped = 0, 0
    for f in files:
        data = json.loads(f.read_text())
        if data.get('_userId'):
            print(f"  • {f.name}: already owned by {data['_userId']} — skipping")
            skipped += 1
            continue
        data['_userId'] = user_id
        f.write_text(json.dumps(data, indent=2))
        print(f"  ✓ {f.name}: tagged with {user_id} (save '{data.get('_saveName','Untitled')}')")
        touched += 1

    print(f"\nDone. {touched} migrated, {skipped} already owned.")

if __name__ == '__main__':
    main()
