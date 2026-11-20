"""Offline, bounded TDK-based suggestions for KKBS summaries, never source edits.

Rules were checked against TDK on 2026-11-20. This is a focused writing check,
not a dictionary/identity validator for people or places or a full grammar parser.
"""
import csv
import hashlib
import io
from pathlib import Path
import re

from entry_comparison import ministry_identity, text
from incoming_papers import key

VERSION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
SOURCES = {
    'dictionary': 'https://sozluk.gov.tr/',
    'apostrophe': 'https://tdk.gov.tr/icerik/yazim-kurallari/kesme-isareti/',
    'capitals': 'https://tdk.gov.tr/icerik/yazim-kurallari/buyuk-harflerin-kullanildigi-yerler/',
    'punctuation': 'https://tdk.gov.tr/icerik/yazim-kurallari/noktalama-isaretleri-aciklamalar/',
}
SUMMARY_HEADERS = ('Özet', 'Önerge Özeti', 'Soru Özeti', 'Önergenin Özeti', 'Konu Özeti',
                   'Önerge Sahibi Özeti', 'Sahibi ve Özeti', 'Konu')
COMBINED_HEADERS = {key(v) for v in ('Önerge Sahibi Özeti', 'Sahibi ve Özeti')}
LETTERS = 'A-Za-zÇĞİÖŞÜçğıöşüÂÎÛâîû'
APOSTROPHE = "['’‘ʼ]"
INSTITUTIONS = ('Başkanlığı', 'Bakanlığı', 'Müdürlüğü', 'Üniversitesi', 'Fakültesi',
                'Kurumu', 'Kurulu', 'Meclisi', 'Komisyonu', 'Derneği', 'Vakfı',
                'Belediyesi', 'İdaresi', 'Mahkemesi', 'Valiliği', 'Kaymakamlığı',
                'Rektörlüğü', 'Dairesi', 'Kooperatifi', 'Şirketi', 'Başbakanlığı',
                'Cumhurbaşkanlığı', 'Enstitüsü', 'Akademisi', 'Bölümü')
INSTITUTION_RE = re.compile(r'\b(' + '|'.join(INSTITUTIONS) + ')' + APOSTROPHE
                            + r'([' + LETTERS + r']+)\b', re.I)
SPELLINGS = {
    'herkez': 'herkes', 'yanlız': 'yalnız', 'yalnış': 'yanlış',
    'bir çok': 'birçok', 'bir kaç': 'birkaç', 'hiç bir': 'hiçbir',
    'herşey': 'her şey', 'yada': 'ya da', 'pekçok': 'pek çok',
}
SPELLING_RULES = [(re.compile(r'\b' + re.escape(wrong).replace(r'\ ', r'[ \u00a0]+') + r'\b'), right)
                  for wrong, right in SPELLINGS.items()]
TITLE_RE = re.compile(r'\b(Bakan|Başkan|Vali|Kaymakam|Müdür)' + APOSTROPHE
                      + r'([' + LETTERS + r']+)\b', re.I)


def suggest_summary_column(sheet, header):
    normalized = [key(v) for v in sheet.headers(header)] if header else []
    for label in SUMMARY_HEADERS:
        matches = [i for i, value in enumerate(normalized) if value == key(label)]
        if len(matches) == 1:
            return matches[0]
    return None


def summary_text(value, combined, recipients):
    """Strip the generated KKBS wrapper only when both boundaries are recognized."""
    value = text(value)
    owner = re.match(r'^.{0,65}?\b(?:Milletvekili|Mv\.)\s+[^,\n]{1,100},\s*', value, re.I)
    if owner:
        for match in reversed(list(re.finditer(r'\bilişkin\b', value, re.I))):
            tail = value[match.end():]
            if (match.start() >= owner.end()
                    and re.search(r'\byazılı\s+soru\s+önergesi\b', tail, re.I)
                    and ministry_identity(tail, recipients)[0]):
                return value[owner.end():match.end()].strip()
    # A broken combined template must never be mistaken for the manual summary.
    if combined or (owner and re.search(r'yazılı\s+soru\s+önergesi|Başkanlığa\s+geliş', value, re.I)):
        return None
    return value


def _protected_spans(value):
    spans = [m.span() for m in re.finditer(r'"[^"\n]*"|“[^”\n]*”', value)]
    # The combined KKBS prefix is the owner and constituency, not the summary.
    owner = re.match(r'^.{0,65}?\b(?:Milletvekili|Mv\.)\s+[^,\n]{1,100},', value)
    if owner:
        spans.append(owner.span())
    # Do not propose dictionary substitutions in a named geographic expression.
    place_types = r'(?:köy[üüne][^\W\d_]*|mahalles[^\W\d_]*|ilçes[^\W\d_]*|il(?:i|ine|inde|inin|inden)|beldes[^\W\d_]*|soka[ğk][^\W\d_]*|caddes[^\W\d_]*|bulvarı[^\W\d_]*|meydanı[^\W\d_]*)'
    for m in re.finditer(r'\b[^\W\d_]+\s+' + place_types + r'\b', value, re.I):
        spans.append(m.span())
    for m in re.finditer(r'\b(?:[^\W\d_]+\s+){1,4}(?:Bey|Hanım|Paşa|Efendi)\b', value):
        spans.append(m.span())
    for m in re.finditer(r'\b\w+' + APOSTROPHE + r'\w+', value):
        spans.append(m.span())
    return spans


