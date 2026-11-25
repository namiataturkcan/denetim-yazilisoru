"""Compare two independently entered registers using exact document IDs; no API."""
import csv
import hashlib
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

from incoming_papers import MAX_COLUMNS, MAX_ROWS, TableError, _workbook, key
from recipient_validation import normalize
from constituency_validation import reference_pairs

VERSION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
ALIASES = {
    'document': ('Genel Evrak Numarası', 'Genel Evrak No', 'Evrak Kayıt No', 'Evrak Numarası',
                 'Evrak No', 'EBYS Evrak No', 'EBYS No', 'Belge Numarası', 'Belge No', 'Barkod No', 'Barkod Numarası', 'Evrak Sayısı', 'Sayı'),
    'member': ('Önerge Sahibi', 'Soru Sahibi', 'Milletvekili Adı Soyadı', 'Milletvekili Adı', 'Milletvekili',
               'Vekil Adı', 'Adı Soyadı', 'Gönderen', 'Geldiği Yer', 'Gelen Yer'),
    'ministry': ('Önerge Muhatabı', 'Muhatap Unvanı', 'Muhatap Ünvanı', 'Muhatap', 'Bakanlık Adı',
                 'Bakanlık', 'Bakan Adı', 'Bakan', 'Gönderilen Makam'),
    'case': ('Esas No', 'Esas Numarası'),
    'province': ('Seçim Çevresi', 'Soru Sahibi İli', 'Milletvekili İli'),
}
COMBINED = ('Önerge Sahibi Özeti', 'Sahibi ve Özeti', 'Konu', 'Açıklama')
MINISTRIES = {
    'Adalet Bakanlığı': ('adalet',),
    'Aile ve Sosyal Hizmetler Bakanlığı': ('aile ve sosyal hizmetler', 'aile'),
    'Çalışma ve Sosyal Güvenlik Bakanlığı': ('calisma ve sosyal guvenlik', 'calisma'),
    'Çevre, Şehircilik ve İklim Değişikliği Bakanlığı': ('cevre sehircilik ve iklim degisikligi', 'cevre ve sehircilik', 'cevre sehircilik', 'cevre'),
    'Dışişleri Bakanlığı': ('disisleri',),
    'Enerji ve Tabii Kaynaklar Bakanlığı': ('enerji ve tabii kaynaklar', 'enerji'),
    'Gençlik ve Spor Bakanlığı': ('genclik ve spor', 'genclik', 'spor'),
    'Hazine ve Maliye Bakanlığı': ('hazine ve maliye', 'maliye', 'hazine'),
    'İçişleri Bakanlığı': ('icisleri',),
    'Kültür ve Turizm Bakanlığı': ('kultur ve turizm', 'kultur', 'turizm'),
    'Millî Eğitim Bakanlığı': ('milli egitim', 'egitim'),
    'Millî Savunma Bakanlığı': ('milli savunma', 'savunma'),
    'Sağlık Bakanlığı': ('saglik',),
    'Sanayi ve Teknoloji Bakanlığı': ('sanayi ve teknoloji', 'sanayi'),
    'Tarım ve Orman Bakanlığı': ('tarim ve orman', 'tarim', 'orman'),
    'Ticaret Bakanlığı': ('ticaret',),
    'Ulaştırma ve Altyapı Bakanlığı': ('ulastirma ve altyapi', 'ulastirma'),
    'Cumhurbaşkanı Yardımcısı': ('cumhurbaskani yardimcisi', 'cumhurbaskanligi yardimcisi'),
}


def text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def folded(value):
    value = normalize(text(value)).translate(str.maketrans('çğıöşüâû', 'cgiosuau'))
    return ' '.join(re.findall(r'[a-z0-9]+', value))


def document_id(value):
    if isinstance(value, bool):
        return ''
    value = text(value)
    if re.fullmatch(r'\d+\.0+', value):
        value = value.split('.')[0]
    if re.fullmatch(r'[1-9]\d{0,2}(?:\.\d{3})+', value):
        value = value.replace('.', '')
    value = re.sub(r'\s+', '', value).upper()
    # Keep year/prefix components: 2026/123 is not guessed to be document 123.
    return value if (len(value) <= 120 and re.fullmatch(r'[A-Z0-9./_-]+', value)
                     and re.search(r'\d', value)) else ''


