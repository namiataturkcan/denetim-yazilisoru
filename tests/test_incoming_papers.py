import io

import pytest
from openpyxl import Workbook

from app import RULES
from incoming_papers import (Record, TableError, build_report, number_ranges, parse_number,
    read_excel, read_paste, read_records, recipient_names, report_csv, report_text, sheet_names)


ANNOUNCED = 'Cevaplanmadığı Gelen Kağıtlarda İlan Edildi'
PENDING = '15 Günlük Cevaplanma Süresi Devam Ediyor'


def workbook(rows, sheet='Rapor'):
    book = Workbook()
    book.active.title = sheet
    for row in rows:
        book.active.append(row)
    out = io.BytesIO()
    book.save(out)
    book.close()
    return out.getvalue()


def run(rows, first=1, last=5, term=''):
    return build_report(read_records(rows), first, last, term, RULES['recipients'])


def test_reference_conversation_range_and_18_recipient_difference():
    excluded = {49233, 49235, 49269, 49270, 49276, 49290, 49291, 49292,
                49296, 49297, 49302, 49303, 49304}
    recipients = [title for title in RULES['recipients'] if title not in {'Dışişleri Bakanı', 'Millî Savunma Bakanı'}]
    rows = [[number, 'Cevaplandı' if number in excluded else PENDING, recipients[index % 16]]
            for index, number in enumerate(range(49220, 49330))]
    result = run(rows, 49220, 49329)
    assert result['total'] == 110
    assert result['selected_count'] == 97
    assert result['counts'] == {'pending': 97, 'answered': 13}
    assert result['ranges'] == ['49220–49232', '49234', '49236–49268', '49271–49275',
                                '49277–49289', '49293–49295', '49298–49301', '49305–49329']
    assert result['missing_recipients'] == ['Dışişleri Bakanlığı', 'Millî Savunma Bakanlığı']
    assert len(result['present_recipients']) == 16
    assert not result['absent_count']
    assert 'Toplam: 97 önerge.' in report_text(result)


def test_historic_conversation_single_answered_gap():
    result = run([[n, 'Cevaplandı' if n == 45694 else ANNOUNCED, 'ADALET BAKANI']
                  for n in range(45628, 45697)], 45628, 45696)
    assert result['ranges'] == ['45628–45693', '45695–45696']
    assert result['selected_count'] == 68


def test_current_statuses_are_separate_and_late_answers_are_excluded():
    statuses = [ANNOUNCED, PENDING, 'Cevaplandı', 'Süresi Geçtikten Sonra Cevaplandı',
                'Önerge Sahibi Tarafından Geri Alındı']
    result = run([[index, status, 'İÇİŞLERİ BAKANI'] for index, status in enumerate(statuses, 1)])
    assert result['selected_count'] == 2
    assert result['counts'] == {'announced': 1, 'pending': 1, 'answered': 2, 'withdrawn': 1}
    assert result['ranges_by_status']['announced'] == ['1']
    assert result['ranges_by_status']['pending'] == ['2']


def test_missing_numbers_unknown_statuses_and_unknown_recipients_are_explicit():
    result = run([[1, ANNOUNCED, 'TBMM Başkanı'], [3, 'Bilinmeyen yeni durum', 'Adalet Bakanı'],
                  ['hatalı numara', PENDING, 'Adalet Bakanı']])
    assert result['selected_count'] == 1
    assert result['absent_count'] == 3
    assert result['absent_ranges'] == ['2', '4–5']
    assert result['counts']['unknown'] == 1
    assert result['other_recipients'] == ['TBMM Başkanı']
    assert len(result['missing_recipients']) == 18
    assert result['invalid_rows'] == [3]


def test_duplicates_do_not_double_count_and_conflicts_are_not_guessed():
    result = run([[1, PENDING, 'Adalet Bakanı'], [1, PENDING, 'ADALET BAKANI'],
                  [2, PENDING, 'İçişleri Bakanı'], [2, 'Cevaplandı', 'İçişleri Bakanı'],
                  [3, PENDING, 'Sağlık Bakanı'], [3, PENDING, 'Adalet Bakanı']])
    assert result['total'] == 3
    assert result['selected_count'] == 1
    assert result['duplicate_count'] == 1
    assert result['counts']['conflict'] == 2


