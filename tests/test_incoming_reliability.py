import csv
import io
import random
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import RULES
from incoming_papers import (TableError, build_report, read_excel, read_paste, read_records,
                             report_csv, report_text, sheet_names)
from test_incoming_papers import ANNOUNCED, PENDING, workbook


def report(rows, first=1, last=3, stage='prepare'):
    return build_report(read_records(rows), first, last, None, RULES['recipients'], stage=stage)


def test_partial_header_never_falls_back_to_general_document_number():
    rows = [['Genel Evrak No', 'Esas No', 'Yeni durum başlığı', 'Muhatap Unvanı'],
            [123456, 49220, PENDING, 'Adalet Bakanı']]
    with pytest.raises(TableError, match='Son Durum'):
        read_records(rows)
    with pytest.raises(TableError, match='Son Durum'):
        read_excel(workbook(rows), 'Rapor')


def test_full_kkbs_rows_without_headers_are_rejected_instead_of_misread():
    with pytest.raises(TableError, match='başlıklarıyla'):
        read_paste(f'123456\t19.10.2026\t28.DÖNEM\t4\t7/49220\tÖzet\t{PENDING}\tAdalet Bakanı')


def test_no_valid_numbers_is_a_read_error_instead_of_all_ministries_missing():
    with pytest.raises(TableError, match='geçerli numara'):
        read_records([['Esas No', 'Son Durum', 'Muhatap Unvanı'], ['=1+1', PENDING, 'Adalet Bakanı']])


def test_duplicate_headers_and_repeated_print_headers():
    header = ['Esas No', 'Son Durum', 'Muhatap Unvanı']
    records = read_records([header, [1, PENDING, 'Adalet Bakanı'], header, [2, PENDING, 'Sağlık Bakanı']])
    assert [row.number for row in records] == [1, 2]
    with pytest.raises(TableError, match='Birden fazla'):
        read_records([header + ['Durum'], [1, PENDING, 'Adalet Bakanı', PENDING]])


def test_quoted_csv_delimiters_and_multiline_cells_do_not_move_columns():
    for delimiter in (',', ';', '\t'):
        out = io.StringIO()
        writer = csv.writer(out, delimiter=delimiter)
        writer.writerow(['Esas No', 'Son Durum', 'Muhatap Unvanı', 'Özet'])
        writer.writerow([1, PENDING, 'Çevre, Şehircilik ve İklim Değişikliği Bakanı', 'Bir; özet,\nikinci\tsatır'])
        rows = read_paste(out.getvalue())
        assert rows[0].number == 1
        assert rows[0].status == PENDING
        assert rows[0].recipient == 'Çevre, Şehircilik ve İklim Değişikliği Bakanı'
    with pytest.raises(TableError):
        read_paste('Esas No\tSon Durum\tMuhatap Unvanı\n1\t"kapanmayan alıntı')


def test_incorrect_excel_dimensions_and_empty_formatted_columns():
    data = workbook([['Esas No', 'Son Durum', 'Muhatap Unvanı'], [1, PENDING, 'Adalet Bakanı']])
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, 'w') as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == 'xl/worksheets/sheet1.xml':
                content = re.sub(rb'<dimension ref="[^"]+"', b'<dimension ref="A1:A1"', content)
            target.writestr(item, content)
    assert [r.number for r in read_excel(out.getvalue(), 'Rapor')] == [1]
    rows = read_records([['Esas No', 'Son Durum', 'Muhatap Unvanı'] + [None] * 200,
                         [1, PENDING, 'Adalet Bakanı'] + [None] * 200])
    assert rows[0].number == 1


def test_sheet_listing_does_not_load_shared_strings(monkeypatch):
    data = workbook([['Esas No', 'Son Durum', 'Muhatap Unvanı'], [1, PENDING, 'Adalet Bakanı']])
    def no_load(*args, **kwargs):
        raise AssertionError('Sheet listing must not load workbook data')
    monkeypatch.setattr('incoming_papers.load_workbook', no_load)
    assert sheet_names(data) == ['Rapor']


def test_workbook_size_and_missing_sheet_errors_are_controlled(monkeypatch):
    data = workbook([['Esas No', 'Son Durum', 'Muhatap Unvanı'], [1, PENDING, 'Adalet Bakanı']])
    with pytest.raises(TableError, match='sayfası bulunamadı'):
        read_excel(data, 'Başka sayfa')
    monkeypatch.setattr('incoming_papers.MAX_UNPACKED_BYTES', 100)
    for load in (sheet_names, lambda data: read_excel(data, 'Rapor')):
        with pytest.raises(TableError, match='boyutu çok büyük'):
            load(data)


