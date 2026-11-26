"""Extract and cross-check the user's 2018 Interior Ministry PDF directory."""
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pymupdf

SOURCE_URL = ('https://www.icisleri.gov.tr/kurumlar/icisleri.gov.tr/IcSite/illeridaresi/Bilgiler2/'
              '%C4%B0l%20ve%20%C4%B0l%C3%A7e%20Kurulu%C5%9F%20Tarihleri%202018.pdf')
UPPER = 'A-ZÇĞİÖŞÜÂÎÛ'
ROW = re.compile(r'^\s*(\d{1,2})\s+([' + UPPER + r'][' + UPPER + r' ()0-9-]*?)\s{2,}(.*)$', re.M)


def title(value):
    # Source spellings are preserved; only Turkish uppercase is made readable.
    return ' '.join(w[0] + w[1:].translate(str.maketrans('Iİ', 'ıi')).lower() for w in value.split())


def build(path, *, expected_counts=(81, 922)):
    provinces, pages = defaultdict(list), defaultdict(list)
    with pymupdf.open(path) as document:
        for page_number, page in enumerate(document, 1):
            words = page.get_text('words')
            headings = [w[4].strip('*') for w in words
                        if w[1] < 120 and re.fullmatch(r'\*[' + UPPER + r']+\*?', w[4])]
            numbers = [w for w in words if 65 < w[0] < 105 and 155 < w[1] < 790 and w[4].isdigit()]
            if page_number == 1 and not headings and not numbers:
                continue  # The source's cover is not a province table.
            if len(headings) != 1 or not numbers:
                raise ValueError(f'Sayfa {page_number}: il başlığı veya ilçe satırları okunamadı.')
            province = title(headings[0])
            rows = []
            for number in sorted(numbers, key=lambda w: w[1]):
                cells = sorted((w for w in words if 105 < w[0] < 235 and abs(w[1]-number[1]) < 4), key=lambda w: w[0])
                name = ' '.join(w[4] for w in cells)
                if not re.fullmatch(r'[' + UPPER + r'][' + UPPER + r' 0-9-]*', name):
                    raise ValueError(f'Sayfa {page_number}, satır {number[4]}: ilçe adı ayrıştırılamadı.')
                rows.append((int(number[4]), name))
            # Independent reading by text lines catches dropped/misaligned cells.
            text_rows = [(int(n), name.strip()) for n, name, _ in ROW.findall(page.get_text(sort=True))]
            if rows != text_rows:
                raise ValueError(f'Sayfa {page_number}: konum ve metin okumaları uyuşmuyor.')
            for number, name in rows:
                if number != len(provinces[province])+1 or title(name) in provinces[province]:
                    raise ValueError(f'{province}, satır {number}: eksik, tekrarlı veya sırasız ilçe.')
                provinces[province].append(title(name))
            pages[province].append(page_number)
        counts = len(provinces), sum(map(len, provinces.values()))
        if counts != expected_counts:
            raise ValueError(f'İl/ilçe kapsamı eksik: {counts}; beklenen {expected_counts}.')
        return {
            'source': {'file': path.name, 'url': SOURCE_URL,
                       'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                       'list_year': 2018, 'pdf_creation_date': document.metadata.get('creationDate'),
                       'page_count': len(document), 'province_count': counts[0], 'district_count': counts[1],
                       'scope': 'PDF tablolarındaki numaralı ilçe satırları. İl başlıkları ilçe kaydı değildir; '
                                'numarasız merkez ilçeler eklenmemiştir. Güncel statü listesi değildir.'},
            'provinces': dict(provinces), 'province_pages': dict(pages),
        }


if __name__ == '__main__':
    result = build(Path(sys.argv[1]))
    output = Path(__file__).resolve().parents[1] / 'district_reference.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f"{result['source']['province_count']} il; {result['source']['district_count']} ilçe; iki okuma eşleşti.")
