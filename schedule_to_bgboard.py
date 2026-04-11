"""
Convert parsed schedule data to BG Board data model.
Maps parser output → shooting days → scenes → background actors
"""

from typing import Dict, List, Optional
from schedule_parser import parse_shooting_schedule


def convert_schedule_to_bgboard(pdf_path: str, format_type: str = "auto") -> Dict:
    """
    Parse a shooting schedule PDF and convert it directly to BG Board data model.

    Returns data structure ready to populate BG Board UI:
    {
        "show": {...},
        "days": [
            {
                "dayNum": 1,
                "date": "2025-05-12",
                "standins": [...],
                "scenes": [...]
            }
        ]
    }
    """

    # Step 1: Parse the schedule using schedule_parser
    parsed = parse_shooting_schedule(pdf_path, format_type)

    # Step 2: Convert to BG Board format
    show_data = {
        "name": parsed["metadata"]["show_title"],
        "episode": "",
        "version": "1",
        "preparedBy": "",
        "role": "",
        "contractType": "tv",
        "sagMin": 25
    }

    # Extract ALL shooting days from the PDF (even those without background actors)
    # This ensures we show all 18 days even if some don't have BG actors assigned yet
    all_day_numbers = set()
    try:
        import re
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            all_text = ""
            for page in pdf.pages:
                all_text += page.extract_text() + "\n"

        # Find all "End of Day X" markers
        day_pattern = r'End of Day (\d+)\s*\|'
        for match in re.finditer(day_pattern, all_text):
            day_num = int(match.group(1))
            all_day_numbers.add(day_num)
    except Exception as e:
        print(f"Warning: Could not extract all day numbers from PDF: {e}")

    # Group scenes by shooting day (extracted from "End of Day X" markers)
    days_dict = {}
    for scene in parsed["scenes"]:
        # Use shooting_day if available (from Shamel format), otherwise fall back to time_of_day
        day_key = scene.get("shooting_day") or scene.get("time_of_day") or "Unknown"

        if day_key not in days_dict:
            days_dict[day_key] = []

        days_dict[day_key].append(scene)

    # Ensure all extracted days are in the dict (even if empty)
    for day_num in all_day_numbers:
        if day_num not in days_dict:
            days_dict[day_num] = []

    # Convert to BG Board day structure
    # Sort days numerically if they're shooting day numbers
    sorted_days = []
    for day_key, scenes in days_dict.items():
        # Try to parse as integer (shooting day number) for proper sorting
        try:
            sort_key = int(day_key) if isinstance(day_key, (int, str)) else 999
        except (ValueError, TypeError):
            sort_key = 999
        sorted_days.append((sort_key, day_key, scenes))

    sorted_days.sort(key=lambda x: x[0])

    days = []
    for idx, (sort_key, day_key, scenes) in enumerate(sorted_days, 1):
        day_scenes = []

        for scene in scenes:
            # Convert each scene to BG Board format
            bg_board_scene = _convert_scene_to_bgboard(scene)
            day_scenes.append(bg_board_scene)

        # Use shooting day number as dayNum, but also show the day_key as label
        day_num = int(day_key) if isinstance(day_key, (int, str)) else idx
        day_label = f"Day {day_num}"

        day_data = {
            "id": f"day-{day_num}",
            "dayNumber": day_num,  # Field name expected by UI rendering
            "dayLabel": day_label,
            "date": "",  # Would need actual date from schedule if available
            "standins": [],  # Would need standin data from separate source
            "standinOff": {},  # Tracks which standins are off this day
            "standinHours": {},  # Tracks standin hours per day
            "scenes": day_scenes
        }

        days.append(day_data)

    return {
        "show": show_data,
        "standins": [],  # Top-level standins array (required by BGBoard app)
        "days": days,
        "metadata": parsed["metadata"]
    }


def _convert_scene_to_bgboard(scene: Dict) -> Dict:
    """
    Convert a parsed scene to BG Board scene format.

    BG Board scene format:
    {
        "id": "unique-id",
        "sceneId": "35",
        "intExt": "INT",
        "set": "KITCHEN",
        "desc": "Liz prepares breakfast",
        "roles": [
            {
                "id": "role-1",
                "type": "WAITERS",
                "count": 3,
                "tier": "SAG",
                "rate": 182,
                "hours": 8,
                "bumps": ["wardrobe"],
                "reuse": true,
                "notes": ""
            }
        ]
    }
    """

    scene_id = f"scene-{scene['scene_id']}"

    # Convert background actors to BG Board roles
    roles = []
    for bg_actor in scene.get("background_actors", []):
        role = _convert_bg_actor_to_role(bg_actor)
        roles.append(role)

    return {
        "id": scene_id,
        "sceneId": scene["scene_id"],
        "intExt": scene.get("int_ext") or "INT",
        "set": scene.get("set") or "Unknown Set",
        "desc": scene.get("synopsis") or "",
        "duration": scene.get("duration") or "0h 00m",
        "timeOfDay": scene.get("time_of_day") or "",
        "roles": roles
    }