def test_same_institution_spelling_variants_count_once_and_unknowns_remain_unknown():
    result = report([[1, PENDING, 'Adalet Bakanı'], [1, PENDING, 'ADALET BAKANLIĞINA'],
                     [2, PENDING, 'Cumhurbaşkanı Yardımcılığı'], [3, PENDING, 'Adalet Komisyonu']])
    assert result['selected_count'] == 3
    assert result['duplicate_count'] == 1
    assert result['present_recipients'] == ['Cumhurbaşkanı Yardımcısı', 'Adalet Bakanlığı']
    assert result['other_recipients'] == ['Adalet Komisyonu']
    assert not result['assessment_complete']


def test_report_explains_empty_and_incomplete_data_in_exports():
    no_match = report([[5, PENDING, 'Adalet Bakanı']])
    assert (no_match['source_first'], no_match['source_last']) == (5, 5)
    assert 'bakanlıklar değerlendirilemedi' in report_text(no_match)
    assert 'Listede bulunmayanlar (18)' not in report_text(no_match)
    unknown = report([[1, 'Yeni durum', 'Adalet Bakanı']], 1, 1)
    assert unknown['unrecognized_statuses'] == {'Yeni durum': 1}
    assert not unknown['assessment_complete']
    assert 'VERİ KONTROLÜ GEREKLİ' in report_text(unknown)
    assert 'Listede bulunmayanlar (18)' not in report_text(unknown)
    complete = report([[1, PENDING, 'Adalet Bakanı']], 1, 1)
    assert complete['assessment_complete']
    assert 'Listede bulunmayanlar (17)' in report_text(complete)


def test_randomized_ranges_match_independent_status_selection():
    rng = random.Random(21102026)
    for _ in range(100):
        rows = [[number, rng.choice([PENDING, ANNOUNCED, 'Cevaplandı', 'Geri Alındı']), 'Adalet Bakanı']
                for number in range(1, 101) if rng.random() > .15]
        first, last = sorted(rng.sample(range(1, 101), 2))
        stage = rng.choice(['prepare', 'verify'])
        result = report(rows, first, last, stage=stage)
        expected = {number for number, status, _ in rows
                    if first <= number <= last and status == (PENDING if stage == 'prepare' else ANNOUNCED)}
        expanded = set()
        for part in result['ranges']:
            ends = list(map(int, part.split('-')))
            expanded.update(range(ends[0], ends[-1]+1))
        assert expanded == expected
        assert result['selected_count'] == len(expected)
        assert sum(result['counts'].values()) == result['total']
        assert result['total'] + result['absent_count'] == last-first+1


def test_parallel_workbook_reads_and_reports_are_independent():
    def generate(index):
        first = index * 10 + 1
        recipient = list(RULES['recipients'])[index]
        data = workbook([['Esas No', 'Son Durum', 'Muhatap Unvanı'], [first, PENDING, recipient]])
        result = build_report(read_excel(data, sheet_names(data)[0]), first, first, None, RULES['recipients'])
        assert result['ranges_text'] == f'{first}-{first}'
        assert result['selected_count'] == 1
        assert len(result['present_recipients']) == 1
        assert len(list(csv.reader(io.StringIO(report_csv(result).decode('utf-8-sig')), delimiter=';'))) == 2
        return result['present_recipients'][0]
    with ThreadPoolExecutor(max_workers=4) as pool:
        names = list(pool.map(generate, range(4)))
    assert len(set(names)) == 4


def test_workflow_stages_never_merge_and_updated_cells_move_to_expert_list():
    rows = [[1, PENDING, 'Adalet Bakanı'], [2, ANNOUNCED, 'Sağlık Bakanı'],
            [3, 'Cevaplandı', 'İçişleri Bakanı'], [4, 'Süresi Geçtikten Sonra Cevaplandı', 'Ticaret Bakanı'],
            [5, 'Geri Alındı', 'Dışişleri Bakanı']]
    prepared = report(rows, 1, 5, 'prepare')
    verified = report(rows, 1, 5, 'verify')
    assert prepared['ranges_text'] == '1-1'
    assert prepared['present_recipients'] == ['Adalet Bakanlığı']
    assert prepared['assessment_complete']
    assert verified['ranges_text'] == '2-2'
    assert verified['present_recipients'] == ['Sağlık Bakanlığı']
    assert not verified['assessment_complete']
    assert '1 önerge hâlâ' in verified['workflow_warning']
    rows[0][1] = ANNOUNCED
    verified = report(rows, 1, 5, 'verify')
    assert verified['ranges_text'] == '1-2'
    assert verified['assessment_complete']
    assert not verified['workflow_warning']
    exported = list(csv.DictReader(io.StringIO(report_csv(verified).decode('utf-8-sig')), delimiter=';'))
    assert [row['Esas No'] for row in exported if row['Aşama listesine dahil'] == 'Evet'] == ['1', '2']
    assert 'Uzman kontrolü' in report_text(verified)
    with pytest.raises(TableError, match='aşamasını'):
        report(rows, stage='both')