def member_name(value):
    value = ' '.join(text(value).split())
    if not value or len(value) > 20000:
        return ''
    value = re.sub(r'\([^()]*(?:Milletvekili|Mv\.)[^()]*\)', '', value, flags=re.I).strip()
    role = re.search(r'\b(?:Milletvekili|Mv\.?)\s+', value, re.I)
    if role:
        if role.start() > 60:
            return ''  # Do not search the question narrative for an owner.
        value = value[role.end():]
    value = re.sub(r'^(?:(?:Sayın|Sn\.?|Prof\.?|Doç\.?|Dr\.?|Grup Başkanvekili)\s+)+', '', value, flags=re.I)
    value = re.split(r"['’‘ʼ]", value, maxsplit=1)[0].strip()
    value = value.replace(',', ' ')
    words = value.split()
    if (not 2 <= len(words) <= 5 or len(value) > 120
            or not all(re.fullmatch(r'[^\W\d_]+(?:-[^\W\d_]+)?|[^\W\d_]\.', word) for word in words)):
        return ''
    if set(folded(value).split()) & {'milletvekili', 'bakani', 'bakanligi', 'bakan', 'onergesi',
                                    'yazili', 'iliskin', 'hakkinda', 'konulu', 'tarafindan', 'tbmm'}:
        return ''
    return ' '.join(words)


def member_province(value):
    """Read only an explicit owner prefix/parenthesis, never places in the summary."""
    value = ' '.join(text(value).split())
    value = re.sub(r'^Yazılı Soru\s+(?:Önergesi\s+)?', '', value, flags=re.I)
    word = r'[^\W\d_]+'
    match = re.match(r'^(' + word + r')\s+(?:Milletvekili|Mv\.?)\s+', value, re.I)
    if not match:
        match = re.fullmatch(r'[\w .-]{2,120}\s+\((' + word + r')\s+(?:Milletvekili|Mv\.?)\)', value, re.I)
    return match[1] if match else ''


def directory_checks(left, right, directory):
    """Validate KKBS against the independent list, and disambiguate namesakes."""
    checks = []
    name = member_name(left['member'])
    if not name:
        return checks  # Already reported by the name comparison.
    entries = directory.get(folded(name), ())
    if not entries:
        return [('member_reference', 'belirsiz',
                 f'KKBS’deki {name} adı kullanıcının milletvekili listesinde tam adla eşleşmedi; listeye göre doğrulanamadı.')]
    allowed = {folded(province): province for _, provinces in entries for province in provinces}
    province = left.get('province') or member_province(left['member'])
    other = right.get('province') or member_province(right['member'])
    if province and folded(province) not in allowed:
        checks.append(('province', 'uyari',
                       f'KKBS’de {name} için seçim çevresi {province}; kullanıcının listesinde {", ".join(allowed.values())}.'))
    elif len(allowed) > 1:
        # Equal full names alone do not prove that these are the same member.
        if not province or not other or folded(other) not in allowed:
            checks.append(('province', 'belirsiz',
                           f'{name} adı listede birden fazla seçim çevresinde var ({", ".join(allowed.values())}); '
                           'iki kayıttaki seçim çevresiyle aynı kişi olduğu doğrulanamadı.'))
        elif folded(province) != folded(other):
            checks.append(('province', 'uyari',
                           f'Adlar aynı olsa da farklı milletvekilleri: KKBS {province}, EBYS {other} seçim çevresi.'))
    return checks


def one_edit(a, b):
    """One insertion, deletion, replacement or adjacent transposition, bounded."""
    if a == b or abs(len(a)-len(b)) > 1:
        return a == b
    if len(a) == len(b):
        differences = [i for i, pair in enumerate(zip(a, b)) if pair[0] != pair[1]]
        return len(differences) == 1 or (len(differences) == 2
            and differences[1] == differences[0]+1
            and a[differences[0]] == b[differences[1]] and a[differences[1]] == b[differences[0]])
    if len(a) > len(b):
        a, b = b, a
    i = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), len(a))
    return a[i:] == b[i+1:]


