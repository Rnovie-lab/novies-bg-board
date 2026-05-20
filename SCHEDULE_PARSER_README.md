# Schedule Parser Architecture

## Overview

`schedule_parser.py` is a modular, extensible system for parsing shooting schedules from different production software (Shamel, ProductionHub, Movie Magic, etc.) and extracting background actor data for use in BG Board.

## Current Status

✅ **Shamel** — Fully implemented and tested
- Parses 47-page schedules correctly
- Extracts: Scene #, INT/EXT, Set, Time of Day, Background Actor descriptions and counts
- Example: "2 x ELEVEN PEOPLE" for party scenes, "1 x YOUNG COUPLE" for cafe scenes

## Architecture

### Base Class: `ScheduleParser`

All format-specific parsers inherit from `ScheduleParser`, which defines the interface:

```python
class ScheduleParser(ABC):
    @abstractmethod
    def parse(self, pdf_path: str) -> Dict:
        """Parse PDF and return structured scene data"""
        pass
```

### Return Format

All parsers return a standardized dictionary:

```python
{
    "metadata": {
        "format": "Shamel",
        "show_title": "Pony Fleek",
        "board": "Board 1",
        "total_pages": 47
    },
    "scenes": [
        {
            "scene_id": "35",
            "int_ext": "INT",
            "set": "VARIOUS SCENES FROM LIZ'S DAY",
            "time_of_day": "MORNING",
            "duration": "0h 00m",
            "synopsis": "Liz's day caring for Jerry...",
            "cast": [],
            "background_actors": [
                {
                    "count": 1,
                    "type": "MIDDLE AGED DAUGHTER",
                    "notes": "beach photo"
                },
                {
                    "count": 2,
                    "type": "OTHER BACKGROUND",
                    "notes": ""
                }
            ],
            "props": [],
            "wardrobe": [],
            "weapons": [],
            "vehicles": [],
            "animals": []
        }
        # ... more scenes
    ],
    "total_scenes": 14,
    "scenes_with_background": 14
}
```

## Adding a New Format

### Step 1: Create a New Parser Class

Inherit from `ScheduleParser` and implement the `parse()` method:

```python
class ProductionHubScheduleParser(ScheduleParser):
    """Parser for ProductionHub shooting schedule format"""

    def __init__(self):
        super().__init__()
        self.show_title = None
        self.board = None

    def parse(self, pdf_path: str) -> Dict:
        """Parse ProductionHub PDF"""
        with pdfplumber.open(pdf_path) as pdf:
            # Extract metadata from first page
            first_page = pdf.pages[0].extract_text()
            self._extract_metadata(first_page)

            # Parse all pages
            all_text = ""
            for page in pdf.pages:
                all_text += page.extract_text() + "\n"

            scenes = self._extract_scenes(all_text)

            return {
                "metadata": {
                    "format": "ProductionHub",
                    "show_title": self.show_title,
                    "board": self.board,
                    "total_pages": len(pdf.pages)
                },
                "scenes": scenes,
                "total_scenes": len(scenes),
                "scenes_with_background": len([s for s in scenes if s.get("background_actors")])
            }

    def _extract_metadata(self, text: str):
        """Extract show title, board, etc."""
        # Implement ProductionHub-specific metadata extraction
        pass

    def _extract_scenes(self, text: str) -> List[Dict]:
        """Extract all scenes from text"""
        # Implement ProductionHub-specific scene extraction
        pass

    def _parse_scene(self, block: str, scene_num: str) -> Optional[Dict]:
        """Parse a single scene block"""
        # Implement ProductionHub-specific scene parsing
        pass
```

### Step 2: Update `parse_shooting_schedule()`

Add the new format to the auto-detection and routing:

```python
def parse_shooting_schedule(pdf_path: str, format_type: str = "auto") -> Dict:
    """
    Main entry point for parsing any shooting schedule
    """

    # Auto-detect format if needed
    if format_type == "auto":
        with pdfplumber.open(pdf_path) as pdf:
            first_page = pdf.pages[0].extract_text()

            if "shamelstudio.com" in first_page.lower():
                format_type = "shamel"
            elif "productionhub" in first_page.lower():
                format_type = "productionhub"  # ← NEW
            elif "moviemagic" in first_page.lower():
                format_type = "moviemagic"     # ← NEW
            else:
                format_type = "shamel"  # Fallback

    # Route to appropriate parser
    if format_type.lower() == "shamel":
        parser = ShamelScheduleParser()
    elif format_type.lower() == "productionhub":
        parser = ProductionHubScheduleParser()  # ← NEW
    elif format_type.lower() == "moviemagic":
        parser = MovieMagicScheduleParser()    # ← NEW
    else:
        raise ValueError(f"Unknown schedule format: {format_type}")

    return parser.parse(pdf_path)
```

## Implementation Tips

### Parsing Strategy

1. **Extract metadata first** (show title, board, etc.) from early pages
2. **Split into scene blocks** using scene headers as delimiters
3. **For each scene block:**
   - Extract metadata (set, time, duration, synopsis)
   - Find the "Background Actors" section
   - Parse background actor entries (count + description)
   - Extract any props/wardrobe/weapons mentioned

### Handling Messy Data

Production schedules vary widely in format. Don't try to be perfect:

- **Use pragmatic regex** instead of perfect parsing
- **Filter aggressively** — ignore lines that don't match expected patterns
- **Prioritize key data** — scene number, background descriptions, counts
- **Store raw text** in `notes` field for manual review if needed

### Testing

```python
# Quick test
if __name__ == "__main__":
    pdf_path = "sample_schedule.pdf"
    result = parse_shooting_schedule(pdf_path, format_type="productionhub")
    
    print(f"Show: {result['metadata']['show_title']}")
    print(f"Total scenes: {result['total_scenes']}")
    print(f"Scenes with BG: {result['scenes_with_background']}")
    
    for scene in result['scenes'][:5]:
        print(f"\nScene {scene['scene_id']}: {scene['set']}")
        for bg in scene['background_actors']:
            print(f"  - {bg['count']}x {bg['type']}")
```

## Server Integration

The parser is exposed via the `/parse-schedule` endpoint:

```bash
# Example usage
curl -X POST http://localhost:8765/parse-schedule \
  -H "Content-Type: application/pdf" \
  --data-binary @schedule.pdf
```

Returns:

```json
{
  "ok": true,
  "data": {
    "metadata": { ... },
    "scenes": [ ... ],
    "total_scenes": 14,
    "scenes_with_background": 14
  }
}
```

## Next Steps

- [ ] Add ProductionHub format support
- [ ] Add Movie Magic Scheduling format support
- [ ] Add Scriptmate support
- [ ] Create UI for selecting schedule format on upload
- [ ] Add error handling for malformed/unusual schedules
- [ ] Cache parsed schedules for quick re-import

## Questions?

For issues or new format requests, see the BG Board project spec.