def check_summary(value, recipients, *, sentence_initial=True):
    """Return source offsets and replacement suggestions without rewriting text."""
    value = text(value)
    suggestions = []
    protected = _protected_spans(value)

    def add(start, end, replacement, rule, reason, source, conditional=False):
        if value[start:end] == replacement:
            return
        suggestions.append(dict(start=start, end=end, before=value[start:end], after=replacement,
                                rule=rule, reason=reason, source=SOURCES[source], conditional=conditional))

    for m in re.finditer(r'(?<=\S)[ \u00a0]{2,}(?=\S)', value):
        add(*m.span(), ' ', 'extra_spaces', f'Kelimeler arasında {len(m.group())} boşluk var; tek boşluk kullanın.', 'punctuation')

    def unprotected(m):
        return not any(a < m.end() and m.start() < b for a, b in protected)

    for pattern, right in SPELLING_RULES:
        for m in pattern.finditer(value):
            if unprotected(m):
                add(*m.span(), right, 'spelling', 'TDK Güncel Türkçe Sözlük’teki yazıma göre öneri.', 'dictionary')
    for m in re.finditer(r'\bunvan[' + LETTERS + r']*\b', value):
        if unprotected(m):
            add(*m.span(), 'ünvan' + m.group()[5:], 'unvan', 'Güncel TDK sözlüğünde sözcük “ünvan” olarak yer alır.', 'dictionary')

    # Institutional names differ from personal titles: Başkanlığına, but Başkanı’na.
    for m in INSTITUTION_RE.finditer(value):
        add(*m.span(), m.group(1) + m.group(2), 'institution_apostrophe',
            'Kurum, kuruluş ve kurul adlarına gelen ekler kesmeyle ayrılmaz.', 'apostrophe')

    for title in recipients:
        pattern = re.compile(r'\b' + re.escape(title).replace(r'\ ', r'\s+') + r'\b', re.I)
        for office in pattern.finditer(value):
            if office.group().isupper():
                continue  # An entirely capitalized name keeps its conjunction capitals.
            for m in re.finditer(r'\b(?:Ve|İle|Veya|Yahut)\b', office.group()):
                add(office.start()+m.start(), office.start()+m.end(), m.group().lower(),
                    'title_conjunction', 'Özel adların içindeki bağlaçlar küçük harfle yazılır; tamamı büyük yazılmış adlar hariçtir.', 'capitals')

    # A title can stand for a particular person's name. Always label this conditional.
    for m in TITLE_RE.finditer(value):
        prefix = value[:m.start()].rstrip()
        previous = re.search(r'([' + LETTERS + r']+)\s*$', prefix)
        if previous and (previous.group(1)[0].isupper() or previous.group(1).lower() in ('sayın', 'sn')):
            continue  # Sayın Bakan / a full office or personal name is not generic.
        if any(a <= m.start() < b for a, b in protected
               if value[a:b].startswith(('"', '“'))):
            continue
        replacement = m.group(1).lower() + m.group(2)
        if (not prefix and sentence_initial) or (prefix and prefix[-1] in '.!?'):
            replacement = replacement[0].upper() + replacement[1:]
        add(*m.span(), replacement, 'generic_title',
            'Genel görev adı kastediliyorsa küçük harf ve kesmesiz yazım kullanılır. Belirli bir kişinin adı yerine kullanılan makam adı büyük harfle yazılabilir; bağlamı kontrol edin.',
            'capitals', conditional=True)
    return sorted(suggestions, key=lambda s: (s['start'], s['end'], s['rule']))


def review_summaries(sheet, source_records, column, recipients, *, header=0):
    report = dict(version=VERSION, available=column is not None, checked_count=0,
                  empty_count=0, affected_count=0, suggestions=[], scope='summary_only', skipped_documents=[])
    if column is None:
        return report
    by_row = {record['row']: record for record in source_records}
    headers = sheet.headers(header)
    combined = column < len(headers) and key(headers[column]) in COMBINED_HEADERS
    affected = set()
    for number, cells in sheet.rows:
        record = by_row.get(number)
        if record is None:
            continue
        value = text(cells[column]) if column < len(cells) else ''
        if not value:
            report['empty_count'] += 1
            continue
        original = value
        value = summary_text(value, combined, recipients)
        if not value:
            report['skipped_documents'].append(record['document'])
            continue
        report['checked_count'] += 1
        findings = check_summary(value, recipients, sentence_initial=value == original)
        if findings:
            affected.add(number)
        for finding in findings:
            report['suggestions'].append(dict(finding, document=record['document'], row=number, summary=value))
    report['affected_count'] = len(affected)
    return report


def suggestions_csv(report):
    out = io.StringIO()
    writer = csv.writer(out, delimiter=';')
    writer.writerow(['Evrak No', 'Olan', 'Olması gereken', 'Gerekçe', 'Bağlama bağlı', 'Kaynak'])
    for finding in report['suggestions']:
        values = [finding['document'], finding['before'], finding['after'], finding['reason'],
                  'Evet' if finding['conditional'] else 'Hayır', finding['source']]
        writer.writerow(["'"+v if v.lstrip().startswith(('=', '+', '-', '@')) else v for v in values])
    return out.getvalue().encode('utf-8-sig')
