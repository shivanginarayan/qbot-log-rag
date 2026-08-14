from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import re
from typing import Dict, List, Optional, Set, Tuple
import zipfile
from xml.etree import ElementTree as ET

from ament_index_python.packages import get_package_share_directory

try:
    from rapidfuzz import fuzz, process
except ImportError:  # pragma: no cover - runtime fallback when dependency is absent
    fuzz = None
    process = None


@dataclass(frozen=True)
class DirectoryEntry:
    kind: str
    title: str
    location: str
    floor: str
    description: str
    notes: str


@dataclass(frozen=True)
class DirectoryMatch:
    query: str
    entry: Optional[DirectoryEntry]
    score: float
    reason: str
    alternatives: Tuple[str, ...] = ()


class SeicDirectory:
    def __init__(self, workbook_path: Optional[str] = None):
        if workbook_path is None:
            workbook_path = self._default_workbook_path()

        self.workbook_path = workbook_path
        self.entries = self._load_entries()
        self.entry_aliases = self._build_entry_aliases()

    def find_best_match(self, user_query: str) -> DirectoryMatch:
        cleaned_query = self._normalize_query(user_query)
        if not cleaned_query:
            return DirectoryMatch(query='', entry=None, score=0.0, reason='empty_query')

        exact_entry = self._match_by_room_number(cleaned_query)
        if exact_entry is not None:
            return DirectoryMatch(
                query=cleaned_query,
                entry=exact_entry,
                score=1.0,
                reason='room_number',
            )

        alias_entry = self._match_by_alias(cleaned_query)
        if alias_entry is not None:
            return DirectoryMatch(
                query=cleaned_query,
                entry=alias_entry,
                score=0.99,
                reason='alias',
            )

        ranked = self._rank_candidates(cleaned_query)
        if not ranked:
            return DirectoryMatch(
                query=cleaned_query,
                entry=None,
                score=0.0,
                reason='no_candidates',
            )

        best_score, best_entry = ranked[0]
        alternatives = tuple(entry.title for _, entry in ranked[1:4])
        runner_up_gap = best_score - ranked[1][0] if len(ranked) > 1 else best_score

        if best_score < 0.72 or runner_up_gap < 0.06:
            return DirectoryMatch(
                query=cleaned_query,
                entry=None,
                score=best_score,
                reason='low_confidence',
                alternatives=(best_entry.title,) + alternatives,
            )

        return DirectoryMatch(
            query=cleaned_query,
            entry=best_entry,
            score=best_score,
            reason='fuzzy_match',
            alternatives=alternatives,
        )

    def build_response(self, match: DirectoryMatch) -> str:
        if match.entry is None:
            if match.alternatives:
                suggestions = ', '.join(match.alternatives[:3])
                return (
                    f"Sorry, I couldn't confidently match {match.query}. "
                    f'The closest public directory entries are {suggestions}.'
                )
            return f"Sorry, I couldn't find {match.query} in the public SEIC directory."

        entry = match.entry
        if entry.kind == 'room':
            detail = f'{entry.title} is on floor {entry.floor}'
            if entry.description:
                detail += f' and is a {entry.description}'
            return detail + '.'

        if entry.kind == 'person':
            detail = f'{entry.title} is listed at {entry.location}'
            if entry.floor:
                detail += f' on floor {entry.floor}'
            return detail + '.'

        detail = f'{entry.title} is listed at {entry.location}'
        if entry.floor and entry.floor != '0':
            detail += f' on floor {entry.floor}'
        if (
            'not publicly listed' in entry.location.lower()
            or 'room not publicly listed' in entry.location.lower()
        ):
            detail += ', but a public room number is not listed'
        return detail + '.'

    def expression_for_match(self, match: DirectoryMatch) -> str:
        if match.entry is None:
            return 'confused'
        return 'happy'

    def _load_entries(self) -> List[DirectoryEntry]:
        shared_strings = []
        namespace = {'a': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

        with zipfile.ZipFile(self.workbook_path) as workbook:
            if 'xl/sharedStrings.xml' in workbook.namelist():
                root = ET.fromstring(workbook.read('xl/sharedStrings.xml'))
                for item in root.findall('a:si', namespace):
                    text = ''.join(node.text or '' for node in item.findall('.//a:t', namespace))
                    shared_strings.append(text)

            room_rows = self._sheet_rows(workbook, 'sheet2.xml', shared_strings, namespace)
            people_rows = self._sheet_rows(workbook, 'sheet3.xml', shared_strings, namespace)
            named_rows = self._sheet_rows(workbook, 'sheet4.xml', shared_strings, namespace)

        entries = []

        for row in room_rows[1:]:
            if len(row) < 8 or not row[0]:
                continue
            entries.append(
                DirectoryEntry(
                    kind='room',
                    title=row[0],
                    location=row[0],
                    floor=row[1],
                    description=row[2],
                    notes=row[7],
                )
            )

        for row in people_rows[1:]:
            if len(row) < 8 or not row[0]:
                continue
            entries.append(
                DirectoryEntry(
                    kind='person',
                    title=row[0],
                    location=row[3],
                    floor=row[4],
                    description=row[1],
                    notes=row[5],
                )
            )

        for row in named_rows[1:]:
            if len(row) < 6 or not row[0]:
                continue
            entries.append(
                DirectoryEntry(
                    kind='space',
                    title=row[0],
                    location=row[1],
                    floor=row[2],
                    description=row[3],
                    notes='',
                )
            )

        entries.extend(self._custom_entries())
        return entries

    def _custom_entries(self) -> List[DirectoryEntry]:
        return [
            DirectoryEntry(
                kind='person',
                title='Michael Cabrera',
                location='SEIC 404',
                floor='4',
                description='Office',
                notes='Alias: Micheal Cabrera',
            ),
            DirectoryEntry(
                kind='person',
                title='Milton Tinoco',
                location='SEIC 313',
                floor='3',
                description='Office',
                notes='',
            ),
            DirectoryEntry(
                kind='person',
                title='Kevin Honag',
                location='SEIC 313',
                floor='3',
                description='Office',
                notes='',
            ),
            DirectoryEntry(
                kind='person',
                title='Ryan',
                location='SEIC 313',
                floor='3',
                description='Office',
                notes='',
            ),
        ]

    def _build_entry_aliases(self) -> Dict[DirectoryEntry, Set[str]]:
        aliases: Dict[DirectoryEntry, Set[str]] = {}

        for entry in self.entries:
            entry_aliases = {
                self._normalize_text(entry.title),
                self._normalize_text(entry.location),
            }
            if entry.description and entry.kind != 'room':
                entry_aliases.add(self._normalize_text(entry.description))

            room_code = self._room_code(entry.title) or self._room_code(entry.location)
            if room_code:
                entry_aliases.update(
                    {
                        self._normalize_text(room_code),
                        self._normalize_text(f'seic {room_code}'),
                        self._normalize_text(f'room {room_code}'),
                    }
                )

            if entry.kind == 'person':
                last_name = entry.title.split()[-1]
                entry_aliases.update(
                    {
                        self._normalize_text(last_name),
                        self._normalize_text(f'professor {last_name}'),
                        self._normalize_text(f'doctor {last_name}'),
                        self._normalize_text(f'dr {last_name}'),
                    }
                )
                for alias in re.split(r'[;,]', entry.notes):
                    alias = alias.strip()
                    if alias.lower().startswith('alias:'):
                        alias = alias.split(':', 1)[1].strip()
                    normalized_alias = self._normalize_text(alias)
                    if normalized_alias:
                        entry_aliases.add(normalized_alias)

            if 'makerspace' in self._normalize_text(entry.title):
                entry_aliases.add(self._normalize_text('makerspace'))

            if 'machine shop' in self._normalize_text(entry.title):
                entry_aliases.add(self._normalize_text('machine shop'))
                entry_aliases.add(self._normalize_text('stockroom'))

            if entry.kind == 'space':
                entry_aliases.update(self._space_alias_variants(entry.title))

            aliases[entry] = {
                alias for alias in entry_aliases if alias and not self._is_generic_alias(alias)
            }

        return aliases

    def _default_workbook_path(self) -> str:
        candidates = []

        try:
            share_dir = Path(get_package_share_directory('milton_final_project'))
            candidates.append(share_dir / 'data' / 'seic_public_directory_with_schedule.xlsx')
            candidates.append(share_dir / 'data' / 'seic_public_directory.xlsx')
        except Exception:
            pass

        here = Path(__file__).resolve()
        candidates.append(here.parents[3] / 'data' / 'seic_public_directory_with_schedule.xlsx')
        candidates.append(here.parents[3] / 'data' / 'seic_public_directory.xlsx')
        candidates.append(here.parents[2] / 'data' / 'seic_public_directory_with_schedule.xlsx')
        candidates.append(here.parents[2] / 'data' / 'seic_public_directory.xlsx')

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        return str(candidates[0])

    def _sheet_rows(self, workbook, sheet_file: str, shared_strings, namespace):
        root = ET.fromstring(workbook.read(f'xl/worksheets/{sheet_file}'))
        rows = []

        for row in root.findall('a:sheetData/a:row', namespace):
            values = []
            for cell in row.findall('a:c', namespace):
                inline = cell.find('a:is', namespace)
                value = cell.find('a:v', namespace)
                cell_type = cell.attrib.get('t')

                if inline is not None:
                    text = ''.join(node.text or '' for node in inline.findall('.//a:t', namespace))
                    values.append(text)
                elif value is None:
                    values.append('')
                elif cell_type == 's':
                    values.append(shared_strings[int(value.text)])
                else:
                    values.append(value.text or '')
            rows.append(values)

        return rows

    def _normalize_query(self, text: str) -> str:
        return self._normalize_text(text)

    def _normalize_text(self, text: str) -> str:
        text = text.strip().lower()
        text = text.replace('&', ' and ')
        text = re.sub(r'\bscience\s+and\s+engineering\s+innovation\s+center\b', 'seic', text)
        text = re.sub(r'\bscience\s+and\s+engineering\b', 'seic', text)
        text = re.sub(r'\bscience\s+engineering\b', 'seic', text)
        text = re.sub(r'\bsci(?:ence)?\b', 'science', text)
        text = re.sub(r'\bengr\b', 'engineering', text)
        text = re.sub(r'\bprof\b', 'professor', text)
        text = re.sub(r'\bdr\b\.?', 'doctor', text)
        text = re.sub(
            r'\b(can you|could you|please|help me|i need|looking for|take me to|where is|'
            r'find|locate|go to|show me|tell me|bring me to)\b',
            ' ',
            text,
        )
        text = re.sub(r'[^a-z0-9]+', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        room_match = re.search(r'\b(?:seic\s*)?(\d{3}[a-z]?)\b', text)
        if room_match:
            return f'seic {room_match.group(1)}'

        return text

    def _match_by_room_number(self, query: str) -> Optional[DirectoryEntry]:
        room_code = self._room_code(query)
        if not room_code:
            return None

        target_room = f'SEIC {room_code}'
        for entry in self.entries:
            if entry.title.upper() == target_room or entry.location.upper() == target_room:
                return entry
        return None

    def _match_by_alias(self, query: str) -> Optional[DirectoryEntry]:
        for entry, aliases in self.entry_aliases.items():
            if query in aliases:
                return entry
        return None

    def _rank_candidates(self, query: str) -> List[Tuple[float, DirectoryEntry]]:
        ranked: List[Tuple[float, DirectoryEntry]] = []
        query_tokens = query.split()

        for entry, aliases in self.entry_aliases.items():
            score = max(self._score_alias(query, alias, query_tokens) for alias in aliases)
            ranked.append((score, entry))

        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked

    def _score_alias(self, query: str, alias: str, query_tokens: List[str]) -> float:
        if not alias:
            return 0.0

        if query == alias:
            return 1.0

        if query in alias or alias in query:
            return 0.95

        alias_tokens = alias.split()
        overlap = len(set(query_tokens) & set(alias_tokens)) / max(1, len(set(query_tokens)))

        if process is not None and fuzz is not None:
            fuzzy_ratio = fuzz.ratio(query, alias) / 100.0
            partial_ratio = fuzz.partial_ratio(query, alias) / 100.0
            token_ratio = fuzz.token_set_ratio(query, alias) / 100.0
            return max(
                fuzzy_ratio * 0.35 + partial_ratio * 0.25 + token_ratio * 0.25 + overlap * 0.15,
                token_ratio * 0.92,
                partial_ratio * 0.88,
            )

        similarity = SequenceMatcher(None, query, alias).ratio()
        fuzzy_token_similarity = self._best_token_alignment(query_tokens, alias_tokens)
        return max(
            similarity * 0.55 + overlap * 0.15 + fuzzy_token_similarity * 0.30,
            overlap * 0.90,
            fuzzy_token_similarity * 0.92,
        )

    def _best_token_alignment(self, query_tokens, candidate_tokens) -> float:
        if not query_tokens or not candidate_tokens:
            return 0.0

        scores = []
        for query_token in query_tokens:
            token_scores = [
                SequenceMatcher(None, query_token, candidate_token).ratio()
                for candidate_token in candidate_tokens
            ]
            scores.append(max(token_scores) if token_scores else 0.0)

        return sum(scores) / len(scores)

    def _room_code(self, text: str) -> Optional[str]:
        match = re.search(r'\b(?:seic\s*)?(\d{3}[a-z]?)\b', text, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1).upper()

    def _space_alias_variants(self, title: str) -> Set[str]:
        normalized_title = self._normalize_text(title)
        variants = set()

        if normalized_title.endswith(' lab') and ' and ' in normalized_title:
            prefix = normalized_title[:-4]
            for chunk in prefix.split(' and '):
                chunk = chunk.strip()
                if chunk:
                    variants.add(f'{chunk} lab')

        if normalized_title.endswith(' makerspace'):
            prefix = normalized_title[:-11].strip()
            if prefix:
                variants.add(prefix)

        return variants

    def _is_generic_alias(self, alias: str) -> bool:
        generic_aliases = {
            'lab',
            'classroom',
            'lecture hall',
            'study room',
            'office',
            'space',
        }
        return alias in generic_aliases or len(alias.split()) == 1 and alias in {'room', 'floor'}
