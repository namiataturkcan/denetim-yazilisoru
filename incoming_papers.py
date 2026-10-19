"""Deterministic incoming-paper reports from uploaded tables; no model or API calls."""
import csv
import io
import hashlib
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

from recipient_validation import normalize


MAX_TABLE_BYTES = 12 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 128
MAX_UNPACKED_BYTES = 160 * 1024 * 1024
REPORT_VERSION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
STATUS_LABELS = {
    'announced': 'Cevaplanmadığı Gelen Kağıtlarda İlan Edildi',
    'pending': '15 Günlük Cevaplanma Süresi Devam Ediyor',
    'answered': 'Cevaplandı',
    'withdrawn': 'Geri alındı',
    'unknown': 'Durumu tanınmayan',
    'conflict': 'Çelişkili kayıt',
}


class TableError(ValueError):
    pass


def key(value):
    text = normalize(str(value or '')).translate(str.maketrans('çğıöşüâû', 'cgiosuau'))
    return re.sub(r'[^a-z0-9]', '', text)


_status_groups = {
    key('Cevaplanmadığı Gelen Kağıtlarda İlan Edildi'): 'announced',
    key('15 Günlük Cevaplanma Süresi Devam Ediyor'): 'pending',
    key('Cevaplandı'): 'answered',
    key('Süresi İçinde Cevaplandı'): 'answered',
    key('Süresi Geçtikten Sonra Cevaplandı'): 'answered',
    key('Önerge Sahibi Tarafından Geri Alındı'): 'withdrawn',
    key('Geri Alındı'): 'withdrawn',
}
_column_aliases = {
    'number': ('Esas No', 'Esas Numarası', 'Esas Numara'),
    'status': ('Son Durum', 'Durum', 'Durumu', 'Statü'),
    'recipient': ('Muhatap Unvanı', 'Muhatap Ünvanı', 'Muhatap', 'Unvan'),
    'term': ('Donem Adı', 'Dönem', 'Dönem Adı', 'Yasama Dönemi'),
}
_header_keys = {field: {key(alias) for alias in aliases} for field, aliases in _column_aliases.items()}


def parse_number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('Geçersiz esas numarası')
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError('Geçersiz esas numarası')
        value = int(value)
    text = str(value).strip()
    text = re.sub(r'^7\s*/\s*', '', text)
    if re.fullmatch(r'[1-9]\d{0,2}(?:\.\d{3})+', text):
        text = text.replace('.', '')
    if not re.fullmatch(r'\d{1,9}', text) or int(text) <= 0:
        raise ValueError('Geçersiz esas numarası')
    return int(text)


def term_name(value):
    text = str(value or '').strip()
    match = re.fullmatch(r'(\d+)\s*\.?\s*(?:dönem)?', text, re.IGNORECASE)
    return f'{int(match[1])}. Dönem' if match else text


@dataclass(frozen=True)
class Record:
    number: int | None
    status: str
    recipient: str
    term: str
    source_row: int


def read_records(rows):
    """Read named KKBS columns or the three leading columns of a headerless paste."""
    mapping = None
    records = []
    for row_number, row in enumerate(rows, 1):
        if row_number > MAX_ROWS + 20:
            raise TableError('Tablo en fazla 100.000 veri satırı içerebilir.')
        if len(row) > MAX_COLUMNS:
            raise TableError('Tabloda en fazla 128 sütun destekleniyor.')
        if not any(value is not None and str(value).strip() for value in row):
            continue
        header = {}
        if mapping is None or (len(row) > mapping['number'] and key(row[mapping['number']]) in _header_keys['number']):
            normalized = [key(value) for value in row]
            for field, aliases in _column_aliases.items():
                matches = [i for i, column in enumerate(normalized) if column in _header_keys[field]]
                if len(matches) > 1:
                    raise TableError(f'Birden fazla {aliases[0]} sütunu bulundu; tek sütun kullanın.')
                if matches:
                    header[field] = matches[0]
        if {'number', 'status', 'recipient'} <= header.keys():
            mapping = header
            continue
        if mapping is None:
            # Historic ChatGPT examples were pasted without headers: number, status, title.
            try:
                parse_number(row[0])
            except (ValueError, IndexError):
                if row_number <= 20:
                    continue
                raise TableError('Esas No, Son Durum ve Muhatap Unvanı sütunları bulunamadı.')
            if len(row) < 3:
                raise TableError('Tabloda esas numarası, durum ve muhatap sütunları gerekli.')
            mapping = {'number': 0, 'status': 1, 'recipient': 2}
        def cell(field):
            index = mapping.get(field)
            return row[index] if index is not None and index < len(row) else None
        try:
            number = parse_number(cell('number'))
        except ValueError:
            number = None
        records.append(Record(number, str(cell('status') or '').strip(),
                              str(cell('recipient') or '').strip(), term_name(cell('term')), row_number))
        if len(records) > MAX_ROWS:
            raise TableError('Tablo en fazla 100.000 veri satırı içerebilir.')
    if not records:
        raise TableError('Veri bulunamadı. Esas No, Son Durum ve Muhatap Unvanı sütunlarını kontrol edin.')
    return records


