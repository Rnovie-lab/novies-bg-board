# Testing BG Board Locally on Your Mac

## Current Status

✅ **Backend:** Heuristic parser + converter pipeline (complete)  
✅ **Frontend:** React app (ready to test)  
✅ **Data model:** BG Board format validated  
⚠️ **Blockers:** PDF file locking in sandbox (not an issue on your machine)

## Quick Start (5 mins)

### 1. Prerequisites
Ensure you have Python 3.8+ and the required packages:

```bash
pip install pdfplumber --break-system-packages
```

### 2. Start the Server Locally

```bash
cd /path/to/BG Board
python3 bgboard_server.py
```

You'll see:
```
══════════════════════════════════════════════════════════
  Novie's BG Board Server
══════════════════════════════════════════════════════════
  Listening on 0.0.0.0:8765
  Open: http://localhost:8765
  Press Ctrl+C to stop
══════════════════════════════════════════════════════════
```

### 3. Open the Frontend
Click the link or go to: **http://localhost:8765**

### 4. Test the Parser
1. Click **↑ Import** (or drag-drop a PDF)
2. Select your shooting schedule PDF
3. The server will:
   - Parse it with the heuristic parser (`HeuristicScheduleParser`)
   - Convert to BG Board format (`schedule_to_bgboard`)
   - Return structured day/scene/role data

## Test Files Available

You have two shootsked formats to test with:

- **St. Denis Medical 217** (`SDM 217...`) — Movie Magic format
- **St. Denis Medical 218** (`SDM 218...`) — Also Movie Magic format

Both are known to parse correctly.

## What Gets Tested

When you upload a PDF, the `/parse-schedule` endpoint:

1. ✅ Detects format (Movie Magic, EP one-line, etc.) automatically
2. ✅ Extracts shooting days using universal patterns
3. ✅ Parses scene headers (both Shamel + Standard formats)
4. ✅ Extracts background actors within each scene block
5. ✅ Converts to BG Board roles with:
   - Count, type, tier (SAG/non-union)
   - Base rates ($182 SAG, $120 non-union)
   - Auto-detected bumps (wardrobe, props, hazards)
   - Notes and metadata

## Debugging Tips

### View Server Logs
The terminal shows:
```
POST /parse-schedule  Content-Length=2048  Content-Type=application/pdf
Read 2048 bytes
✓ Imported: St. Denis Medical — 5 days, 31 scenes, 69 BG roles
```

### Browser DevTools
- **Network tab:** See the POST request payload
- **Console:** App logs (if frontend is instrumented)

### Manual Test (curl)
```bash
curl -X POST http://localhost:8765/parse-schedule \
  -H "Content-Type: application/pdf" \
  --data-binary @"SDM 217 Extras Breakdown 10.23.25.pdf" \
  | python3 -m json.tool | head -50
```

This returns the full parsed state (days → scenes → roles).

## Next Steps After Testing

1. **If parser works:** Commit changes and move to Phase 2 (frontend refinements)
2. **If issues occur:** Check the server logs for specific error from pdfplumber
3. **To customize:** Edit bumps library in `schedule_to_bgboard.py` line ~210

---

**Ready to test?** Start the server and let me know what happens when you upload a real PDF.