def within_two_edits(a, b):
    if abs(len(a)-len(b)) > 2:
        return False
    previous = list(range(len(b)+1))
    for i, char in enumerate(a, 1):
        current = [i]
        for j, other in enumerate(b, 1):
            current.append(min(current[-1]+1, previous[j]+1, previous[j-1]+(char != other)))
        if min(current) > 2:
            return False
        previous = current
    return previous[-1] <= 2


def resolve_initials(parts, full_names):
    if not any(len(p) == 1 for p in parts):
        return ' '.join(parts)
    if len(parts[-1]) == 1:
        return None  # A surname initial is not enough to identify an owner.
    matches = set()
    for name in full_names:
        words = folded(name).split()
        if len(words) == len(parts) and all(len(w) > 1 for w in words) and all(
                w == p or (len(p) == 1 and w.startswith(p)) for w, p in zip(words, parts)):
            matches.add(' '.join(words))
    return next(iter(matches)) if len(matches) == 1 else None


def compare_members(left, right, known, full_names=()):
    a, b = member_name(left), member_name(right)
    if not a or not b:
        return 'belirsiz', 'Milletvekili adı boş, eksik veya seçilen metinden açıkça ayrıştırılamadı.'
    fa, fb = folded(a), folded(b)
    ca, cb = fa.replace(' ', ''), fb.replace(' ', '')
    if any(len(p) == 1 for p in (fa+' '+fb).split()):
        ra, rb = (resolve_initials(name.split(), full_names) for name in (fa, fb))
        if not ra or not rb:
            return 'belirsiz', 'Kısaltılmış milletvekili adı kaynaklarda tek bir tam adla eşleştirilemedi.'
        if ra == rb:
            return 'yazim', 'Adın baş harfiyle yapılan kısaltma, kaynaklarda tek bir tam adla eşleşti.'
        return 'uyari', 'Kısaltılmış ad açıldığında milletvekili adları farklı kişilere karşılık geliyor.'
    if ca == cb:
        return 'uygun', ''
    # Never excuse two known, different people as a spelling mistake.
    if ca in known and cb in known:
        return 'uyari', 'İki kayıtta farklı milletvekili adları var; önergenin aslıyla kontrol edin.'
    if sorted(fa.split()) == sorted(fb.split()):
        return 'yazim', 'Ad ve soyadı sırası farklı; adın tüm sözcükleri aynı.'
    wa, wb = fa.split(), fb.split()
    if min(len(wa), len(wb)) >= 2 and abs(len(wa)-len(wb)) == 1:
        short, long = (wa, wb) if len(wa) < len(wb) else (wb, wa)
        def same_prefix(words):
            if len(words) != len(long):
                return False
            prefix, given = ''.join(words[:len(short)]), ''.join(short)
            return prefix == given or (min(len(prefix), len(given)) >= 10 and one_edit(prefix, given))
        if same_prefix(long):
            matches = {folded(name) for name in full_names if same_prefix(folded(name).split())}
            if matches == {' '.join(long)}:
                return 'yazim', 'Son ad/soyad bileşeni bir kaynakta eksik; en az iki sözcükle ve en fazla bir harf farkıyla kaynaklarda tek tam ada eşleşti.'
            return 'belirsiz', 'Ad/soyadın bir bileşeni eksik olabilir; kaynaklarda tek bir kişiyle eşleştirilemedi.'
    if min(len(ca), len(cb)) >= 8 and one_edit(ca, cb):
        possibilities = {name for name in known if abs(len(name)-len(cb)) <= 1 and one_edit(name, cb)}
        if possibilities == {ca}:
            return 'yazim', 'Tek harf veya harf sırası farkı var; kaynaklardaki tek yakın tam adla uyumlu.'
        return 'belirsiz', 'Adlar yakın yazılmış ancak farklı kişileri belirtme ihtimali dışlanamadı.'
    # Longer names can contain a short extra/missing syllable in one word.
    # Keep the other words exact and require a single candidate in the user's
    # reference + KKBS source, never a generic fuzzy match to arbitrary people.
    if (min(len(ca), len(cb)) >= 12 and len(wa) == len(wb)
            and sum(a != b for a, b in zip(wa, wb)) == 1 and within_two_edits(ca, cb)):
        possibilities = {name for name in known if within_two_edits(name, cb)}
        if possibilities == {ca}:
            return 'yazim', 'Adın bir sözcüğünde iki harfe kadar yazım farkı var; diğer sözcükler aynı ve kaynaklarda tek yakın tam ad bulundu.'
        return 'belirsiz', 'Adlar yakın yazılmış; hangi kişiyi belirttiği kaynaklardan kesinleştirilemedi.'
    return 'uyari', 'Milletvekili adları uyuşmuyor; ortak bir ad/soyad sözcüğü aynı kişi kabul edilmez.'