def _convert_bg_actor_to_role(bg_actor: Dict) -> Dict:
    """
    Convert a background actor description to a BG Board role.

    Input: { "count": 2, "type": "ELEVEN PEOPLE", "notes": "tequila shots" }
    Output: {
        "id": "role-unique-id",
        "type": "ELEVEN PEOPLE",
        "count": 2,
        "tier": "nonunion",  # Must match app's expected value
        "baseRate": 120,     # App uses 'baseRate' not 'rate'
        "hours": 8,
        "bumps": [{category, name, amt}, ...],  # Objects with amt property
        "reuse": false,
        "notes": "tequila shots"
    }
    """

    import uuid

    # Extract bumps from notes and extracted props
    # Bumps should be objects with category, name, and amt (amount)
    bumps = []
    notes = bg_actor.get("notes", "")
    extracted_props = bg_actor.get("props", [])  # Props extracted by parser

    # Add extracted props as bumps
    for prop in extracted_props:
        bumps.append({
            "id": f"bump-{uuid.uuid4().hex[:8]}",
            "category": "props",
            "name": prop,
            "amt": 5  # Default prop bump amount
        })

    # Also check notes for additional bump keywords
    bump_info = {
        "wardrobe": {
            "keywords": ["robe", "watch", "gun", "hat", "shirt", "tee"],
            "amt": 10  # Default bump amount for wardrobe
        },
        "special": {
            "keywords": ["stunt", "double", "coord"],
            "amt": 50
        }
    }

    notes_lower = notes.lower()
    for category, info in bump_info.items():
        if any(kw in notes_lower for kw in info["keywords"]):
            bumps.append({
                "id": f"bump-{uuid.uuid4().hex[:8]}",
                "category": category,
                "name": category.title(),
                "amt": info["amt"]
            })

    return {
        "id": f"role-{uuid.uuid4().hex[:8]}",
        "type": bg_actor.get("type", "Background").strip(),
        "count": bg_actor.get("count", 1),
        "tier": "sag",       # Default to SAG union rate
        "baseRate": 182,     # SAG rate $182/8hrs
        "hours": 8,
        "bumps": bumps,      # Array of {id, category, name, amt} objects
        "reuse": False,
        "notes": notes
    }


def import_schedule_to_bgboard_state(pdf_path: str) -> Dict:
    """
    Complete import workflow: PDF → BG Board ready-to-use state

    This is what gets saved to the app's state/database.
    """

    bgboard_data = convert_schedule_to_bgboard(pdf_path)

    return {
        "show": bgboard_data["show"],
        "days": bgboard_data["days"],
        "importedFrom": {
            "format": bgboard_data["metadata"]["format"],
            "fileName": pdf_path.split("/")[-1]
        }
    }


# Example usage
if __name__ == "__main__":
    import json

    pdf_path = "/sessions/eager-awesome-pascal/mnt/uploads/Shooting_Schedule_Pony Fleek_Board 1_portrait.pdf"

    # Convert to BG Board format
    bgboard = convert_schedule_to_bgboard(pdf_path)

    print("✓ Converted to BG Board format\n")
    print(f"Show: {bgboard['show']['name']}")
    print(f"Days: {len(bgboard['days'])}")

    # Show first day with scenes
    if bgboard['days']:
        day = bgboard['days'][0]
        print(f"\nDay {day['dayNum']} ({day['dayLabel']}):")
        print(f"  Scenes: {len(day['scenes'])}")

        if day['scenes']:
            scene = day['scenes'][0]
            print(f"\n  Scene {scene['sceneId']}: {scene['set']}")
            print(f"  Background Roles: {len(scene['roles'])}")

            for role in scene['roles'][:3]:
                print(f"    • {role['count']}x {role['type']}")
                if role['bumps']:
                    print(f"      Bumps: {', '.join(role['bumps'])}")

    print("\n" + "="*70)
    print("FULL OUTPUT (first scene):")
    print("="*70)
    if bgboard['days'] and bgboard['days'][0]['scenes']:
        print(json.dumps(bgboard['days'][0]['scenes'][0], indent=2))
