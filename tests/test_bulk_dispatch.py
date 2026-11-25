"""Numbered lists with one recipient heading for each block of proposals."""
import io

import openpyxl
import pytest

import bulk_review as bulk
from incoming_papers import sheet_names
from test_bulk_packet import packet
from test_bulk_review import reading
from test_incoming_papers import workbook


HEADER = ['SIRA NO', 'ESAS NO', 'SAHİBİ VE ÖZETİ']
OWNER = "Kocaeli Milletvekili Ömer Faruk GERGERLİOĞLU'nun, İstanbul ve Sağlık Bakanlığı hakkındaki iddialara ilişkin"


def dispatch_rows():
    return [[None, None, 'ADALET BAKANLIĞI'], HEADER,
            [1, '7/50000', OWNER], [None, None, None], HEADER, [2, '7/50001', OWNER],
            [None, None, 'SAĞLIK BAKANLIĞI'], HEADER, [1, '7/50002', OWNER],
            [None, None, 'CUMHURBAŞKANI YARDIMCISI (CEVDET YILMAZ)'], HEADER, [1, '7/50003', OWNER]]


def test_dispatch_groups_repeated_headers_and_serial_resets_keep_exact_ids():
    records, invalid = bulk.read_kkbs(workbook(dispatch_rows()), 'Rapor')
    assert not invalid and [r.number for r in records] == [50000, 50001, 50002, 50003]
    assert [r.title for r in records] == ['ADALET BAKANLIĞI', 'ADALET BAKANLIĞI', 'SAĞLIK BAKANLIĞI', 'CUMHURBAŞKANI YARDIMCISI']
    assert [(r.member, r.province) for r in records] == [('Ömer Faruk GERGERLİOĞLU', 'Kocaeli')] * 4
    assert [r.source_row for r in records] == [3, 6, 9, 12]
    assert all(not r.minister and not r.minister_in_source for r in records[:3])
    assert records[-1].minister == 'CEVDET YILMAZ' and records[-1].minister_in_source


def test_department_and_minister_title_equivalence_and_only_available_fields():
    records, _ = bulk.read_kkbs(workbook(dispatch_rows()), 'Rapor')
    review, pages = reading()
    assert not bulk.compare_proposal(review, pages, [18], records)['issues']
    review.number.value = '7/50002'
    review.number.quote = review.number.quote.replace('50000', '50002')
    review.pages[0].text = review.pages[0].text.replace('50000', '50002')
    pages[0]['ocr'] = review.pages[0].text
    result = bulk.compare_proposal(review, pages, [20], records)
    mismatches = [i for i in result['issues'] if i['field'] == 'KKBS · Muhatap bakanlık']
    assert len(mismatches) == 1 and mismatches[0]['status'] == 'uyari'
    assert mismatches[0]['expected'] == 'SAĞLIK BAKANLIĞI'
    assert not any(i['field'] == 'KKBS · Muhatap bakan' for i in result['issues'])


def test_missing_and_unrecognized_headers_never_reuse_previous_ministry():
    with pytest.raises(bulk.TableError, match='bölüm başlığı bulunamadı'):
        bulk.read_kkbs(workbook([HEADER, [1, '7/50000', OWNER]]), 'Rapor')
    rows = dispatch_rows()
    rows[6][2] = 'OKUNAMAYAN BAŞLIK'
    with pytest.raises(bulk.TableError, match='önceki bakanlığa aktarılmadı'):
        bulk.read_kkbs(workbook(rows), 'Rapor')


def test_missing_or_invalid_essential_numbers_are_not_replaced_by_serial():
    rows = dispatch_rows()
    rows[2][1] = None
    rows[5][1] = '8/50001'
    records, invalid = bulk.read_kkbs(workbook(rows), 'Rapor')
    assert invalid == [3, 6]
    assert [r.number for r in records] == [50002, 50003]


def test_dispatch_supports_merged_heading_and_ignores_optional_evrak_column():
    book = openpyxl.Workbook()
    ws = book.active
    ws.append(['ADALET BAKANLIĞI'])
    ws.merge_cells('A1:D1')
    ws.append(['SIRA NO', 'ESAS NO', 'EVRAK KAYIT NO', 'SAHİBİ VE ÖZETİ'])
    ws.append([1, '7/50000', 1980000, OWNER])
    data = io.BytesIO()
    book.save(data)
    records, invalid = bulk.read_kkbs(data.getvalue(), ws.title)
    assert not invalid and records[0].number == 50000
    assert records[0].title == 'ADALET BAKANLIĞI'
    assert not hasattr(records[0], 'evrak')


def test_dispatch_missing_owner_is_a_real_missing_value_not_an_invented_person():
    rows = dispatch_rows()
    rows[2][2] = None
    records, _ = bulk.read_kkbs(workbook(rows), 'Rapor')
    assert not records[0].member and not records[0].province
    review, pages = reading()
    result = bulk.compare_proposal(review, pages, [18], records)
    assert any(i['field'] == 'KKBS · Milletvekili' and i['status'] == 'belirsiz' for i in result['issues'])


def test_auto_selection_accepts_dispatch_only_but_prefers_full_source_if_present():
    data = workbook(dispatch_rows())
    assert bulk.default_kkbs_sheet(data, sheet_names(data)) == 'Rapor'
    book = openpyxl.load_workbook(io.BytesIO(packet()))
    book.move_sheet('İlk Çıkış', offset=-2)
    data = io.BytesIO()
    book.save(data)
    assert bulk.default_kkbs_sheet(data.getvalue(), sheet_names(data.getvalue())) == 'Veri'


def test_conflicting_duplicate_numbers_across_ministries_remain_suspect():
    rows = dispatch_rows()
    rows[8][1] = '7/50000'
    records, _ = bulk.read_kkbs(workbook(rows), 'Rapor')
    records = bulk.select_records(records)
    review, pages = reading()
    result = bulk.compare_proposal(review, pages, [18], records)
    assert not result['matched']
    assert any('çelişkili' in i['explanation'] for i in result['issues'])