def ministry_identity(value, recipients):
    value = folded(value)
    if not value or len(value) > 20000:
        return None, False
    # In KKBS summaries the subject can mention another minister. The office
    # after "ilişkin" is the addressee; never fall back to a subject mention if
    # that addressee is unknown or missing.
    if ' iliskin ' in value and re.search(r'\byazili soru\b', value.rsplit(' iliskin ', 1)[1]):
        value = value.rsplit(' iliskin ', 1)[1]
    found = set()
    for title, aliases in MINISTRIES.items():
        for alias in aliases:
            ending = '' if title == 'Cumhurbaşkanı Yardımcısı' else r' bakan(?:ligi|i|lik)(?:na|ndan|nin)?'
            if value == alias or re.search(r'\b' + re.escape(alias) + ending + r'\b', value):
                found.add(title)
    if found:
        return (next(iter(found)), False) if len(found) == 1 else (None, False)
    # A named, unrecognized ministry is not overridden by the minister's name.
    offices = list(re.finditer(r'\bbakan\w*', value))
    if offices:
        near = set()
        for office in offices:
            prefix = value[:office.start()].split()
            for title, aliases in MINISTRIES.items():
                if title == 'Cumhurbaşkanı Yardımcısı':
                    continue
                for alias in aliases:
                    candidate = ''.join(prefix[-len(alias.split()):])
                    if min(len(candidate), len(alias.replace(' ', ''))) >= 5 and one_edit(candidate, alias.replace(' ', '')):
                        near.add(title)
        return (next(iter(near)), True) if len(near) == 1 else (None, False)
    # Only exact full minister names from the user's existing reference list.
    for title, name in recipients.items():
        if value == folded(name):
            display = title[:-len('Bakanı')] + 'Bakanlığı' if title.endswith('Bakanı') else title
            return display, False
    return None, False


@dataclass
class Sheet:
    name: str
    rows: list

    def headers(self, row_number):
        if row_number == 0:
            width = max((len(values) for _, values in self.rows), default=0)
            return tuple('' for _ in range(width))
        return next((values for number, values in self.rows if number == row_number), ())


def is_ebys_subject(value):
    """Recognize incoming-register subjects, not copied KKBS owner summaries."""
    return bool(re.match(r'^yazili soru\b.{0,90}\b(?:mv|milletvekili)\b', folded(value)))


def ebys_subject_columns(sheet):
    samples = [values for _, values in sheet.rows[:30]]
    width = max((len(values) for values in samples), default=0)
    columns = []
    for index in range(width):
        filled = [values[index] for values in samples if index < len(values) and text(values[index])]
        # A title/header or occasional empty cell must not defeat recognition.
        count = sum(is_ebys_subject(v) for v in filled)
        if count and count >= max(1, len(filled) * .6):
            columns.append(index)
    return columns


def suggest_mapping(sheet, header_row):
    if header_row:
        return suggest_columns(sheet.headers(header_row))
    result = {field: None for field in ALIASES}
    subjects = ebys_subject_columns(sheet)
    if len(subjects) != 1:
        return result
    subject = subjects[0]
    result.update(member=subject, ministry=subject)
    samples = [values for _, values in sheet.rows[:30]
               if subject < len(values) and is_ebys_subject(values[subject])]
    candidates = []
    for index in range(len(sheet.headers(0))):
        ids = [document_id(values[index]) if index < len(values) else '' for values in samples]
        if all(ids) and all(identity != '0' for identity in ids):
            candidates.append((index, ids))
    # Repeated ID columns are common in joined exports. Only pick one when
    # all candidates contain the very same IDs; otherwise ask for a mapping.
    if candidates and all(ids == candidates[0][1] for _, ids in candidates):
        result['document'] = candidates[0][0]
    return result


