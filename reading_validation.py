"""Compare evidence locally; an unreadable area does not taint a whole page."""
import difflib
import re
import unicodedata

from recipient_validation import normalize


def evidence_present(text, quote):
    compact = lambda s: ' '.join(unicodedata.normalize('NFC', s).split())
    return bool(quote.strip()) and compact(quote) in compact(text)


def field_present(text, value):
    if not value.strip():
        return False
    pattern = r"(?<!\w)" + r"\s+".join(re.escape(w) for w in value.split()) + r"(?!\w)"
    return re.search(pattern, text) is not None


def tokens(text):
    return re.findall(r'\w+', normalize(text).translate(str.maketrans('çğıöşüâû', 'cgiosuau')))


def span(sequence, part):
    return next(spans(sequence, part), None)


def spans(sequence, part):
    if not part:
        return
    for start in range(len(sequence)-len(part)+1):
        if sequence[start:start+len(part)] == part:
            yield start, start+len(part)


class ReadingComparison:
    """Reuse one word alignment per page; evaluate only the cited evidence."""

    def __init__(self, vision, ocr):
        self.vision = tokens(vision)
        self.ocr = tokens(ocr)
        self._opcodes = None

    def disagrees(self, quote):
        regions = list(spans(self.vision, tokens(quote)))
        if not self.ocr or not regions or self.vision == self.ocr:
            return False
        if self._opcodes is None:
            self._opcodes = difflib.SequenceMatcher(
                a=self.vision, b=self.ocr, autojunk=False).get_opcodes()
        for low, high in regions:
            for index, (operation, start, end, other_start, other_end) in enumerate(self._opcodes):
                if operation == 'replace' and start < high and end > low:
                    return True
                if operation == 'insert' and low < start < high:
                    return True
                # A missing/fragmentary OCR layer is not a conflicting reading.
                # An omission surrounded by matching text in this evidence is.
                if operation == 'delete' and low < start and end < high:
                    before = self._opcodes[index-1] if index else None
                    after = self._opcodes[index+1] if index+1 < len(self._opcodes) else None
                    if before and after and before[0] == after[0] == 'equal':
                        return True
        return False


def serious_disagreement(vision, ocr, quote):
    """Only material word substitutions in the evidence, not whitespace or punctuation."""
    return ReadingComparison(vision, ocr).disagrees(quote)
