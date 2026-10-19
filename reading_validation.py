"""Compare evidence locally; an unreadable area does not taint a whole page."""
import difflib
import re

from recipient_validation import normalize


def evidence_present(text, quote):
    return bool(quote.strip()) and ' '.join(quote.split()) in ' '.join(text.split())


def field_present(text, value):
    if not value.strip():
        return False
    pattern = r"(?<!\w)" + r"\s+".join(re.escape(w) for w in value.split()) + r"(?!\w)"
    return re.search(pattern, text) is not None


def tokens(text):
    return re.findall(r'\w+', normalize(text).translate(str.maketrans('çğıöşüâû', 'cgiosuau')))


def span(sequence, part):
    if not part:
        return None
    for start in range(len(sequence)-len(part)+1):
        if sequence[start:start+len(part)] == part:
            return start, start+len(part)
    return None


def serious_disagreement(vision, ocr, quote):
    """Only material word substitutions in the evidence, not whitespace or punctuation."""
    a, b, q = tokens(vision), tokens(ocr), tokens(quote)
    if not b or not q or span(b, q) is not None:
        return False
    region = span(a, q)
    if region is None:
        return False
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for operation, start, end, other_start, other_end in matcher.get_opcodes():
        if operation == 'replace' and start < region[1] and end > region[0] and other_end > other_start:
            return True
    # A fragmentary/missing text layer is not itself evidence of a conflicting reading.
    return min(len(a), len(b)) >= 20 and matcher.ratio() < .55