def validate_ebys_source(sheet, header_row, mapping):
    subjects = ebys_subject_columns(sheet)
    if len(subjects) != 1:
        return
    subject = subjects[0]
    if any(number <= header_row and subject < len(values) and is_ebys_subject(values[subject])
           for number, values in sheet.rows):
        raise TableError('EBYS başlık satırı seçimi gerçek kayıtları atlıyor. Başlıksız sayfada başlık satırını 0 yapın.')
    headers = sheet.headers(header_row)
    def explicit_field(field):
        index = mapping.get(field)
        return (header_row > 0 and index is not None and index < len(headers)
                and key(headers[index]) in {key(alias) for alias in ALIASES[field]})
    if any(mapping.get(field) != subject and not explicit_field(field) for field in ('member', 'ministry')):
        from openpyxl.utils import get_column_letter
        raise TableError(f'EBYS gelen evrak metni {get_column_letter(subject+1)} sütununda bulundu. '
                         'Milletvekili ve bakanlık alanlarında bu sütunu seçin; diğer sayfadan kopyalanmış özetle karşılaştırma yapılmamalı.')


def suggest_columns(headers):
    normalized = [key(v) for v in headers]
    result = {}
    for field, aliases in ALIASES.items():
        result[field] = next((normalized.index(key(alias)) for alias in aliases if normalized.count(key(alias)) == 1), None)
    combined = next((normalized.index(key(alias)) for alias in COMBINED if normalized.count(key(alias)) == 1), None)
    for field in ('member', 'ministry'):
        if result[field] is None:
            result[field] = combined
    return result


def suggest_header(sheet):
    candidates = [(number, suggest_columns(values)) for number, values in sheet.rows if number <= 30]
    best = max(candidates, key=lambda item: sum(item[1][f] is not None for f in ('document', 'member', 'ministry')), default=None)
    if best and any(v is not None for v in best[1].values()):
        return best[0]
    return 0 if ebys_subject_columns(sheet) else 1


def sheet_score(sheet, side):
    header = suggest_header(sheet)
    headers = {key(v) for v in sheet.headers(header)}
    mapped = sum(v is not None for v in suggest_mapping(sheet, header).values())
    if side == 'kkbs':
        return (bool(headers & {key('Genel Evrak No'), key('Genel Evrak Numarası')}),
                'kkbs' in key(sheet.name), not bool(ebys_subject_columns(sheet)), mapped)
    return (bool(headers & {key('Barkod No'), key('Barkod Numarası')}) or bool(ebys_subject_columns(sheet)),
            any(v in key(sheet.name) for v in ('ebys', 'gelenevrak', 'incomingdocuments')), mapped)


def suggest_sheet(previews, side):
    return max(previews, key=lambda sheet: sheet_score(sheet, side)).name


def suggest_sheet_pair(previews):
    kkbs = max(previews, key=lambda s: sheet_score(s, 'kkbs'))
    remaining = [s for s in previews if s.name != kkbs.name]
    ebys = max(remaining, key=lambda s: sheet_score(s, 'ebys'))
    return kkbs.name, ebys.name


