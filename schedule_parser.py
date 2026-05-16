"""
Universal PDF shooting schedule parser using heuristic pattern matching.

Rather than format-specific parsers, this engine:
1. Scans for universal markers (day numbers, scene headers, sections)
2. Uses fuzzy field matching for labels that vary by software
3. Implements fallback extraction strategies
4. Automatically adapts to unknown format variations

This approach solves the core problem: we don't need a new parser class for
every format variation. Instead, we detect patterns and adapt dynamically.
"""

import re
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import pdfplumber


@dataclass
class ParsedScene:
    """Standardized scene data extracted from any format."""
    scene_id: str
    int_ext: str = "INT"
    set: str = ""
    synopsis: str = ""
    duration: str = ""
    time_of_day: str = ""
    shooting_day: Optional[int] = None
    background_actors: List[Dict] = None
    # Non-BG columns captured by ColumnAwareScheduleParser; not surfaced in UI yet.
    cast: List[Dict] = None
    props: List[str] = None
    vehicles: List[str] = None
    wardrobe: List[str] = None
    animals: List[str] = None
    set_dressing: List[str] = None
    additional_labor: List[str] = None
    visual_effects: List[str] = None
    stunts: List[str] = None
    weapons: List[str] = None
    special_equipment: List[str] = None
    notes_section: List[str] = None
    camera: List[str] = None
    makeup: List[str] = None
    art_department: List[str] = None
    misc: List[str] = None
    grip: List[str] = None
    lighting: List[str] = None
    sound: List[str] = None
    episodic_cast: List[str] = None

    def __post_init__(self):
        for attr in (
            'background_actors', 'cast', 'props', 'vehicles', 'wardrobe',
            'animals', 'set_dressing', 'additional_labor', 'visual_effects',
            'stunts', 'weapons', 'special_equipment', 'notes_section',
            'camera', 'makeup', 'art_department', 'misc', 'grip',
            'lighting', 'sound', 'episodic_cast',
        ):
            if getattr(self, attr) is None:
                setattr(self, attr, [])


