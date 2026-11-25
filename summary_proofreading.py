"""Offline, bounded TDK-based suggestions for KKBS summaries, never source edits.

Rules were checked against TDK on 2026-11-20; kayyum/kayyım on 2026-11-25. This is a focused writing check,
not a dictionary/identity validator for people or places or a full grammar parser.
"""
import csv
import hashlib
import io
import json
from functools import lru_cache
from pathlib import Path
import re

from entry_comparison import MINISTRIES, folded, one_edit, text
from incoming_papers import key

_district_path = Path(__file__).with_name('district_reference.json')
_district_data = _district_path.read_bytes() if _district_path.exists() else b''
# A source file is installed only after checking the user's actual PDF.
DISTRICT_REFERENCE = json.loads(_district_data) if _district_data else None
VERSION = hashlib.sha256(b'\0'.join((Path(__file__).read_bytes(),
    Path(__file__).with_name('district_validation.py').read_bytes(), _district_data))).hexdigest()[:12]
SOURCES = {
    'dictionary': 'https://sozluk.gov.tr/',
    'apostrophe': 'https://tdk.gov.tr/icerik/yazim-kurallari/kesme-isareti/',
    'capitals': 'https://tdk.gov.tr/icerik/yazim-kurallari/buyuk-harflerin-kullanildigi-yerler/',
    'punctuation': 'https://tdk.gov.tr/icerik/yazim-kurallari/noktalama-isaretleri-aciklamalar/',
    'summary_format': 'Kullanıcının KKBS özet biçimi kuralı: son sözcük “ilişkin” olmalıdır.',
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


@lru_cache(maxsize=8)
def _recipient_tail(titles):
    # Cache only public office patterns, never uploaded summaries.
    variants = set(titles)
    for title, aliases in MINISTRIES.items():
        if title == 'Cumhurbaşkanı Yardımcısı':
            variants.update(aliases)
        else:
            variants.update(alias + ' bakani' for alias in aliases)
    letters = {'a': '[aâ]', 'c': '[cç]', 'g': '[gğ]', 'i': '[iıî]',
               'o': '[oö]', 's': '[sş]', 'u': '[uüû]'}
    offices = []
    for title in sorted(variants, key=len, reverse=True):
        offices.append(r',?\s+'.join(''.join(letters.get(c, re.escape(c)) for c in word)
                                    for word in folded(title).split()))
    return re.compile(r'\b(?:' + '|'.join(offices) + r')' + APOSTROPHE + r'?ndan'
        r'(?:\s*\([^()]{1,120}\))?\s+yazılı\s+soru\s+önergesi'
        r'(?:\s*\(Başkanlığa\s+geliş\s+tarihi\s*:[^()]{1,60}\))?[\s.]*$', re.I)


def summary_text(value, combined, recipients):
    """Find the summary using the owner and recipient, regardless of its last word."""
    value = text(value)
    owner = re.match(r'^.{0,65}?\b(?:Milletvekili|Mv\.)\s+[^,\n]{1,100},\s*', value, re.I)
    if owner:
        tail = _recipient_tail(tuple(recipients)).search(value, owner.end())
        if tail:
            return value[owner.end():tail.start()].strip()
    # A broken combined template must never be mistaken for the manual summary.
    if combined or (owner and re.search(r'yazılı\s+soru\s+önergesi|Başkanlığa\s+geliş', value, re.I)):
        return None
    return value


def check_summary_ending(value):
    """The required KKBS ending is a workflow rule, independent of TDK membership."""
    value = text(value)
    if not value:
        return []  # Empty/unreadable summaries are separately reported, never approved.
    last = re.search(r'\b(?P<word>[' + LETTERS + r']+)(?P<punctuation>[^\w]*)$', value)
    if last:
        word = last['word'].translate(str.maketrans('Iİ', 'ıi')).lower()
        if word == 'ilişkin' and not last['punctuation']:
            return []
        if (one_edit(folded(word), 'iliskin')
                and re.fullmatch(r'[.,;:!?…]*', last['punctuation'])):
            return [dict(start=last.start(), end=len(value), before=value[last.start():], after='ilişkin',
                         rule='summary_ending', conditional=False, source=SOURCES['summary_format'],
                         reason='KKBS özetinin son sözcüğü “ilişkin” olmalıdır; hatalı bitişi düzeltin.')]
    # Do not fabricate a grammatical rewrite for a different or missing ending.
    return [dict(start=0, end=len(value), before=value, after='… ilişkin', rule='summary_ending',
                 conditional=True, source=SOURCES['summary_format'],
                 reason='Özet “ilişkin” ile bitmiyor. Son ifadeyi anlamını koruyarak “… ilişkin” biçiminde düzenleyin; önceki sözcüğün hâl eki de değişebilir.')]


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
    for m in re.finditer(r'\bkayyum(?:(?:lar|lu[kğ]|u|a|d[au]|la|c[au]|suz|ken)[' + LETTERS + r']*)?\b', value, re.I):
        if unprotected(m):
            add(*m.span(), m.group().translate(str.maketrans('uU', 'ıI')), 'kayyim',
                'TDK, “kayyum” maddesini “kayyım” biçimine yönlendirir. Ekli kullanımlarda da ünlü uyumu korunur.', 'dictionary')

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


def review_summaries(sheet, source_records, column, recipients, *, header=0, district_reference=DISTRICT_REFERENCE):
    # Opt in only after the user's directory has been retrieved and verified.
    from district_validation import DistrictDirectory
    directory = DistrictDirectory(district_reference) if district_reference is not None else None
    report = dict(version=VERSION, available=column is not None, checked_count=0,
                  empty_count=0, affected_count=0, suggestions=[], scope='summary_only', skipped_documents=[])
    report['district_review'] = {'available': directory is not None,
                                 'source': directory.source if directory else None}
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
        findings.extend(check_summary_ending(value))
        if directory is not None:
            findings.extend(directory.check(value))
        findings.sort(key=lambda finding: (finding['start'], finding['end'], finding['rule']))
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