def read_sheets(data, names, *, preview=False):
    if not names or len(set(names)) != len(names):
        raise TableError('Geçerli ve farklı çalışma sayfaları seçin.')
    book = _workbook(data)
    try:
        sheets = []
        for name in names:
            if name not in book.sheetnames:
                raise TableError('Seçilen çalışma sayfası bulunamadı.')
            ws = book[name]
            ws.reset_dimensions()
            rows = []
            source = ws.iter_rows(values_only=True)
            for number, raw in enumerate(islice(source, 30) if preview else source, 1):
                if number > MAX_ROWS + 30:
                    raise TableError('Her sayfada en fazla 100.000 veri satırı destekleniyor.')
                values = list(raw)
                while values and values[-1] is None:
                    values.pop()
                if len(values) > MAX_COLUMNS:
                    raise TableError('Bir çalışma sayfasında en fazla 128 sütun destekleniyor.')
                if any(text(v) for v in values):
                    rows.append((number, tuple(values)))
            sheets.append(Sheet(name, rows))
        return sheets
    except TableError:
        raise
    except Exception:
        raise TableError('Excel sayfaları okunamadı; geçerli ve şifresiz bir .xlsx dosyası yükleyin.') from None
    finally:
        book.close()


def records(sheet, header_row, mapping):
    headers = sheet.headers(header_row)
    if not headers:
        raise TableError(f'{sheet.name}: seçilen başlık satırı boş.')
    for field in ('document', 'member', 'ministry'):
        if mapping.get(field) is None:
            raise TableError(f'{sheet.name}: ortak evrak numarası, milletvekili ve bakanlık sütunlarını seçin.')
    if mapping['document'] in (mapping['member'], mapping['ministry']):
        raise TableError('Evrak numarası sütunu ad/bakanlık sütunu ile aynı olamaz.')
    if any(type(i) is not int or i < 0 or i >= len(headers) for i in mapping.values() if i is not None):
        raise TableError('Seçilen sütun geçersiz.')
    result = []
    for row_number, values in sheet.rows:
        if row_number <= header_row:
            continue
        cell = lambda i: values[i] if i is not None and i < len(values) else None
        selected = {field: text(cell(index)) for field, index in mapping.items()}
        if not any(selected.values()):
            continue
        if all(key(cell(mapping[f])) == key(headers[mapping[f]]) for f in ('document', 'member', 'ministry')):
            continue  # A repeated header in a printed/exported table.
        result.append({**selected, 'id': document_id(cell(mapping['document'])), 'row': row_number})
    if not result:
        raise TableError(f'{sheet.name}: seçilen başlığın altında kayıt bulunamadı.')
    return result


def finding(status, field, reason, left=None, right=None):
    left, right = left or {}, right or {}
    def evidence(row):
        if field == 'member_reference':
            return row.get('member', '')
        if field == 'province':
            return row.get('province') or row.get('member', '')
        return row.get(field, '')
    return {'status': status, 'field': field, 'explanation': reason,
            'document': left.get('document') or right.get('document', ''), 'case': left.get('case', ''),
            'kkbs_row': left.get('row', ''), 'ebys_row': right.get('row', ''),
            'kkbs': evidence(left), 'ebys': evidence(right)}


