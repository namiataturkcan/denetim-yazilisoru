"""Conservative validation of explicit addressees against user-supplied rules."""
import re
import unicodedata


def normalize(text):
    text = unicodedata.normalize('NFC', text).translate(str.maketrans({'I': 'ı', 'İ': 'i', 'î': 'i', 'Î': 'i'})).lower()
    return ' '.join(text.split())


def extract_recipients(readings, recipients):
    candidates = []
    # Match explicit answer-request constructions, not a name anywhere in the PDF.
    letters = r'[A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû]+'
    name = rf'{letters}(?:\s+{letters}){{1,4}}?'
    ending = r"(?=\s+tarafından\b|[’'](?:nın|nin|nun|nün|ın|in|un|ün|na|ne)\b)"
    for page in readings:
        for title, expected in recipients.items():
            title_pattern = r'\s+'.join(re.escape(w) for w in title.split()).replace('Millî', 'Mill[îi]')
            pattern = rf'(?<!\w)(?P<title>{title_pattern})\s+(?:Sayın\s+)?(?P<name>{name}){ending}'
            for match in re.finditer(pattern, page.text, re.IGNORECASE):
                prefix = page.text[max(0, match.start()-30):match.start()]
                if re.search(r'(?:eski|önceki|dönemin)\s*$', prefix, re.IGNORECASE):
                    continue
                candidates.append((page, match.group(0), match.group('name'), title, expected))
    return candidates


def validate_recipient(review, recipients, comparison_pages=None):
    from types import SimpleNamespace
    check = next(c for c in review.checks if c.kind == 'muhatap')
    candidates = extract_recipients(review.pages, recipients)
    comparison_readings = [SimpleNamespace(page=i, text=p.get('ocr', ''))
                           for i, p in enumerate(comparison_pages or [], 1)]
    comparison = extract_recipients(comparison_readings, recipients)
    if len(candidates) != 1:
        check.status = 'belirsiz'
        check.explanation = 'Kullanıcının muhatap listesiyle karşılaştırılabilecek tek bir açık unvan–isim eşleşmesi doğrulanamadı; insan kontrolü gerekiyor.'
        return
    page, quote, actual, title, expected = candidates[0]
    # Compare structured addressees as well as generic text diffs. A matching name
    # elsewhere in the page must not hide a conflicting name in the actual addressee.
    comparison_same_page = [item for item in comparison if item[0].page == page.page]
    comparable = lambda value: normalize(value).translate(str.maketrans('çğıöşüâû', 'cgiosuau'))
    comparison_unique = {(comparable(item[3]), comparable(item[2])): item for item in comparison_same_page}
    if len(comparison_unique) > 1:
        check.status = 'belirsiz'
        check.page = page.page
        check.quote = quote
        check.reading_uncertain = True
        check.explanation = 'PDF/OCR okumasında birden fazla farklı muhatap var; görsel okumayla tek bir eşleşme doğrulanamadı. Uygun kabul edilmedi.'
        return
    if len(comparison_unique) == 1:
        other = next(iter(comparison_unique.values()))
        if comparable(other[2]) != comparable(actual) or comparable(other[3]) != comparable(title):
            check.status = 'belirsiz'
            check.page = page.page
            check.quote = quote
            check.reading_uncertain = True
            check.explanation = (f'Muhatap alanında iki okuma uyuşmuyor. Görsel okuma: {title} – {actual}; '
                                 f'PDF/OCR okuması: {other[3]} – {other[2]}. '
                                 f'Kullanıcı listesindeki {title}: {expected}. Uygun kabul edilmedi.')
            return
    if check.reading_uncertain or '[OKUNAMADI]' in quote:
        check.status = 'belirsiz'
        check.page = page.page
        check.quote = quote
        check.explanation = 'Muhatabın bulunduğu sayfada okuma belirsizliği var; unvan–isim eşleşmesi insan kontrolü gerektiriyor.'
        return
    check.page = page.page
    check.quote = quote
    if normalize(actual) != normalize(expected):
        check.status = 'uyari'
        check.page = page.page
        check.quote = quote
        check.explanation = f'Kullanıcı tarafından tanımlanan muhatap listesinde {title}: {expected}. Belgede {actual} yazıyor; unvan–isim eşleşmesi uygun değil.'
    else:
        check.status = 'uygun'
        check.explanation = f'Belgedeki {title} – {actual} eşleşmesi, kullanıcının muhatap listesindeki {expected} ile uyumlu. Bakan adı kontrolünde yalnızca bu liste kullanıldı.'