class HeuristicScheduleParser:
    """
    Format-agnostic shooting schedule parser using pattern matching.
    Works with any production software format without pre-built parsers.
    """

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.text = ""
        self.lines = []
        self.raw_pages = []
        self.detected_patterns = {}

    def parse(self) -> Dict:
        """Parse PDF and return standardized schedule data."""

        # Step 1: Extract raw text and structure
        self._extract_text()

        # Step 2: Detect shooting days (universal marker across all formats)
        shooting_days = self._detect_shooting_days()

        # Step 3: Parse scenes WITH their background actors
        scenes = self._extract_scenes_with_actors(shooting_days)

        # Convert to dicts
        scene_dicts = [asdict(scene) for scene in scenes]

        # Build metadata
        metadata = {
            "show_title": self._extract_show_title(),
            "format": "auto-detected",
            "total_days": len(shooting_days),
            "detected_patterns": self.detected_patterns
        }

        return {
            "scenes": scene_dicts,
            "metadata": metadata
        }

    def _extract_text(self):
        """Extract text from PDF with line preservation."""
        with pdfplumber.open(self.pdf_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                full_text += page_text + "\n"
                self.raw_pages.append(page_text)

            self.text = full_text
            self.lines = [line for line in full_text.split('\n') if line.strip()]

    def _detect_shooting_days(self) -> Dict[int, int]:
        """
        Detect all shooting days using multiple heuristics.
        Returns: {day_number: text_position}
        """
        shooting_days = {}
        self.detected_patterns = {}

        # Pattern 1: "End of Day X" or "End of DAY X" (Shamel, ProductionHub, Cineapse)
        day_pattern = r'(?:End of )?(?:Day|DAY)\s+(\d+)'
        day_matches = list(re.finditer(day_pattern, self.text))
        if day_matches:
            self.detected_patterns['end_of_day_markers'] = len(day_matches)
            for match in day_matches:
                day_num = int(match.group(1))
                if day_num not in shooting_days:
                    shooting_days[day_num] = match.start()
            return shooting_days

        # Pattern 2: "Shoot Day #X" or "Shoot Day X" (Standard formats)
        shoot_pattern = r'Shoot\s+Day\s+#?(\d+)'
        shoot_matches = list(re.finditer(shoot_pattern, self.text, re.IGNORECASE))
        if shoot_matches:
            self.detected_patterns['shoot_day_markers'] = len(shoot_matches)
            for match in shoot_matches:
                day_num = int(match.group(1))
                if day_num not in shooting_days:
                    shooting_days[day_num] = match.start()
            return shooting_days

        # Pattern 3: "Block X" (Cineapse, similar formats)
        block_pattern = r'\bBlock\s+(\d+)\b'
        block_matches = list(re.finditer(block_pattern, self.text))
        if block_matches:
            self.detected_patterns['block_markers'] = len(block_matches)
            for idx, match in enumerate(block_matches, 1):
                shooting_days[idx] = match.start()
            return shooting_days

        # Pattern 4: Fallback - infer from page breaks
        if len(self.raw_pages) > 1:
            self.detected_patterns['page_break_inference'] = len(self.raw_pages)
            for idx, page in enumerate(self.raw_pages, 1):
                if page.strip():
                    shooting_days[idx] = 0
            return shooting_days

        # At least one day
        return {1: 0}

    def _extract_scenes_with_actors(self, shooting_days: Dict) -> List[ParsedScene]:
        """
        Extract scenes with their background actors by finding complete scene blocks.
        Handles multiple format variations:
          - Shamel:   "INT. Scene 15 1/8 Pages" then "Set: LOCATION ..."
          - Standard: "INT LOCATION Stage 25 ..." then "Scene # 7 synopsis"
        """
        scenes = []
        current_day = 1

        # First pass: identify all scene header positions
        scene_headers = []

        for i, line in enumerate(self.lines):
            # Track day changes
            day_match = re.search(r'End of Day (\d+)|Shoot\s+Day\s+#?\s*(\d+)', line, re.IGNORECASE)
            if day_match:
                day_num = day_match.group(1) or day_match.group(2)
                current_day = int(day_num)

            # --- Format A: Shamel "INT. Scene X" or "EXT. Scene X" ---
            shamel_match = re.match(r'^\s*(INT|EXT|INT/EXT|I/E)\.\s+Scene\s+(\d+[A-Za-z]*)', line)
            if shamel_match:
                int_ext = shamel_match.group(1)
                scene_id = shamel_match.group(2)

                # Look ahead for "Set: LOCATION"
                set_name = ""
                synopsis = ""
                for j in range(i + 1, min(i + 4, len(self.lines))):
                    set_match = re.match(r'^\s*Set:\s*(.+?)\s+(?:Time of Day:|Duration:|$)', self.lines[j])
                    if set_match:
                        set_name = set_match.group(1).strip()
                    syn_match = re.match(r'^\s*Synopsis:\s*(.+?)(?:\s+Unit:|$)', self.lines[j])
                    if syn_match:
                        synopsis = syn_match.group(1).strip()

                scene_headers.append((i, int_ext, set_name, scene_id, synopsis, current_day))
                continue

            # --- Format B: Standard "INT LOCATION Stage N" then "Scene # X" ---
            standard_match = re.match(r'^\s*(INT|EXT|INT/EXT|I/E)\s+([A-Z][A-Z\s\-]+?)\s+(?:Stage|stage)\s+\d+', line)
            if standard_match:
                int_ext = standard_match.group(1)
                set_name = standard_match.group(2).strip()

                if i + 1 < len(self.lines):
                    next_line = self.lines[i + 1]
                    scene_num_match = re.match(r'^\s*Scene\s*#\s*(\d+[A-Za-z]*)\s*,?\s*(.+)?', next_line, re.IGNORECASE)
                    if scene_num_match:
                        scene_id = scene_num_match.group(1)
                        synopsis = (scene_num_match.group(2) or "").strip()
                        scene_headers.append((i, int_ext, set_name, scene_id, synopsis, current_day))

        # Second pass: extract background actors within each scene's block
        for scene_idx, (line_idx, int_ext, set_name, scene_id, synopsis, day) in enumerate(scene_headers):
            block_start = line_idx
            block_end = scene_headers[scene_idx + 1][0] if scene_idx + 1 < len(scene_headers) else len(self.lines)

            scene_block_text = '\n'.join(self.lines[block_start:block_end])
            bg_actors = self._extract_background_actors_from_block(scene_block_text)

            if bg_actors:
                scene = ParsedScene(
                    scene_id=scene_id,
                    int_ext=int_ext,
                    set=set_name,
                    synopsis=synopsis,
                    shooting_day=day,
                    background_actors=bg_actors
                )
                scenes.append(scene)

        self.detected_patterns['scenes_found'] = len(scenes)
        return scenes

    def _extract_background_actors_from_block(self, block_text: str) -> List[Dict]:
        """
        Extract background actors from a single scene block.

        Handles PDF column-merging where cast member info (e.g. '1 LIZ') appears
        on the same line as BG descriptions ('OLD PEOPLE') and props ('watch gun')
        because the original PDF had them in adjacent columns.
        """
        bg_actors = []

        # Find "Background Actors" section — grab everything after it in the block
        # (block already ends at next scene, so no need for terminators)
        bg_match = re.search(r'Background Actors[^\n]*\n(.*)', block_text, re.IGNORECASE | re.DOTALL)
        if not bg_match:
            return bg_actors

        bg_section = bg_match.group(1)

        for line in bg_section.split('\n'):
            line = line.strip()
            if not line or len(line) < 2:
                continue

            # Skip header labels, page footers, and metadata lines
            if re.match(r'^(Cast|Props|Notes|Wardrobe|Weapons|Vehicles|Animals|Powered by|Printed|\d+/\d+)', line, re.IGNORECASE):
                continue
            if re.match(r'^(End of Day|Pages:|Est\. time)', line, re.IGNORECASE):
                continue
            if line.startswith('(') or line.startswith('4/') or line.startswith('http'):
                continue

            # --- Strip leading cast member pattern: "NUMBER CASTNAME ..." ---
            # Cast members have a number then a single ALL-CAPS name (or name+parens)
            # e.g. "1 LIZ", "2 JERRY", "100 STUNT COORD", "101 RICH (STUNTS)"
            remainder = line
            count = 1
            cast_strip = re.match(r'^(\d+)\s+([A-Z]{2,}(?:\s+\([^)]+\))?)\s+(.*)', line)
            if cast_strip:
                potential_cast_num = int(cast_strip.group(1))
                potential_cast_name = cast_strip.group(2).strip()
                remainder = cast_strip.group(3).strip()

                # If the "cast name" is actually a pure prop/stunt, skip
                if potential_cast_name.lower() in {'stunt coord', 'stunt coordinator'}:
                    continue

                # If remainder starts with a number, that's the actual BG count
                count_match = re.match(r'^(\d+)\s+(.+)', remainder)
                if count_match:
                    count = int(count_match.group(1))
                    remainder = count_match.group(2).strip()
                # Otherwise count stays at 1 (implied)

            elif re.match(r'^(\d+)\s+', line):
                # No cast name — the number is the actual BG count
                count_match = re.match(r'^(\d+)\s+(.+)', line)
                if count_match:
                    count = int(count_match.group(1))
                    remainder = count_match.group(2).strip()

            if not remainder or remainder.startswith('('):
                continue

            # Clean remainder: strip prop/wardrobe keywords and character names
            clean_type, props = self._split_type_and_props(remainder)

            if clean_type:
                bg_actors.append({
                    "count": count,
                    "type": clean_type,
                    "notes": "",
                    "props": props
                })

        return bg_actors

    def _split_type_and_props(self, text: str) -> tuple:
        """
        Separate the BG actor type from props/wardrobe in a merged string.
        e.g. 'OLD PEOPLE watch gun' → ('OLD PEOPLE', ['watch', 'gun'])
        e.g. 'PARTY GUEST hand gun' → ('PARTY GUEST', ['hand gun'])
        """
        prop_keywords = {
            'photo', 'photos', 'umbrella', 'robe', 'robes', 'suitcase', 'suitcases',
            'phone', 'phones', 'pen', 'pens', 'paper', 'papers', 'gun', 'guns',
            'knife', 'knives', 'weapon', 'weapons', 'car', 'cars', 'medications',
            'medication', 'pills', 'pill', 'tequila', 'shots', 'shot', 'bottle',
            'bottles', 'cigarette', 'cigarettes', 'cigars', 'cigar', 'ice', 'pack',
            'water', 'drinks', 'drink', 'watch', 'hat', 'shirt', 'gear', 'outfit',
            'bike', 'demerol', 'scotch', 'whiskey', 'napkin', 'sandwich', 'sandwiches',
            'sunglasses', 'frisbee', 'axe', 'dollar', 'bill', 'underwear', 'tandem',
            'hand', 'fleek', 'pony', 'clipboard', 'brace', 'fishing', 'neck', 'blood',
            'vial', 'needle', 'twenty', 'beach'
        }

        # Proper character names only — not relational words like "daughter"
        character_names = {
            'jerry', 'liz', 'rizzo', 'benny', 'gladys', 'hudson', 'susan', 'marvin',
            'butch', 'roger', 'pete', 'coord', 'double', 'stunt', 'tommy', 'craig',
            'pepper', 'rich', 'hazel', 'dmitri', 'kelly', 'bruce', 'ron', 'joyce',
            'alex', 'val', 'matt', 'serena'
        }

        words = text.split()
        type_words = []
        prop_words = []
        in_props = False

        for word in words:
            wl = word.lower().rstrip('.,')
            if wl in character_names:
                continue  # skip character names entirely
            if wl in prop_keywords:
                in_props = True
            if in_props:
                prop_words.append(word)
            else:
                type_words.append(word)

        final_type = ' '.join(type_words).strip()
        # Remove trailing numbers/commas from PDF formatting artifacts
        final_type = re.sub(r'[,\s]+\d+$', '', final_type).strip()

        # Reject if it's too short or is just a single prop word
        if len(final_type) < 3 or final_type.lower() in prop_keywords:
            return None, []

        return final_type, prop_words


    def _clean_actor_type(self, actor_str: str) -> str:
        """Remove character names and keep only role descriptions."""

        character_names = {
            'jerry', 'rizzo', 'benny', 'liz', 'dmitri', 'hazel', 'marty',
            'stunt', 'coord', 'double', 'mom', 'dad', 'grandpa', 'grandma'
        }

        cleaned = actor_str.strip()

        # Remove character names from beginning
        words = cleaned.split()
        filtered_words = []
        for word in words:
            word_lower = word.lower().rstrip(',')
            if word_lower not in character_names and not word.isdigit():
                filtered_words.append(word)

        cleaned = ' '.join(filtered_words).strip()

        # Remove known props
        props_to_remove = ['photo', 'beach photo', 'hotties', 'tennis', 'of']
        for prop in props_to_remove:
            cleaned = re.sub(rf'\b{prop}\b', '', cleaned, flags=re.IGNORECASE)

        cleaned = ' '.join(cleaned.split()).strip()

        return cleaned if len(cleaned) > 2 else ""

    def _extract_props_from_string(self, actor_str: str) -> List[str]:
        """Extract props mentioned in description."""
        props = []
        prop_keywords = ['photo', 'gun', 'hat', 'watch', 'robe', 'shirt', 'coat', 'weapon']

        for keyword in prop_keywords:
            if keyword.lower() in actor_str.lower():
                props.append(keyword.title())

        return props

    def _extract_show_title(self) -> str:
        """Extract show title from PDF."""
        # Look for common title patterns
        title_patterns = [
            r'(?:Title|Show|Production):\s*(.+?)(?:\n|$)',
            r'SHOOTING SCHEDULE\s*[—-]\s*(.+?)(?:\n|$)',
            r'^([A-Z][A-Za-z\s]+?)\s+(?:Shooting|Schedule)',
        ]

        for pattern in title_patterns:
            match = re.search(pattern, self.text, re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1).strip()

        # Fallback: first non-empty line
        for line in self.lines[:5]:
            if len(line) > 5 and not any(x in line.lower() for x in ['day', 'scene', 'page']):
                return line.strip()

        return "Unknown Production"


class ColumnAwareScheduleParser:
    """
    Layout-aware parser. Uses pdfplumber's word-coordinate output to detect
    column header rows, derive column anchors by x-position, and route content
    words to the correct column. Handles four format families seen so far:
    Shamel, Movie Magic (multi-col), Movie Magic (simple), and Hierarchical.

    Falls through to HeuristicScheduleParser if a page has no recognized
    column headers at all.

    See PARSER_COORDINATION.md for the full design rationale.
    """

    # Canonical key -> aliases (case-insensitive match). Order matters within
    # an alias list: multi-word aliases must come first so they win greedy match.
    LABEL_VOCAB = {
        'cast': ['Cast Members', 'Cast'],
        # Episodic Cast (Movie Magic old-desktop): lists cast members tagged
        # by episode. Recognized as a non-BG label so its content (e.g.
        # "gd2.3.Santi") doesn't bleed into background_actors.
        'episodic_cast': ['Episodic Cast'],
        'background_actors': ['Featured Background Actors', 'Background Actors',
                               'Featured Background', 'Background', 'Extras', 'BG'],
        'props': ['Props'],
        'wardrobe': ['Wardrobe', 'Costumes'],
        'vehicles': ['Vehicles', 'Picture Cars'],
        'animals': ['Animals'],
        'set_dressing': ['Set Dressing', 'Greens'],
        'additional_labor': ['Additional Labor', "Add'l Labor"],
        'visual_effects': ['Visual Effects', 'VFX', 'SPFX', 'Special Effects'],
        'stunts': ['Stunts'],
        'weapons': ['Weapons'],
        'special_equipment': ['Special Equipment'],
        'notes_section': ['Notes'],
        'camera': ['Camera'],
        'makeup': ['Make Up', 'Makeup', 'Hair', 'Makeup & Hair', 'Make Up & Hair'],
        'art_department': ['Art Department'],
        'misc': ['Miscellaneous'],
        'grip': ['Grip'],
        # Lighting / electric / sound — sometimes appear as Shamel sub-headers
        # next to Additional Labor; absent from vocab they break header
        # detection and surrounding content gets routed to neighbouring columns.
        'lighting': ['Lighting', 'Electric'],
        'sound': ['Sound'],
    }
    # Tokens that appear inside header rows as structural noise — not labels
    # themselves, but should not disqualify the row from being a header.
    # - Column-structure markers: '#', 'name', 'members'
    # - Scene-header keywords that share the y-row with column headers in
    #   formats like ProductionHub (Block2 #2): 'INT NURSE STATION Day Cast
    #   Members Props' is all on one visual row.
    # - Lower-cased before comparison; punctuation trimmed.
    HEADER_NOISE_TOKENS = {
        '#', 'name', 'members',
        'int', 'ext', 'int/ext', 'i/e',
        'day', 'night', 'dawn', 'dusk', 'morning', 'afternoon', 'evening',
        'stage', 'pgs', 'pg', 'page', 'pages',
    }
    # When a single-label sub-section column is active (no multi-column system),
    # content this many points to the right of the label's x1 is considered
    # outside the column and dropped. Prevents far-right content from being
    # vacuumed into the active column.
    SUBSECTION_RIGHT_MARGIN = 200.0
    # Labels that are NOT background performers but live in the same layout —
    # we still recognize them so words in those columns don't bleed into BG.
    # Non-BG list: everything in LABEL_VOCAB except 'background_actors'.

    # Y-tolerance for grouping words into a line (points). Must be tight
    # enough that distinct visual rows separated by ~3pt (some Movie Magic
    # layouts) stay separate, but loose enough to handle subpixel y variance
    # within a single row.
    Y_TOL = 1.5
    # If the gap between content rows under an active column system exceeds this
    # (points), the column system is considered closed — protects against
    # footers and unrelated content at the bottom of the page being routed into
    # the last live column system.
    SECTION_BREAK_GAP = 30.0

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.warnings: List[str] = []
        self.format_family = 'unknown'
        # Build lowercase alias -> (canonical, word_count) lookup.
        self._alias_lookup = {}
        for canon, aliases in self.LABEL_VOCAB.items():
            for a in aliases:
                self._alias_lookup[a.lower()] = (canon, len(a.split()))
        # Track whether ANY page used column-aware extraction successfully.
        self._any_columns_found = False

    # ------------------------------------------------------------------ parse

    def parse(self) -> Dict:
        scenes: List[ParsedScene] = []
        with pdfplumber.open(self.pdf_path) as pdf:
            # Format-family detection from footer text on first few pages.
            self.format_family = self._detect_format_family(pdf)
            show_title = self._extract_show_title(pdf)

            # First pass: determine the FINAL "End of Day N" marker across the
            # whole document. Anything assigned to a day > final_day is treated
            # as boneyard (omitted strips, stock footage, etc.) — not a real
            # shoot day.
            final_day: Optional[int] = None
            for page in pdf.pages:
                pt = page.extract_text() or ''
                for m in re.finditer(r'End\s+(?:of\s+)?Day\s+#?\s*(\d+)', pt, flags=re.IGNORECASE):
                    d = int(m.group(1))
                    if final_day is None or d > final_day:
                        final_day = d

            current_day = 1
            for page_idx, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ''
                # "Shoot Day # N" header (Movie Magic): sets current day for the
                # whole page. Position-independent.
                shoot_day_match = re.search(r'Shoot\s+Day\s+#?\s*(\d+)', page_text, flags=re.IGNORECASE)
                if shoot_day_match:
                    current_day = int(shoot_day_match.group(1))

                # Find "End of Day N" markers and their string positions on this
                # page. extract_text returns top-to-bottom order, so a string
                # position serves as a proxy for visual y. A scene whose
                # marker-text-position is AFTER an "End of Day N" position
                # belongs to day N+1, not the previous day. This handles the
                # case where the day-break sits at the TOP of a page (Shamel
                # quirk seen in BTB) — the old logic assigned those scenes to
                # the previous day because the marker was processed AFTER scene
                # extraction.
                page_day_breaks = [
                    (m.start(), int(m.group(1)))
                    for m in re.finditer(r'End\s+of\s+Day\s+(\d+)', page_text, flags=re.IGNORECASE)
                ]

                # Find scene marker positions in page_text by scene_id. Matches
                # the same patterns _find_scene_markers uses (Shamel, Movie
                # Magic). First occurrence per scene_id wins.
                _sid = r'(\d+(?:\.\d+)?[A-Za-z]*)'
                scene_text_pos: Dict[str, int] = {}
                for m in re.finditer(
                    r'(?:INT|EXT|INT/EXT|I/E)\.?\s+Scene\s+' + _sid + r'\b'
                    r'|(?:^|\n)\s*-?\s*Scene\s*#?:?\s*' + _sid + r'\b'
                    r'|\bSc\.?\s+' + _sid + r'\b',
                    page_text, flags=re.IGNORECASE
                ):
                    sid = m.group(1) or m.group(2) or m.group(3)
                    if sid and sid not in scene_text_pos:
                        scene_text_pos[sid] = m.start()

                page_scenes = self._parse_page(page, page_idx)
                for s in page_scenes:
                    if s.shooting_day is not None:
                        continue
                    spos = scene_text_pos.get(s.scene_id)
                    # Default to current_day (matches prior behavior).
                    day = current_day
                    if spos is not None and page_day_breaks:
                        # Pick the day implied by the LATEST break above this scene.
                        for brk_pos, brk_day in page_day_breaks:
                            if spos > brk_pos:
                                day = brk_day + 1
                    s.shooting_day = day
                scenes.extend(page_scenes)

                # Carry the latest end-of-day marker forward to subsequent pages.
                if page_day_breaks:
                    last_day = max(d for _, d in page_day_breaks)
                    current_day = last_day + 1

        # Split into in-schedule scenes and boneyard. A scene is boneyard if it
        # falls past the final "End of Day N" marker. If no end-of-day markers
        # exist (e.g. Movie Magic with no end markers), final_day is None and
        # all scenes stay in-schedule.
        boneyard: List[ParsedScene] = []
        in_schedule: List[ParsedScene] = []
        for s in scenes:
            if final_day is not None and s.shooting_day is not None and s.shooting_day > final_day:
                boneyard.append(s)
            else:
                in_schedule.append(s)

        return {
            'scenes': [asdict(s) for s in in_schedule],
            'boneyard': [asdict(s) for s in boneyard],
            'metadata': {
                'show_title': show_title,
                'format': f'column-aware:{self.format_family}',
                'format_family': self.format_family,
                'format_display_name': format_display_name(self.format_family),
                'total_scenes': len(in_schedule),
                'boneyard_count': len(boneyard),
                'final_day': final_day,
                'columns_detected': self._any_columns_found,
                'warnings': self.warnings,
            },
        }

    # ------------------------------------------------------------- per-page

    def _parse_page(self, page, page_idx: int) -> List[ParsedScene]:
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
        if not words:
            return []
        lines = self._group_lines(words)
        if not lines:
            return []

        # Find scene markers on this page; each marker starts a scene block.
        scene_markers = self._find_scene_markers(lines)
        if not scene_markers:
            return []  # Title page or unrelated; skip silently.

        scenes: List[ParsedScene] = []
        for i, marker in enumerate(scene_markers):
            block_start = marker['line_idx']
            block_end = scene_markers[i + 1]['line_idx'] if i + 1 < len(scene_markers) else len(lines)
            block_lines = lines[block_start:block_end]
            scene = self._parse_scene_block(block_lines, marker)
            if scene is not None:
                scenes.append(scene)
        return scenes

    def _parse_scene_block(self, block_lines: List[Dict], marker: Dict) -> Optional[ParsedScene]:
        """Walk a scene block; maintain an 'active columns' state; route content."""
        scene = ParsedScene(
            scene_id=marker['scene_id'],
            int_ext=marker.get('int_ext', 'INT'),
        )

        # Extract metadata (set, synopsis, time of day) from the scene's header area —
        # the lines before the first column-header row.
        active_columns: List[Dict] = []
        # Per-column accumulator of (line_top, [phrase_strings]) so we keep row order.
        column_rows: Dict[str, List[List[str]]] = {}
        last_content_top: Optional[float] = None

        def reset_columns(cols):
            active_columns.clear()
            active_columns.extend(cols)
            for c in cols:
                column_rows.setdefault(c['canon'], [])

        metadata_text_lines: List[str] = []

        for line in block_lines:
            labels = self._find_labels_in_line(line)
            if self._is_column_header_row(labels, line):
                # Establish a new column system. Earlier columns flush; new ones start.
                reset_columns(labels)
                last_content_top = line['top']
                self._any_columns_found = True
                continue
            if len(labels) == 1 and self._is_sub_section_header(labels[0], line):
                # Single-label line at left → sub-section header (Margo pattern).
                # Treat it as a 1-column system spanning the whole line width.
                reset_columns([{
                    'x0': 0.0,
                    'x1': labels[0]['x1'],
                    'canon': labels[0]['canon'],
                    'text': labels[0]['text'],
                }])
                last_content_top = line['top']
                continue

            # Margo pattern: leftmost-column label appears on a row that also has
            # content in OTHER columns. The label re-canonicalizes the leftmost
            # column for subsequent rows; this row's other-column content is
            # still routed normally.
            if len(labels) == 1 and active_columns:
                label = labels[0]
                leftmost = min(active_columns, key=lambda c: c['x0'])
                if abs(label['x0'] - leftmost['x0']) <= 20:
                    leftmost['canon'] = label['canon']
                    column_rows.setdefault(label['canon'], [])
                    # Remove the label's own words from the line before routing,
                    # so 'Background' itself doesn't become a BG entry.
                    label_word_xs = {w['x0'] for w in line['words'][:label['word_span']]}
                    line = {
                        **line,
                        'words': [w for w in line['words'] if w['x0'] not in label_word_xs],
                    }
                    if not line['words']:
                        last_content_top = line['top'] if 'top' in line else last_content_top
                        continue

            if not active_columns:
                # Pre-header lines are scene metadata.
                metadata_text_lines.append(line['text'])
                continue

            # Section-break detection: if there's a large vertical gap since the
            # last content row, the column system is stale (footer / next-scene).
            if last_content_top is not None and (line['top'] - last_content_top) > self.SECTION_BREAK_GAP:
                active_columns.clear()
                metadata_text_lines.append(line['text'])
                continue

            # Route this content line to columns.
            routed = self._route_line_to_columns(line, active_columns)
            row_has_content = False
            for canon, words_in_col in routed.items():
                if not words_in_col:
                    continue
                phrase = ' '.join(w['text'] for w in words_in_col).strip()
                if phrase:
                    column_rows.setdefault(canon, []).append([phrase, line['top']])
                    row_has_content = True
            if row_has_content:
                last_content_top = line['top']

        # Populate scene fields from column_rows.
        self._fill_scene_from_columns(scene, column_rows)
        # Scene metadata from pre-header text.
        self._fill_scene_metadata(scene, metadata_text_lines, marker)
        return scene

    # ----------------------------------------------------- line/label helpers

    def _group_lines(self, words: List[Dict]) -> List[Dict]:
        """Group words into lines by y-position. Returns lines sorted top-to-bottom."""
        words_sorted = sorted(words, key=lambda w: (w['top'], w['x0']))
        lines: List[Dict] = []
        for w in words_sorted:
            if lines and abs(w['top'] - lines[-1]['_anchor_top']) <= self.Y_TOL:
                lines[-1]['words'].append(w)
            else:
                lines.append({'_anchor_top': w['top'], 'top': w['top'], 'words': [w]})
        for line in lines:
            line['words'].sort(key=lambda w: w['x0'])
            line['text'] = ' '.join(w['text'] for w in line['words'])
            del line['_anchor_top']
        return lines

    def _find_labels_in_line(self, line: Dict) -> List[Dict]:
        """Return label matches in a line: [{x0, x1, canon, text}, ...]"""
        words = line['words']
        matches: List[Dict] = []
        i = 0
        while i < len(words):
            matched = None
            # Try longest aliases first (greedy multi-word match).
            for window in (3, 2, 1):
                if i + window > len(words):
                    continue
                phrase = ' '.join(w['text'] for w in words[i:i + window])
                lookup = self._alias_lookup.get(phrase.lower())
                if lookup:
                    canon, _ = lookup
                    matched = {
                        'x0': words[i]['x0'],
                        'x1': words[i + window - 1]['x1'],
                        'canon': canon,
                        'text': phrase,
                        'word_span': window,
                    }
                    break
            if matched:
                matches.append(matched)
                i += matched['word_span']
            else:
                i += 1
        return matches

    def _is_column_header_row(self, labels: List[Dict], line: Dict) -> bool:
        """A real column-header row requires:
          - 2+ distinct labels at 2+ distinct x-positions
          - Labels span ≥50pt horizontally (rejects content lines where label
            words happen to appear close together, like 'Beach BG props')
          - Non-label words on the line are either zero OR all are recognized
            header-noise tokens like '#', 'Name' (handles 'Cast # Name Extras
            Miscellaneous' Movie Magic variants).
        """
        if len(labels) < 2:
            return False
        canons = {l['canon'] for l in labels}
        xs = sorted({round(l['x0'], 1) for l in labels})
        if len(canons) < 2 or len(xs) < 2:
            return False
        if (xs[-1] - xs[0]) < 50.0:
            return False
        # All non-label words must be header-noise.
        words_in_labels = sum(l['word_span'] for l in labels)
        non_label_count = len(line['words']) - words_in_labels
        if non_label_count == 0:
            return True
        # Identify non-label words by their text. Approximate: any word whose
        # lowercased text is in HEADER_NOISE_TOKENS counts as noise.
        noise_count = sum(
            1 for w in line['words']
            if w['text'].lower().rstrip('.,:') in self.HEADER_NOISE_TOKENS
        )
        # Subtract label words from noise_count if a label happens to contain
        # a noise token (rare — none of our labels do today, but be safe).
        return noise_count >= non_label_count

    def _is_sub_section_header(self, label: Dict, line: Dict) -> bool:
        """
        A line containing exactly the label and nothing else (or a multi-word
        label spanning the whole line). Catches Margo's 'Background',
        'Costumes', 'Make Up' sub-headers. Rejects 'BG surfboards' style
        content lines that happen to start with a label word.
        """
        return label['word_span'] == len(line['words'])

    def _route_line_to_columns(self, line: Dict, columns: List[Dict]) -> Dict[str, List[Dict]]:
        """Partition a content line's words by which column range they fall in.

        Inter-column boundary = midpoint between the PREVIOUS label's right edge (x1)
        and the CURRENT label's left edge (x0). This places the boundary inside
        the visible whitespace gap between columns, so content can extend in
        either direction past its column header without crossing into the
        neighbor's territory.
        """
        if not columns:
            return {}
        sorted_cols = sorted(columns, key=lambda c: c['x0'])
        ranges = []
        for i, col in enumerate(sorted_cols):
            if i == 0:
                x_min = 0.0  # Leftmost column captures everything to the left.
            else:
                prev = sorted_cols[i - 1]
                x_min = (prev['x1'] + col['x0']) / 2.0
            if i + 1 < len(sorted_cols):
                nxt = sorted_cols[i + 1]
                x_max = (col['x1'] + nxt['x0']) / 2.0
            elif len(sorted_cols) == 1:
                # Single-column sub-section: cap right edge so far-right content
                # (other unlabeled columns) doesn't get vacuumed into this one.
                x_max = col['x1'] + self.SUBSECTION_RIGHT_MARGIN
            else:
                x_max = float('inf')
            ranges.append((x_min, x_max, col['canon']))

        result: Dict[str, List[Dict]] = {canon: [] for _, _, canon in ranges}
        for w in line['words']:
            # Route by word CENTER, not x0. The leftmost-edge approach
            # mis-routes words that happen to begin a hair before a column
            # boundary — e.g. BTB Sc 20 "piece" has x0=245.7 vs a BG/Props
            # boundary at 245.85, putting "piece of scrap plywood" into BG
            # instead of Props. Center routing places each word on the side
            # where its bulk visually sits.
            wx = (w['x0'] + w['x1']) / 2.0
            for x_min, x_max, canon in ranges:
                if x_min <= wx < x_max:
                    result[canon].append(w)
                    break
        return result

    # -------------------------------------------------------- scene assembly

    def _fill_scene_from_columns(self, scene: ParsedScene, column_rows: Dict[str, List]):
        """Convert per-column row strings into typed scene fields."""
        # Cast: parse "N NAME" or "N. NAME" → {number, name}
        for entry, _top in column_rows.get('cast', []):
            cast_member = self._parse_cast_entry(entry)
            if cast_member:
                scene.cast.append(cast_member)

        # BG: parse "xN TYPE" / "N TYPE" / "TYPE" → {count, type, notes, props}
        for entry, _top in column_rows.get('background_actors', []):
            bg = self._parse_bg_entry(entry)
            if bg:
                scene.background_actors.append(bg)

        # All other columns: flat string list, one entry per row.
        flat_field_map = {
            'props': 'props',
            'vehicles': 'vehicles',
            'wardrobe': 'wardrobe',
            'animals': 'animals',
            'set_dressing': 'set_dressing',
            'additional_labor': 'additional_labor',
            'visual_effects': 'visual_effects',
            'stunts': 'stunts',
            'weapons': 'weapons',
            'special_equipment': 'special_equipment',
            'notes_section': 'notes_section',
            'camera': 'camera',
            'makeup': 'makeup',
            'art_department': 'art_department',
            'lighting': 'lighting',
            'sound': 'sound',
            'episodic_cast': 'episodic_cast',
        }
        for canon, field in flat_field_map.items():
            for entry, _top in column_rows.get(canon, []):
                cleaned = entry.strip()
                if cleaned:
                    getattr(scene, field).append(cleaned)

    def _parse_cast_entry(self, entry: str) -> Optional[Dict]:
        """Parse '1 OPTERS' / '23.KELLY' / '500(K).5.BODHI (5)' → {number, name}."""
        s = entry.strip()
        # Common shapes: "N. NAME", "N NAME", "N.NAME"
        m = re.match(r'^(\d+)\s*\.?\s*([A-Z][A-Z0-9 \-\'\.\(\)/]+?)(?:\s+\(\d+\))?\s*$', s)
        if m:
            try:
                return {'number': int(m.group(1)), 'name': m.group(2).strip()}
            except ValueError:
                pass
        # Fallback: just store the raw string under name with number=None.
        return {'number': None, 'name': s}

    def _parse_bg_entry(self, entry: str) -> Optional[Dict]:
        """Parse 'x2 Bikini Girls (20 Y.O.)' / '10 PARTY GUESTS' / '30 YEAR OLD MOM' /
        'Movers (4)' / 'Fifth Graders (25)' / 'Fisherman'."""
        s = entry.strip()
        if not s:
            return None
        # Trailing (N) badge: Movie Magic old-desktop format puts the count in
        # parentheses AFTER the role. E.g. "Movers (4)", "Fifth Graders (25)".
        # Require pure digits inside the parens so descriptive parentheticals
        # like "(20 Y.O.)" or "(K)" don't get treated as counts.
        m = re.match(r'^(.+?)\s*\((\d+)\)\s*$', s)
        if m:
            cleaned = self._clean_bg_type(m.group(1).strip())
            if cleaned is not None:
                return {'count': int(m.group(2)), 'type': cleaned, 'notes': '', 'props': []}
        # Leading xN badge (definitely a count).
        m = re.match(r'^x\s*(\d+)\s+(.+)$', s, flags=re.IGNORECASE)
        if m:
            cleaned = self._clean_bg_type(m.group(2).strip())
            if cleaned is None:
                return None
            return {'count': int(m.group(1)), 'type': cleaned, 'notes': '', 'props': []}
        # Leading bare integer: count only if not followed by an age/year word.
        m = re.match(r'^(\d+)\s+(.+)$', s)
        if m:
            rest = m.group(2).strip()
            first_word = rest.split()[0].upper().rstrip('.,')
            if first_word in {'YEAR', 'YEARS', 'YR', 'YRS', 'Y.O.', 'Y/O', 'YO'}:
                # "30 YEAR OLD MOM" — number is part of description.
                cleaned = self._clean_bg_type(s)
                return {'count': 1, 'type': cleaned or s, 'notes': '', 'props': []} if cleaned else None
            cleaned = self._clean_bg_type(rest)
            if cleaned is None:
                return None
            return {'count': int(m.group(1)), 'type': cleaned, 'notes': '', 'props': []}
        # No leading count → only accept if the string looks like a real BG role,
        # not column bleed from adjacent sections (e.g. "Hair" from a "Makeup & Hair"
        # column header, or "dust" from "covered in wood dust" in the makeup column).
        if self._looks_like_column_bleed(s):
            return None
        cleaned = self._clean_bg_type(s)
        if cleaned is None:
            return None
        return {'count': 1, 'type': cleaned, 'notes': '', 'props': []}

    # Annotation patterns that show up inside parentheses on Shamel schedules
    # but are notes about reuse / casting, not part of the BG type itself.
    _BG_ANNOTATION_KEYWORDS = ('reuse', 'see scene', 'same as', 'from before',
                               'continued', 'cont.', 'cont\'d', 'continues')

    def _clean_bg_type(self, t: str) -> Optional[str]:
        """Strip annotation parentheticals and reject obvious prop-leak entries.

        Returns the cleaned type, or None if the string should be dropped.
        Keeps real descriptors like '(20 Y.O.)' or '(K)' for minors which
        downstream code reads.
        """
        if not t:
            return None
        # Strip annotation-only parentheticals: "(reuse Drivers from before)",
        # "(see scene 12)", etc. Keep descriptive ones like "(20 Y.O.)", "(K)".
        def _drop_anno(match):
            inner = match.group(1).lower()
            if any(kw in inner for kw in self._BG_ANNOTATION_KEYWORDS):
                return ' '
            return match.group(0)
        cleaned = re.sub(r'\(([^)]*)\)', _drop_anno, t)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        # Reject license-plate / prop-like entries that contain ":"
        # (e.g. "plate: BG cars" — a license plate prop misrouted into BG).
        if ':' in cleaned:
            return None
        # Reject empty or single-symbol residue after cleanup.
        if len(cleaned) < 3 or not re.search(r'[A-Za-z]', cleaned):
            return None
        return cleaned

    def _looks_like_column_bleed(self, s: str) -> bool:
        """Reject single-token / non-BG-shaped strings that are almost certainly
        leakage from adjacent columns (makeup, notes, wardrobe, etc.)."""
        tokens = s.split()
        # Purely symbolic ("&", "+", "/")
        if not re.search(r'[A-Za-z]', s):
            return True
        # Single token: reject if it matches a known non-BG section label,
        # or is a single lowercase word (descriptive note fragment).
        if len(tokens) == 1:
            tok = tokens[0]
            if tok.lower() in self._alias_lookup and self._alias_lookup[tok.lower()][0] != 'background_actors':
                return True
            # "dust", "covered", "wood" — single lowercase tokens are not BG roles.
            if tok.islower() and not tok.startswith('('):
                return True
            # Single 1-2 letter token: not a BG role.
            if len(tok) < 3:
                return True
        # Multi-token: reject if the WHOLE string matches a non-BG label alias
        # (e.g. "Make Up", "Picture Cars"). Word-by-word match against the vocab.
        s_lower = s.lower().strip()
        for alias_lower, (canon, _) in self._alias_lookup.items():
            if canon != 'background_actors' and alias_lower == s_lower:
                return True
        return False

    # ---------------------------------------------- scene / format detection

    def _find_scene_markers(self, lines: List[Dict]) -> List[Dict]:
        """Find lines that mark a scene start.

        Patterns seen across formats:
          - 'Scene N' or 'Scene # N' or 'Scene #: N' (Shamel; Margo inline;
            Movie Magic old desktop). Scene IDs may include dots and letters
            (e.g. '98pt', '3.7pt', '4.1', '3.6PH').
          - 'Sc. N' or 'Sc N' (Movie Magic abbreviation)
          - 'INT/EXT LOCATION Stage N' header line (Movie Magic; comes BEFORE
            the 'Sc. N' line, so we prefer this when both exist for the same scene
            to get accurate block boundaries)
        """
        # Scene ID grammar accepts: optional letter prefix, digits, optional
        # .digits, optional letters. Examples: "12", "12A", "98pt", "3.7pt",
        # "4.1", "3.6PH", "A15", "FB2".
        # Multi-ID rows (Movie Magic old-desktop): the user opted to keep
        # comma-separated IDs as ONE combined scene_id, so we greedily match
        # "3.13, 14VO, 15VO" as a single ID. Single-ID rows fall through
        # to the simple form because the comma part is optional.
        _single = r'[A-Z]{0,2}\d+(?:\.\d+)?[A-Za-z]*'
        scene_id_re = r'(' + _single + r'(?:\s*,\s*' + _single + r')*)'

        markers: List[Dict] = []

        def add_marker(line_idx: int, scene_id: str, int_ext: str):
            # Dedupe: if two patterns matched within 4 lines of each other,
            # they're the same scene — keep the EARLIER line (so the block
            # starts at the true beginning).
            for m in markers:
                if m['scene_id'] == scene_id and abs(m['line_idx'] - line_idx) <= 4:
                    if line_idx < m['line_idx']:
                        m['line_idx'] = line_idx
                        m['int_ext'] = int_ext
                    return
            markers.append({'line_idx': line_idx, 'scene_id': scene_id, 'int_ext': int_ext})

        for i, line in enumerate(lines):
            text = line['text']

            # Pattern A: 'Scene N' or 'Scene # N' or 'Scene #: N'
            m = re.search(r'\bScene\s*#?:?\s*' + scene_id_re + r'\b', text)
            if m:
                scene_word_pos = text.lower().find('scene')
                if len(text[:scene_word_pos].split()) <= 3:
                    int_ext = self._find_int_ext_in_nearby_lines(lines, i)
                    # If the line immediately above is an INT/EXT scene header
                    # (Movie Magic old-desktop pattern), extend the block start
                    # backwards so metadata parsing sees the set/ToD info.
                    block_idx = self._extend_block_to_intext_above(lines, i)
                    add_marker(block_idx, m.group(1), int_ext)

            # Pattern B: 'Sc. N' or 'Sc N' (Movie Magic) — used as the
            # tagline beneath an INT/EXT header.
            m = re.search(r'\bSc\.?\s*' + scene_id_re + r'\b', text)
            if m and 'scene' not in text.lower():
                sc_pos = text.lower().find('sc')
                if len(text[:sc_pos].split()) <= 2:
                    int_ext = self._find_int_ext_in_nearby_lines(lines, i)
                    block_idx = self._extend_block_to_intext_above(lines, i)
                    add_marker(block_idx, m.group(1), int_ext)

            # Pattern C: 'INT/EXT LOCATION ... Stage N' header line. We register
            # this so the block starts at the right place even when a 'Scene #'
            # marker also exists below. Scene ID is not yet known here — we
            # only register if there's an immediately-following 'Sc. N' or
            # 'Scene #' that we can map to.
            int_ext_match = re.match(r'^\s*(INT/EXT|INT\.?|EXT\.?|I/E)\s+[A-Z]', text)
            if int_ext_match and re.search(r'\b(Stage|stage)\s+\d', text):
                # Look ahead up to 3 lines for the scene number.
                for j in range(i, min(i + 4, len(lines))):
                    look = lines[j]['text']
                    sm = re.search(r'\bScene\s*#?:?\s*' + scene_id_re + r'\b', look) or \
                         re.search(r'\bSc\.?\s*' + scene_id_re + r'\b', look)
                    if sm:
                        add_marker(i, sm.group(1), int_ext_match.group(1).rstrip('.'))
                        break

        markers.sort(key=lambda m: m['line_idx'])
        return markers

    def _find_int_ext_in_nearby_lines(self, lines: List[Dict], scene_line_idx: int) -> str:
        """Look in the scene's line and the previous 2 lines for INT/EXT."""
        for j in range(max(0, scene_line_idx - 2), min(len(lines), scene_line_idx + 2)):
            m = re.search(r'\b(INT/EXT|INT\.?|EXT\.?|I/E)\b', lines[j]['text'])
            if m:
                return m.group(1).rstrip('.')
        return 'INT'

    def _extend_block_to_intext_above(self, lines: List[Dict], scene_line_idx: int) -> int:
        """If the line(s) immediately above the scene marker start with
        INT/EXT (Movie Magic old-desktop pattern), return that earlier index
        so the parser's metadata pass sees the inline scene header. Otherwise
        return scene_line_idx unchanged.
        """
        for j in range(scene_line_idx - 1, max(-1, scene_line_idx - 3), -1):
            if j < 0:
                break
            txt = lines[j]['text'].strip()
            if re.match(r'^(INT/EXT|INT|EXT|I/E)\b', txt, flags=re.IGNORECASE):
                return j
            # Stop if we hit something that isn't likely a scene header
            # continuation (e.g. blank, "Cast Members ...", "End of Day").
            if txt:
                break
        return scene_line_idx

    def _fill_scene_metadata(self, scene: ParsedScene, metadata_lines: List[str], marker: Dict):
        joined = '\n'.join(metadata_lines)
        # ── Shamel / Movie Magic (new) labeled format: "Set: NAME", "Time of Day:" etc.
        # Word boundary before "Set:" so we don't match "Sunset:" inside a day
        # header line like "DAY 2 - FRI... Sunset: 8:04pm".
        m = re.search(r'\bSet:\s*(.+?)(?=\s+Time\s+of\s+Day:|\s+Duration:|\s+Script\s+Pages?:|\n|$)',
                      joined, flags=re.IGNORECASE)
        if m:
            scene.set = m.group(1).strip()
        # Synopsis
        m = re.search(r'Synopsis:\s*(.+?)(?=\s+Unit:|\s+Script\s+Pages?:|\n|$)',
                      joined, flags=re.IGNORECASE)
        if m:
            scene.synopsis = m.group(1).strip()
        # Time of Day
        m = re.search(r'Time\s+of\s+Day:\s*(.+?)(?=\s+Duration:|\s+Unit:|\n|$)',
                      joined, flags=re.IGNORECASE)
        if m:
            scene.time_of_day = m.group(1).strip()

        # ── Movie Magic old-desktop format: inline scene header on its own line
        # "INT/EXT SET ToD ScriptDay [Pages] pgs [Unit]"
        # Followed by: "Scene #: ID synopsis ..."
        # Only fires if the labeled format above didn't fill these fields.
        if not scene.set:
            self._try_parse_mm_old_desktop_metadata(scene, metadata_lines)

    # Time-of-day words seen in Movie Magic old-desktop format. Order/case
    # matters less than exhaustiveness — anything not in this list will be
    # absorbed into the set name, which is the wrong end of the boundary.
    _MM_TOD_WORDS = (
        'Day', 'Night', 'Morning', 'Morn', 'Dawn', 'Dusk', 'Evening',
        'Afternoon', 'Continuous', 'Sunset', 'Sunrise', 'Magic Hour',
        'Pre-Dawn', 'Pre-Dusk', 'Twilight', 'Midnight',
    )

    def _try_parse_mm_old_desktop_metadata(self, scene: ParsedScene, metadata_lines: List[str]):
        """Parse Movie Magic old-desktop scene headers.

        Two layout variants in the wild:

        (1) Separate INT/EXT line ABOVE the Scene # line (RAMBLER):
              EXT CRCC - First Tee Box Morn 15 3/8 pgs Wood Ranch
              Scene #: 3.19pt Santi steps up to the first tee. THWACK!

        (2) INLINE on the Scene # line itself (MM_B2, AA 201_202):
              Scene # 606 INT The Shack - Basement Studio Day 7/8
              Dr. Teeth cycles through several phases ...

        Both: split into INT/EXT + SET + TIME_OF_DAY by locating a known ToD
        word; everything between INT/EXT and the ToD is the set name. The
        synopsis is the line immediately following the scene header.
        """
        # Find candidate header text — either a standalone INT/EXT line OR
        # the inline portion of a "Scene # ID INT/EXT SET ToD ..." line.
        header_text = None
        scene_line = None
        scene_line_idx = -1
        for idx, ln in enumerate(metadata_lines):
            stripped = ln.strip()
            if header_text is None and re.match(r'^(INT/EXT|INT|EXT|I/E)\b', stripped, re.IGNORECASE):
                # Variant (1): standalone INT/EXT line
                header_text = stripped
            elif scene_line is None and re.match(r'^Scene\s*#', stripped, re.IGNORECASE):
                scene_line = stripped
                scene_line_idx = idx
                # Variant (2): inline. Strip the "Scene # ID" prefix and treat
                # the remainder as if it were a standalone INT/EXT line.
                if header_text is None:
                    inline = re.match(
                        r'^Scene\s*#?:?\s*\S+\s+(?P<rest>(?:INT/EXT|INT|EXT|I/E)\b.*)$',
                        stripped, flags=re.IGNORECASE
                    )
                    if inline:
                        header_text = inline.group('rest')

        if not header_text:
            return

        # Locate the ToD word in the header. Longest matches first so
        # "Magic Hour" wins over "Hour" if either were in the vocab.
        tod_re = '|'.join(sorted((re.escape(w) for w in self._MM_TOD_WORDS),
                                 key=len, reverse=True))
        m = re.search(r'^(?P<ie>INT/EXT|INT|EXT|I/E)\b\.?\s+(?P<set>.+?)\s+(?P<tod>'
                      + tod_re + r')\b', header_text, flags=re.IGNORECASE)
        if not m:
            return
        scene.int_ext = m.group('ie').upper().rstrip('.')
        scene.set = m.group('set').strip()
        scene.time_of_day = m.group('tod').strip()

        # Synopsis: variant (1) puts it on the Scene #: line AFTER the ID.
        # Variant (2) puts it on the NEXT line after the Scene # line.
        if scene_line:
            # Try synopsis-after-id (variant 1) first.
            sm = re.search(
                r'^Scene\s*#?:?\s*\S+\s+(?:INT/EXT|INT|EXT|I/E)\b.*?\d+(?:/\d+)?\s*$',
                scene_line, flags=re.IGNORECASE
            )
            if sm is None:
                # Variant 1 fallback: synopsis follows the ID directly (no inline IE).
                sm2 = re.search(
                    r'^Scene\s*#?:?\s*[\w.,/\s]+?\s+(?P<syn>[A-Z(].+)$',
                    scene_line
                )
                if sm2:
                    scene.synopsis = sm2.group('syn').strip()
            # Variant 2: synopsis is the line right after the scene header.
            if not scene.synopsis and scene_line_idx >= 0 and scene_line_idx + 1 < len(metadata_lines):
                cand = metadata_lines[scene_line_idx + 1].strip()
                # Don't grab the column-header continuation or noise.
                if cand and not re.match(r'^(Cast|Background|Notes|Props|Wardrobe|End\s+Day|Shoot\s+Day|DAY\s+\d|Sunrise|STAGE|Printed)', cand, re.IGNORECASE):
                    scene.synopsis = cand

    # Heuristic: page is a "cast roster only" (no scene content) when it has
    # many "N.Name" lines and lacks any scene-marker / INT/EXT hints. CSC's
    # 403_ShootSked_Blue.pdf is the canonical case — page 1 lists every cast
    # member then scenes start on page 2.
    @staticmethod
    def _looks_like_cast_roster(text: str) -> bool:
        if not text:
            return False
        # Bail early if scene markers are present — definitely not roster-only.
        if re.search(r'\bScene\s*#', text, flags=re.IGNORECASE):
            return False
        if re.search(r'^\s*(?:INT|EXT|INT/EXT|I/E)\b', text, flags=re.IGNORECASE | re.MULTILINE):
            return False
        lines = [ln for ln in text.split('\n') if ln.strip()]
        if not lines:
            return False
        roster_lines = sum(
            1 for ln in lines
            if re.search(r'\b\d+\.[A-Z]', ln)
        )
        return roster_lines / max(1, len(lines)) > 0.5

    def _detect_format_family(self, pdf) -> str:
        """Quick sniff of vendor signature from text.

        Aligned with CSC's internal taxonomy (PARSER_COORDINATION.md
        'Terminology correction'): the bulk of real-world schedules are
        Movie Magic variants. Strings used here are CSC-compatible to
        make cross-project comparison easy:

          shamel        — Shamel Studio
          mm_oneliner   — Movie Magic — One-Liner (compact export)
          mm_legacy     — Movie Magic — Legacy/old-desktop (Scene # ID inline
                          INT/EXT SET ToD — MM_B2, AA 201_202, RAMBLER style)
          mm_standard   — Movie Magic — Standard (labeled Cast Members/Props
                          sections — 217, GB2, AmAuto, etc.)
          unknown       — couldn't classify

        Cast-roster-only first pages (403_ShootSked_Blue pattern) are
        transparently skipped so format detection looks at the real schedule
        content that follows.
        """
        try:
            # Pull up to the first 3 pages, skipping any roster-only ones.
            page_texts = []
            for p in pdf.pages[:3]:
                t = p.extract_text() or ''
                if self._looks_like_cast_roster(t):
                    continue
                page_texts.append(t)
                if len(page_texts) >= 2:
                    break
            text = '\n'.join(page_texts)
        except Exception:
            return 'unknown'
        t = text.lower()
        if 'shamelstudio.com' in t:
            return 'shamel'
        # One-Liner: explicit label in title/header text. CSC sees ~7% of
        # corpus as oneliner.
        if 'one-liner' in t or 'one liner' in t or 'oneliner' in t:
            return 'mm_oneliner'
        # Legacy: the inline-on-Scene-line format. Cheap test: look for
        # "Scene #: <id> <INT/EXT>" pattern within the first couple pages.
        if re.search(r'Scene\s*#:?\s*[\w.,]+\s+(?:INT|EXT|INT/EXT|I/E)\b',
                     text, flags=re.IGNORECASE):
            return 'mm_legacy'
        # Default Movie Magic when there's no specific signal but the
        # document looks MM-ish (most files in the wild).
        if ('movie magic' in t or 'mm scheduling' in t
                or 'shooting schedule' in t
                or re.search(r'Cast\s+Members', text)):
            return 'mm_standard'
        return 'unknown'


    def _extract_show_title(self, pdf) -> str:
        """Take the largest-font centered title text from page 1 if possible."""
        try:
            page = pdf.pages[0]
            text = page.extract_text() or ''
        except Exception:
            return 'Unknown Production'
        # First non-empty line that isn't a section label or date.
        for line in text.split('\n'):
            s = line.strip()
            if not s:
                continue
            if re.match(r'^\d', s):
                continue
            if any(k in s.lower() for k in ('schedule', 'shooting', 'board:', 'page')):
                # The combined "Show Name - SHOOTING SCHEDULE" line is fine; strip suffix.
                return re.split(r'\s+-\s+', s, maxsplit=1)[0].strip()
            return s
        return 'Unknown Production'


# Human-readable name for a format-family string. Mirrors CSC's
# `format_display_name()` so both projects show the same label to users.
def format_display_name(family: str) -> str:
    return {
        'shamel': 'Shamel Studio',
        'mm_standard': 'Movie Magic — Standard',
        'mm_oneliner': 'Movie Magic — One-Liner',
        'mm_legacy': 'Movie Magic — Legacy',
        'unknown': 'Unknown format',
    }.get(family, family)


class WrongDocumentTypeError(Exception):
    """Raised when an uploaded PDF is detected as something other than a
    shooting schedule (e.g. a Breakdown Sheet, Day Out of Days, or cast list).
    The server handler converts this to a clear user-facing message."""
    def __init__(self, doc_type: str, message: str = ''):
        self.doc_type = doc_type
        self.message = message or f"This appears to be a {doc_type}, not a shooting schedule."
        super().__init__(self.message)


# Lightweight content-type guard: scan first couple pages for telltale headers
# that identify the document as something OTHER than a shooting schedule.
# Returns (doc_type, message) or (None, None) when the file looks like a real
# schedule. CSC's `Superstore 03020 BLUE Shooting Schedule 2.11.18.pdf` is the
# canonical Breakdown Sheet case — filename says "Shooting Schedule" but the
# content has a `Breakdown Sheet` header.
def detect_non_schedule_doc_type(pdf_path: str):
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            text = ''
            for p in pdf.pages[:2]:
                text += (p.extract_text() or '') + '\n'
    except Exception:
        return (None, None)
    t = text.lower()
    if 'breakdown sheet' in t:
        return ('Movie Magic Breakdown Sheet',
                'This is a Breakdown Sheet (one page per scene with prop/wardrobe '
                'details), not a shooting schedule. Upload the schedule PDF instead.')
    # Day Out of Days reports — common confusion point.
    if 'day out of days' in t or re.search(r'\bDOOD\b', text):
        # Be conservative: schedules sometimes mention DOOD in passing.
        # Require it as a header (top-of-page) to flag.
        first_lines = '\n'.join(text.split('\n')[:5]).lower()
        if 'day out of days' in first_lines or 'dood' in first_lines.split():
            return ('Day Out of Days report',
                    'This is a Day Out of Days report (cast schedule grid), '
                    'not a shooting schedule. Upload the schedule PDF instead.')
    return (None, None)


def parse_shooting_schedule(pdf_path: str, format_type: str = "auto") -> Dict:
    """
    Parse any shooting schedule PDF format.

    Primary path: ColumnAwareScheduleParser — uses word coordinates and column
    detection. Fallback: HeuristicScheduleParser — text-based, used only when
    the primary path finds no recognizable column headers anywhere in the PDF.

    Returns standardized schedule data ready for BG Board conversion.

    Raises WrongDocumentTypeError when the input is detected as something
    other than a schedule (Breakdown Sheet, Day Out of Days, etc.).
    """
    # Content-type guard FIRST — reject non-schedule documents with a clear
    # message rather than parsing them as empty schedules.
    doc_type, msg = detect_non_schedule_doc_type(pdf_path)
    if doc_type:
        raise WrongDocumentTypeError(doc_type, msg)

    # Primary path: column-aware.
    column_parser = ColumnAwareScheduleParser(pdf_path)
    column_result = column_parser.parse()

    # Fall through to heuristic ONLY if column-aware found nothing useful:
    # no column headers AND no scenes. If it found scenes but no columns, its
    # output (scenes with empty BG/cast lists) is still better than the
    # heuristic's text-based pattern matching for novel formats.
    needs_fallback = (
        not column_result['metadata'].get('columns_detected')
        and len(column_result['scenes']) == 0
    )
    if needs_fallback:
        heuristic = HeuristicScheduleParser(pdf_path)
        heuristic_result = heuristic.parse()
        heuristic_result['metadata']['format'] = (
            f"heuristic-fallback ({heuristic_result['metadata'].get('format', 'auto-detected')})"
        )
        heuristic_result['metadata'].setdefault('format_family', 'unknown')
        heuristic_result['metadata'].setdefault(
            'format_display_name',
            format_display_name(heuristic_result['metadata']['format_family'])
        )
        heuristic_result.setdefault('boneyard', [])
        return heuristic_result

    column_result.setdefault('boneyard', [])
    return column_result
