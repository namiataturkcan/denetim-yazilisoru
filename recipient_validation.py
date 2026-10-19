"""Conservative validation of explicit addressees against user-supplied rules."""
import re
import unicodedata


def normalize(text):
    text = unicodedata.normalize('NFC', text).translate(str.maketrans({'I': 'ı', 'İ': 'i', 'î': 'i', 'Î': 'i'})).lower()
    return ' '.join(text.split())


def validate_recipient(review, recipients):
    check = next(c for c in review.checks if c.kind == 'muhatap')
    candidates = []
    # Match explicit answer-request constructions, not a name anywhere in the PDF.
    letters = r'[A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû]+'
    name = rf'{letters}(?:\s+{letters}){{1,4}}?'
    ending = r"(?=\s+tarafından\b|[’'](?:nın|nin|nun|nün|ın|in|un|ün|na|ne)\b)"
    for page in review.pages:
        for title, expected in recipients.items():
            title_pattern = r'\s+'.join(re.escape(w) for w in title.split()).replace('Millî', 'Mill[îi]')
            pattern = rf'(?<!\w)(?P<title>{title_pattern})\s+(?:Sayın\s+)?(?P<name>{name}){ending}'
            for match in re.finditer(pattern, page.text, re.IGNORECASE):
                prefix = page.text[max(0, match.start()-30):match.start()]
                if re.search(r'(?:eski|önceki|dönemin)\s*$', prefix, re.IGNORECASE):
                    continue
                candidates.append((page, match.group(0), match.group('name'), title, expected))
    if len(candidates) != 1:
        check.status = 'belirsiz'
        check.explanation = 'Kullanıcının muhatap listesiyle karşılaştırılabilecek tek bir açık unvan–isim eşleşmesi doğrulanamadı; insan kontrolü gerekiyor.'
        return
    page, quote, actual, title, expected = candidates[0]
    if page.uncertainties or '[OKUNAMADI]' in page.text:
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