def compare_records(kkbs, ebys, recipients, reference_names=(), *, member_reference=None):
    pairs = reference_pairs(member_reference) if member_reference is not None else {}
    full_names = set(pairs) | set(reference_names) | {member_name(r['member']) for r in kkbs if member_name(r['member'])}
    directory = defaultdict(list)
    for name, provinces in pairs.items():
        directory[folded(name)].append((name, provinces))
    known = {folded(name).replace(' ', '') for name in full_names}
    groups = [defaultdict(list), defaultdict(list)]
    issues, variants = [], []
    for rows, group, side in zip((kkbs, ebys), groups, ('kkbs', 'ebys')):
        for row in rows:
            if row['id']:
                group[row['id']].append(row)
            else:
                issues.append(finding('belirsiz', 'document', 'Ortak evrak numarası boş veya biçimi tanınmadı.',
                                      row if side == 'kkbs' else None, row if side == 'ebys' else None))
    matched, clean, spelling, different, uncertain = 0, 0, 0, 0, 0
    name_cache, ministry_cache = {}, {}
    for identity in sorted(groups[0].keys() | groups[1].keys()):
        lefts, rights = groups[0].get(identity, []), groups[1].get(identity, [])
        left, right = lefts[0] if lefts else None, rights[0] if rights else None
        if len(lefts) > 1 or len(rights) > 1:
            row = finding('belirsiz', 'document', 'Aynı evrak numarası birden fazla satırda var; birebir eşleştirme yapılmadı.', left, right)
            row.update(kkbs_row=', '.join(str(r['row']) for r in lefts), ebys_row=', '.join(str(r['row']) for r in rights))
            issues.append(row)
            continue
        if left is None or right is None:
            issues.append(finding('belirsiz', 'document', 'Bu evrak yalnız ' + ('EBYS' if left is None else 'KKBS')
                                  + ' sayfasında bulundu; diğer raporun kapsamını kontrol edin.', left, right))
            continue
        matched += 1
        name_key = (left['member'], right['member'])
        if name_key not in name_cache:
            name_cache[name_key] = compare_members(*name_key, known, full_names)
        name_status, explanation = name_cache[name_key]
        checks = [('member', name_status, explanation)]
        if member_reference is not None:
            checks.extend(directory_checks(left, right, directory))
        offices = []
        for raw in (left['ministry'], right['ministry']):
            if raw not in ministry_cache:
                ministry_cache[raw] = ministry_identity(raw, recipients)
            offices.append(ministry_cache[raw])
        if any(title is None for title, _ in offices):
            checks.append(('ministry', 'belirsiz', 'Bakanlık bilgisi boş, tanınmıyor veya birden fazla muhatap içeriyor.'))
        elif offices[0][0] != offices[1][0]:
            checks.append(('ministry', 'uyari', f'Bakanlıklar farklı: KKBS {offices[0][0]}, EBYS {offices[1][0]}.'))
        elif any(near for _, near in offices):
            checks.append(('ministry', 'yazim', f'Küçük yazım farkı {offices[0][0]} ile eşleştirildi.'))
        else:
            checks.append(('ministry', 'uygun', ''))
        statuses = {s for _, s, _ in checks}
        if 'uyari' in statuses:
            different += 1
        elif 'belirsiz' in statuses:
            uncertain += 1
        elif 'yazim' in statuses:
            spelling += 1
        else:
            clean += 1
        for field, status, reason in checks:
            if status in ('uyari', 'belirsiz'):
                issues.append(finding(status, field, reason, left, right))
            elif status == 'yazim':
                variants.append(finding(status, field, reason, left, right))
    return {'version': VERSION, 'api_requests': 0, 'kkbs_count': len(kkbs), 'ebys_count': len(ebys),
            'matched': matched, 'clean': clean, 'spelling': spelling, 'different': different, 'uncertain': uncertain,
            'unmatched_kkbs': len(kkbs)-matched, 'unmatched_ebys': len(ebys)-matched,
            'complete': matched == len(kkbs) == len(ebys) and not uncertain
                        and not any(i['status'] == 'belirsiz' for i in issues),
            'issues': issues, 'variants': variants,
            **({'member_reference_source': member_reference['source']} if member_reference is not None else {})}


LABELS = {'member': 'Milletvekili', 'ministry': 'Bakanlık', 'document': 'Kayıt eşleştirme',
          'province': 'Seçim çevresi', 'member_reference': 'Milletvekili listesi'}


def issue_rows(items):
    return [{'Evrak No': i['document'], 'Esas No': i['case'], 'Kontrol': LABELS[i['field']],
             'Sonuç': {'uyari': 'Uyuşmazlık', 'belirsiz': 'Kontrol gerekli', 'yazim': 'Yakın yazım'}[i['status']],
             'KKBS': i['kkbs'], 'EBYS': i['ebys'], 'KKBS satırı': str(i['kkbs_row']),
             'EBYS satırı': str(i['ebys_row']), 'Açıklama': i['explanation']} for i in items]


def report_csv(report):
    out = io.StringIO()
    columns = ['Evrak No', 'Esas No', 'Kontrol', 'Sonuç', 'KKBS', 'EBYS', 'KKBS satırı', 'EBYS satırı', 'Açıklama']
    writer = csv.DictWriter(out, fieldnames=columns, delimiter=';')
    writer.writeheader()
    for row in issue_rows(report['issues'] + report['variants']):
        writer.writerow({k: "'"+v if v.lstrip().startswith(('=', '+', '-', '@')) else v for k, v in row.items()})
    return out.getvalue().encode('utf-8-sig')