def test_terms_are_filtered_before_deduplication():
    rows = [['Dönem Adı', 'Esas No', 'Son Durum', 'Muhatap Unvanı'],
            ['27.DÖNEM', 1, 'Cevaplandı', 'İçişleri Bakanı'],
            ['28.DÖNEM', 1, PENDING, 'Adalet Bakanı']]
    result = run(rows, 1, 1, '28. Dönem')
    assert result['selected_count'] == 1
    assert result['present_recipients'] == ['Adalet Bakanlığı']
    with pytest.raises(TableError):
        run(rows, 1, 1)


def test_excel_named_columns_in_arbitrary_order_and_extra_columns():
    rows = [['Özet', 'Esas No', 'Son Durum', 'Muhatap Unvanı', 'Donem Adı'],
            ['İşlenmeyen özel metin', '7/49220', PENDING, 'MİLLİ EĞİTİM BAKANI', '28.DÖNEM']]
    data = workbook(rows)
    assert sheet_names(data) == ['Rapor']
    records = read_excel(data, 'Rapor')
    assert records == [Record(49220, PENDING, 'MİLLİ EĞİTİM BAKANI', '28. Dönem', 2)]
    result = build_report(records, 49220, 49220, '28. Dönem', RULES['recipients'])
    assert result['present_recipients'] == ['Millî Eğitim Bakanlığı']
    assert 'özel metin' not in repr(records)


@pytest.mark.parametrize('value,expected', [(49220, 49220), (49220.0, 49220),
    ('7/49220', 49220), ('7 / 49220', 49220), ('49.220', 49220), ('0049', 49)])
def test_number_formats(value, expected):
    assert parse_number(value) == expected


@pytest.mark.parametrize('value', [None, True, -3, 0, 12.4, '01.01.2026', '3/49220', '=1234', '12abc'])
def test_bad_number_formats_are_rejected(value):
    with pytest.raises(ValueError):
        parse_number(value)


def test_paste_with_or_without_headers_and_extra_tabs():
    row = f'49220\t{PENDING}\tİÇİŞLERİ BAKANI\tKişi adı\t\t\t'
    assert read_paste(row)[0].number == 49220
    assert read_paste('Esas No\tSon Durum\tMuhatap Unvanı\n' + row)[0].source_row == 2


def test_paste_semicolon_and_empty_input():
    assert read_paste(f'1;{PENDING};Adalet Bakanı')[0].number == 1
    with pytest.raises(TableError):
        read_paste('')


def test_duplicate_headers_and_invalid_workbooks_are_rejected():
    with pytest.raises(TableError, match='Birden fazla'):
        read_records([['Esas No', 'Esas Numarası', 'Son Durum', 'Muhatap Unvanı']])
    with pytest.raises(TableError):
        read_excel(b'not an excel file', 'Rapor')


def test_bounds_and_compression_are_inclusive_and_never_expand_missing_range():
    result = run([[5, PENDING, 'Adalet Bakanı']], 1, 999999999)
    assert result['absent_count'] == 999999998
    assert result['absent_ranges'] == ['1–4', '6–999999999']
    assert number_ranges([5, 2, 1, 2, 7, 8]) == ['1–2', '5', '7–8']
    with pytest.raises(TableError):
        run([[5, PENDING, 'Adalet Bakanı']], 6, 5)


def test_csv_export_prevents_spreadsheet_formula_execution():
    result = run([[1, '=HYPERLINK("test")', '@recipient']])
    csv = report_csv(result).decode('utf-8-sig')
    assert "'=HYPERLINK" in csv
    assert "'@recipient" in csv


def test_recipient_order_and_names_preserve_reference_list():
    names = recipient_names(RULES['recipients'])
    assert len(names) == 18
    assert names[0] == 'Cumhurbaşkanı Yardımcısı'
    assert names[1] == 'Adalet Bakanlığı'
    assert names[-1] == 'Ulaştırma ve Altyapı Bakanlığı'
