"""Compare two independently entered registers using exact document IDs; no API."""
import csv
import hashlib
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from incoming_papers import MAX_COLUMNS, MAX_ROWS, TableError, _workbook, key
from recipient_validation import normalize

VERSION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
ALIASES = {
    'document': ('Genel Evrak Numarası', 'Genel Evrak No', 'Evrak Kayıt No', 'Evrak Numarası',
                 'Evrak No', 'EBYS Evrak No', 'EBYS No', 'Belge Numarası', 'Belge No', 'Evrak Sayısı', 'Sayı'),
    'member': ('Önerge Sahibi', 'Soru Sahibi', 'Milletvekili Adı Soyadı', 'Milletvekili Adı', 'Milletvekili',
               'Vekil Adı', 'Adı Soyadı', 'Gönderen', 'Geldiği Yer', 'Gelen Yer'),
    'ministry': ('Önerge Muhatabı', 'Muhatap Unvanı', 'Muhatap Ünvanı', 'Muhatap', 'Bakanlık Adı',
                 'Bakanlık', 'Bakan Adı', 'Bakan', 'Gönderilen Makam'),
    'case': ('Esas No', 'Esas Numarası'),
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
    role = re.search(r'\b(?:Milletvekili|Mv\.)\s+', value, re.I)
    if role:
        if role.start() > 60:
            return ''  # Do not search the question narrative for an owner.
        value = value[role.end():]
    value = re.sub(r'^(?:(?:Sayın|Sn\.?|Prof\.?|Doç\.?|Dr\.?)\s+)+', '', value, flags=re.I)
    value = re.split(r"['’‘ʼ]", value, maxsplit=1)[0].strip()
    value = value.replace(',', ' ')
    words = value.split()
    if (not 2 <= len(words) <= 5 or len(value) > 120
            or not all(re.fullmatch(r'[^\W\d_]+(?:-[^\W\d_]+)?', word) for word in words)):
        return ''
    if set(folded(value).split()) & {'milletvekili', 'bakani', 'bakanligi', 'bakan', 'onergesi',
                                    'yazili', 'iliskin', 'hakkinda', 'konulu', 'tarafindan', 'tbmm'}:
        return ''
    return ' '.join(words)


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


def compare_members(left, right, known):
    a, b = member_name(left), member_name(right)
    if not a or not b:
        return 'belirsiz', 'Milletvekili adı boş, eksik veya seçilen metinden açıkça ayrıştırılamadı.'
    fa, fb = folded(a), folded(b)
    ca, cb = fa.replace(' ', ''), fb.replace(' ', '')
    if ca == cb:
        return 'uygun', ''
    # Never excuse two known, different people as a spelling mistake.
    if ca in known and cb in known:
        return 'uyari', 'İki kayıtta farklı milletvekili adları var; önergenin aslıyla kontrol edin.'
    if sorted(fa.split()) == sorted(fb.split()):
        return 'yazim', 'Ad ve soyadı sırası farklı; adın tüm sözcükleri aynı.'
    if min(len(ca), len(cb)) >= 8 and one_edit(ca, cb):
        possibilities = {name for name in known if abs(len(name)-len(cb)) <= 1 and one_edit(name, cb)}
        if possibilities == {ca}:
            return 'yazim', 'Tek harf veya harf sırası farkı var; kaynaklardaki tek yakın tam adla uyumlu.'
        return 'belirsiz', 'Adlar yakın yazılmış ancak farklı kişileri belirtme ihtimali dışlanamadı.'
    return 'uyari', 'Milletvekili adları uyuşmuyor; ortak bir ad/soyad sözcüğü aynı kişi kabul edilmez.'


def ministry_identity(value, recipients):
    value = folded(value)
    if not value or len(value) > 20000:
        return None, False
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
        return next((values for number, values in self.rows if number == row_number), ())


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
    return max(candidates, key=lambda item: sum(item[1][f] is not None for f in ('document', 'member', 'ministry')))[0] if candidates else 1


def read_sheets(data, names):
    if len(names) != 2 or len(set(names)) != 2:
        raise TableError('KKBS ve EBYS için iki farklı çalışma sayfası seçin.')
    book = _workbook(data)
    try:
        sheets = []
        for name in names:
            if name not in book.sheetnames:
                raise TableError('Seçilen çalışma sayfası bulunamadı.')
            ws = book[name]
            ws.reset_dimensions()
            rows = []
            for number, raw in enumerate(ws.iter_rows(values_only=True), 1):
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
    return {'status': status, 'field': field, 'explanation': reason,
            'document': left.get('document') or right.get('document', ''), 'case': left.get('case', ''),
            'kkbs_row': left.get('row', ''), 'ebys_row': right.get('row', ''),
            'kkbs': left.get(field, ''), 'ebys': right.get(field, '')}


def compare_records(kkbs, ebys, recipients, reference_names=()):
    known = {folded(name).replace(' ', '') for name in reference_names}
    known.update(folded(member_name(r['member'])).replace(' ', '') for r in kkbs if member_name(r['member']))
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
            name_cache[name_key] = compare_members(*name_key, known)
        name_status, explanation = name_cache[name_key]
        checks = [('member', name_status, explanation)]
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
            'issues': issues, 'variants': variants}


LABELS = {'member': 'Milletvekili', 'ministry': 'Bakanlık', 'document': 'Kayıt eşleştirme'}


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