def _workbook(data):
    if len(data) > MAX_TABLE_BYTES:
        raise TableError('Excel dosyası en fazla 12 MB olabilir.')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_UNPACKED_BYTES:
                raise TableError('Excel dosyasının açılmış boyutu çok büyük; ilgili satırları ayrı bir dosyaya alın.')
        return load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
    except TableError:
        raise
    except Exception as exc:
        raise TableError('Excel okunamadı. Geçerli ve şifresiz bir .xlsx dosyası yükleyin.') from exc


def sheet_names(data):
    book = _workbook(data)
    try:
        return book.sheetnames
    finally:
        book.close()


def read_excel(data, sheet):
    book = _workbook(data)
    try:
        if sheet not in book.sheetnames:
            raise TableError('Seçilen çalışma sayfası bulunamadı.')
        return read_records(book[sheet].iter_rows(values_only=True))
    except TableError:
        raise
    except Exception as exc:
        raise TableError('Excel satırları okunamadı; dosyanın sağlam olduğunu kontrol edin.') from exc
    finally:
        book.close()


def read_paste(text):
    if len(text.encode('utf-8')) > MAX_TABLE_BYTES:
        raise TableError('Yapıştırılan tablo en fazla 12 MB olabilir.')
    delimiter = '\t' if '\t' in text else ';' if ';' in text else ','
    try:
        return read_records(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error as exc:
        raise TableError('Tablo okunamadı; Excel’den satırları sütunlarıyla birlikte kopyalayın.') from exc


def number_ranges(numbers):
    numbers = sorted(set(numbers))
    ranges = []
    for number in numbers:
        if ranges and number == ranges[-1][1] + 1:
            ranges[-1][1] = number
        else:
            ranges.append([number, number])
    return format_ranges(ranges)


def format_ranges(ranges):
    return [str(start) if start == end else f'{start}–{end}' for start, end in ranges]


def absent_ranges(present, first, last):
    intervals = []
    cursor = first
    for number in sorted(set(present)):
        if number > cursor:
            intervals.append([cursor, number-1])
        cursor = number+1
    if cursor <= last:
        intervals.append([cursor, last])
    return format_ranges(intervals)


def recipient_names(recipients):
    return [title[:-6] + 'Bakanlığı' if title.endswith('Bakanı') else title for title in recipients]


def infer_term(records, first, last):
    """Use source metadata without asking for a term or merging different terms."""
    terms = {record.term for record in records}
    if len(terms) == 1:
        return next(iter(terms))
    matching_terms = {record.term for record in records
                      if record.number is not None and first <= record.number <= last}
    if len(matching_terms) == 1:
        return next(iter(matching_terms))
    raise TableError('Bu aralık için kaynak dönem bilgisi tek bir döneme indirgenemedi. '
                     'İşlem yapmak istediğiniz dönemin kayıtlarını ayrı bir tablo olarak yükleyin.')


def build_report(records, first, last, term, recipients):
    first, last = parse_number(first), parse_number(last)
    if first > last:
        raise TableError('Başlangıç esas numarası bitiş numarasından büyük olamaz.')
    if term is None:
        term = infer_term(records, first, last)
    terms = {record.term for record in records}
    if term not in terms:
        raise TableError('Kaynakta belirtilen döneme ait kayıt bulunamadı.')
    reference = recipient_names(recipients)
    aliases = {}
    for title, display in zip(recipients, reference):
        aliases[key(title)] = aliases[key(display)] = display
    grouped = defaultdict(list)
    invalid_rows = []
    for record in records:
        if record.term != term:
            continue
        if record.number is None:
            invalid_rows.append(record.source_row)
        elif first <= record.number <= last:
            grouped[record.number].append(record)
    outcomes, duplicates = [], 0
    for number, items in sorted(grouped.items()):
        semantic = {(_status_groups.get(key(row.status), 'unknown'),
                     key(row.status) if key(row.status) not in _status_groups else '',
                     key(aliases.get(key(row.recipient), row.recipient))) for row in items}
        conflict = len(semantic) != 1
        duplicates += len(items)-1 if not conflict else 0
        row = items[0]
        outcomes.append({'number': number,
                         'group': 'conflict' if conflict else _status_groups.get(key(row.status), 'unknown'),
                         'status': ' / '.join(dict.fromkeys(x.status or '(boş)' for x in items)),
                         'recipient': ' / '.join(dict.fromkeys(aliases.get(key(x.recipient), x.recipient) or '(boş)' for x in items)),
                         'source_rows': [x.source_row for x in items]})
    selected = [row for row in outcomes if row['group'] in {'announced', 'pending'}]
    counts = Counter(row['group'] for row in outcomes)
    observed_recipients = Counter(row['recipient'] for row in selected)
    present_recipients = [name for name in reference if name in observed_recipients]
    missing_recipients = [name for name in reference if name not in observed_recipients]
    other_recipients = [name for name in observed_recipients if name not in reference]
    ranges = number_ranges(row['number'] for row in selected)
    return {'report_version': REPORT_VERSION, 'first': first, 'last': last, 'term': term, 'counts': dict(counts),
            'total': len(outcomes), 'selected_count': len(selected),
            'ranges': ranges, 'ranges_text': ';'.join(ranges),
            'ranges_by_status': {group: number_ranges(row['number'] for row in outcomes if row['group'] == group)
                                 for group in STATUS_LABELS},
            'present_recipients': present_recipients, 'missing_recipients': missing_recipients,
            'other_recipients': other_recipients, 'recipient_counts': dict(observed_recipients),
            'absent_count': last-first+1-len(outcomes),
            'absent_ranges': absent_ranges(grouped, first, last),
            'invalid_rows': invalid_rows, 'duplicate_count': duplicates, 'rows': outcomes}


def report_text(report):
    lines = [f"Gelen Kağıt İşlemleri · {report['first']}–{report['last']}", '',
             'Cevaplanmamış / cevap süresi devam eden esas numarası aralıkları:',
             report['ranges_text'] or 'Yok', f"Toplam: {report['selected_count']} önerge.", '']
    for group, label in STATUS_LABELS.items():
        lines.append(f"{label}: {report['counts'].get(group, 0)}")
    lines.extend(['', f"Bulunan bakanlıklar ve muhataplar ({len(report['present_recipients'])}):",
                  *report['present_recipients'], '',
                  f"Listede bulunmayanlar ({len(report['missing_recipients'])}):", *report['missing_recipients']])
    if report['other_recipients']:
        lines.extend(['', 'Referans listesi dışında kalan muhataplar:', *report['other_recipients']])
    if report['absent_count']:
        lines.extend(['', f"Dosyada bulunmayan {report['absent_count']} esas numarası (sonuca dahil edilmedi):", *report['absent_ranges']])
    if report['invalid_rows']:
        lines.append('\nEsas numarası okunamayan kaynak satırları: ' + ', '.join(map(str, report['invalid_rows'])))
    return '\n'.join(lines)


def report_csv(report):
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Esas No', 'Dönem', 'İşlem grubu', 'Kaynak durum', 'Muhatap', 'Kaynak satırları'])
    def safe_cell(value):
        text = str(value)
        return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text
    for row in report['rows']:
        writer.writerow([row['number'], safe_cell(report['term']), STATUS_LABELS[row['group']],
                         safe_cell(row['status']), safe_cell(row['recipient']), ', '.join(map(str, row['source_rows']))])
    return output.getvalue().encode('utf-8-sig')
