"""Import the user's KKBS member directory without touching minister/summary sources."""
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook


def build(path):
    book = load_workbook(path, read_only=True, data_only=True)
    pairs = defaultdict(set)
    count = 0
    try:
        sheet = book.active
        rows = sheet.iter_rows(values_only=True)
        required = {'Adı', 'Soyadı', 'Seçim Çevresi', 'Dönem'}
        for header_row, values in enumerate(rows, 1):
            headers = [str(v or '').strip() for v in values]
            if required <= set(headers):
                break
            if header_row >= 20:
                raise ValueError('Milletvekili listesinin başlığı bulunamadı.')
        else:
            raise ValueError('Milletvekili listesinin başlığı bulunamadı.')
        for number, values in enumerate(rows, header_row + 1):
            if not any(values):
                continue
            row = dict(zip(headers, values))
            if any(not str(row.get(k) or '').strip() for k in required):
                raise ValueError(f'Satır {number}: ad, soyad, seçim çevresi veya dönem boş.')
            if row['Dönem'].strip() != '28.DÖNEM':
                raise ValueError(f'Satır {number}: farklı yasama dönemi; kaynakları karıştırmayın.')
            name = ' '.join((row['Adı'] + ' ' + row['Soyadı']).split())
            pairs[name].add(' '.join(row['Seçim Çevresi'].split()))
            count += 1
        if not pairs:
            raise ValueError('Milletvekili listesi boş.')
        return {
            'source': {'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                       'sheet': sheet.title, 'header_row': header_row, 'term': '28.DÖNEM',
                       'row_count': count, 'member_count': sum(map(len, pairs.values())),
                       'name_count': len(pairs)},
            'members': {n: next(iter(p)) for n, p in sorted(pairs.items()) if len(p) == 1},
            'namesakes': {n: sorted(p) for n, p in sorted(pairs.items()) if len(p) > 1},
            'scope': 'Kullanıcının KKBS milletvekili listesindeki 28. dönem ad–seçim çevresi eşleşmeleri. '
                     'Aynı adlı kişiler seçim çevresiyle ayrılır. Ayrılmış üyeler dahil; aktif görev durumu denetlenmez.',
            'invalid_constituency_labels': ['Dersim'],
        }
    finally:
        book.close()


if __name__ == '__main__':
    result = build(Path(sys.argv[1]))
    output = Path(__file__).resolve().parents[1] / 'member_reference.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"{result['source']['member_count']} ad–il eşleşmesi; {len(result['namesakes'])} aynı adlı grup")
