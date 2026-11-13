"""The user's permitted apostrophe variants are the same TBMM salutation."""
import re

from reading_validation import ReadingComparison
from recipient_validation import normalize


def salutation_text(text):
    # Normalize this suffix only; do not erase spelling errors or change names.
    return re.sub(r"\bbaşkanlığı\s*['’‘ʼ]\s*na\b", 'başkanlığına', normalize(text))


def validate_salutation(check, reading, ocr, required):
    """Return the field alignment, retaining the exact source quote for display."""
    allowed = salutation_text(check.quote).rstrip(' .:') == salutation_text(required)
    if allowed and not check.reading_uncertain:
        # Lowercase headings can still fail the separate capitalization check.
        if check.kind == 'hitap' or not check.quote.islower():
            check.status = 'uygun'
            check.explanation = 'TBMM hitabı uygundur; kesme işaretli ve işaretsiz yazımlar kabul edilir.'
    return ReadingComparison(salutation_text(reading), salutation_text(ocr)).disagrees(
        salutation_text(check.quote))
