import re


class RobotInterpreter:
    """Normalize free-form requests into a lookup-friendly destination string."""

    _ROOM_PATTERN = re.compile(r'\b(?:seic\s*)?(\d{3}[a-z]?)\b', flags=re.IGNORECASE)
    _LEADING_PHRASES = (
        'can you tell me where',
        'can you show me where',
        'can you help me find',
        'can you help me get to',
        'could you tell me where',
        'could you help me find',
        'i am looking for',
        'i m looking for',
        'i need',
        'i need to find',
        'i need to go to',
        'take me to',
        'bring me to',
        'where can i find',
        'where do i find',
        'where is',
        'where s',
        'find',
        'locate',
        'go to',
        'show me',
        'help me find',
        'help me get to',
    )

    _FILLER_WORDS = re.compile(
        r'\b('
        r'please|the|a|an|building|room|office|location|place|destination|'
        r'to|for|at|in|on|near|thanks|thank you'
        r')\b',
        flags=re.IGNORECASE,
    )

    _ALIAS_REPLACEMENTS = (
        (re.compile(r'&'), ' and '),
        (re.compile(r'\bsci(?:ence)?\b', flags=re.IGNORECASE), 'science'),
        (re.compile(r'\bengr\b', flags=re.IGNORECASE), 'engineering'),
        (
            re.compile(
                r'\bscience\s+and\s+engineering\s+innovation\s+center\b',
                flags=re.IGNORECASE,
            ),
            'seic',
        ),
        (
            re.compile(r'\bscience\s+and\s+engineering\b', flags=re.IGNORECASE),
            'seic',
        ),
        (
            re.compile(r'\bscience\s+engineering\b', flags=re.IGNORECASE),
            'seic',
        ),
        (
            re.compile(r'\bprof\b', flags=re.IGNORECASE),
            'professor',
        ),
        (
            re.compile(r'\bdr\b\.?', flags=re.IGNORECASE),
            'doctor',
        ),
    )

    _THANKS_PATTERN = re.compile(
        r'\b(thank you|thanks|thank u|appreciate it|that helps)\b',
        flags=re.IGNORECASE,
    )
    _GOODBYE_PATTERN = re.compile(
        r'\b(bye|goodbye|see you|see ya|later|have a nice day|have a good day)\b',
        flags=re.IGNORECASE,
    )

    def is_conversation_end(self, user_text: str) -> bool:
        cleaned = ' '.join(user_text.strip().split())
        if not cleaned:
            return False
        return bool(
            self._THANKS_PATTERN.search(cleaned) or self._GOODBYE_PATTERN.search(cleaned)
        )

    def ending_response(self, user_text: str):
        cleaned = ' '.join(user_text.strip().split())
        if self._GOODBYE_PATTERN.search(cleaned):
            return {
                'expression': 'happy',
                'message': 'Goodbye. Come back if you need help finding another location.',
            }
        return {
            'expression': 'happy',
            'message': "You're welcome. Let me know if you need help with another location.",
        }

    def extract_target(self, user_text: str) -> str:
        cleaned = ' '.join(user_text.strip().split())
        if not cleaned:
            return ''

        room_match = self._ROOM_PATTERN.search(cleaned)
        if room_match:
            return f'SEIC {room_match.group(1).upper()}'

        normalized = cleaned.lower()
        for pattern, replacement in self._ALIAS_REPLACEMENTS:
            normalized = pattern.sub(replacement, normalized)

        normalized = normalized.replace('?', ' ').replace('.', ' ').replace(',', ' ')

        for phrase in self._LEADING_PHRASES:
            if normalized.startswith(phrase):
                normalized = normalized[len(phrase):].strip()
                break

        normalized = self._FILLER_WORDS.sub(' ', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip(" .'\"")

        return normalized or cleaned
