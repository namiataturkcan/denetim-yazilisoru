import io

import pytest
from openpyxl import Workbook

from app import RULES
from entry_comparison import (Sheet, compare_members, compare_records, document_id,
                              folded, member_name, ministry_identity, read_sheets,
                              records, report_csv, suggest_columns, suggest_header)
from incoming_papers import TableError

RECIPIENTS = RULES['recipients']
HEADERS = ['Genel Evrak Numarası', 'Önerge Sahibi', 'Önerge Muhatabı', 'Esas No', 'Açıklama']


def workbook(left=None, right=None, headers=HEADERS):
    book = Workbook()
    book.active.title = 'KKBS'
    book.create_sheet('EBYS')
    for sheet, rows in zip(book, (left, right)):
        sheet.append(['Rapor başlığı'])
        sheet.append(headers)
        for row in rows if rows is not None else [[100, 'Çiçek Otlu', 'Çevre Bakanı', '7/50000', None]]:
            sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def record(doc='100', member='Çiçek Otlu', ministry='Çevre Bakanı', row=3):
    return dict(document=doc, id=document_id(doc), member=member, ministry=ministry, row=row, case='7/50000')


def compare(left=None, right=None, names=()):
    return compare_records(left or [record()], right or [record()], RECIPIENTS, names)


def test_different_people_with_shared_name_and_different_ministries_are_reported():
    report = compare([record(member='Cengiz Çiçek')], [record(member='Çiçek Otlu', ministry='Adalet Bakanı', row=8)])
    assert report['different'] == 1 and report['matched'] == 1
    assert {i['field'] for i in report['issues']} == {'member', 'ministry'}
    assert all(i['status'] == 'uyari' and i['kkbs_row'] == 3 and i['ebys_row'] == 8 for i in report['issues'])
    assert report['api_requests'] == 0


@pytest.mark.parametrize('raw', ['ÇEVRE BAKANI', 'Çevre Bakanlığına', 'Çevre Bakanlığı',
    'Çevre, Şehircilik ve İklim Değişikliği Bakanı Murat KURUM', 'Murat KURUM'])
def test_short_ministry_and_full_title_are_same_office(raw):
    report = compare(right=[record(ministry=raw)])
    assert report['clean'] == 1 and not report['issues']


@pytest.mark.parametrize('title,name', RECIPIENTS.items())
def test_all_user_offices_and_exact_minister_names(title, name):
    assert ministry_identity(title, RECIPIENTS)[0] == ministry_identity(name, RECIPIENTS)[0]
    assert ministry_identity(title+' '+name, RECIPIENTS)[0] is not None


def test_explicit_office_has_priority_over_minister_name():
    assert ministry_identity('Adalet Bakanı Murat Kurum', RECIPIENTS)[0] == 'Adalet Bakanlığı'
    assert ministry_identity('Bilinmeyen Bakanı Murat Kurum', RECIPIENTS)[0] is None
    assert ministry_identity('Murat', RECIPIENTS)[0] is None
    assert ministry_identity('Ali Yerlikaya', RECIPIENTS)[0] is None


def test_interior_exterior_and_multiple_offices_are_not_merged():
    report = compare([record(ministry='İçişleri Bakanı')], [record(ministry='Dışişleri Bakanı')])
    assert report['different'] == 1
    assert ministry_identity('Adalet Bakanı ve Çevre Bakanı', RECIPIENTS)[0] is None


def test_typo_is_explained_and_not_a_red_mismatch():
    report = compare(right=[record(member='Çiçek Otllu', ministry='Çevrre Bakanı')])
    assert report['spelling'] == 1 and report['complete']
    assert len(report['variants']) == 2 and not report['issues']


def test_distinct_known_names_never_excused_as_typo_and_ambiguous_typo_needs_review():
    known = {folded(n).replace(' ', '') for n in ['Ahmet Yılmaz', 'Ahmet Yılman']}
    assert compare_members('Ahmet Yılmaz', 'Ahmet Yılman', known)[0] == 'uyari'
    assert compare_members('Ahmet Yılmaz', 'Ahmet Yılmas', known)[0] == 'belirsiz'


@pytest.mark.parametrize('name', ['ÇİÇEK OTLU', 'Cicek Otlu', 'İstanbul Milletvekili Çiçek Otlu’nun, bir konuya ilişkin önergesi',
                                  'Çiçek Otlu (İstanbul Milletvekili)', 'Sayın Dr. Çiçek Otlu'])
def test_member_orthography_titles_and_combined_summary(name):
    assert compare(right=[record(member=name)])['clean'] == 1


@pytest.mark.parametrize('name', ['', 'Çiçek', 'İstanbul Milletvekili', 'Bu önerge başka konuda hazırlanmış olup İstanbul Milletvekili Çiçek Otlu tarafından gönderildi'])
def test_missing_or_unparseable_name_is_not_green(name):
    report = compare(right=[record(member=name)])
    assert report['uncertain'] == 1 and not report['complete']


def test_reversed_name_is_visible_as_variant():
    assert compare(right=[record(member='Otlu Çiçek')])['spelling'] == 1


def test_rows_join_by_id_even_when_order_differs():
    left = [record('100'), record('101', member='Cengiz Çiçek')]
    report = compare(left, list(reversed(left)))
    assert report['matched'] == report['clean'] == 2 and report['complete']


@pytest.mark.parametrize('a,b', [('2026/123', '123'), ('2025/123', '2026/123'), ('100', '101')])
def test_unmatched_ids_do_not_fall_back_to_name_or_order(a, b):
    report = compare([record(a)], [record(b)])
    assert report['matched'] == 0 and not report['complete']
    assert len(report['issues']) == 2


def test_duplicate_and_missing_ids_remain_visible_and_are_not_paired():
    report = compare([record('100'), record('100', row=4), record('', row=5)], [record('100'), record('101', row=4)])
    assert report['matched'] == 0 and not report['complete']
    assert report['unmatched_kkbs'] == 3 and report['unmatched_ebys'] == 2
    assert len(report['issues']) == 3
    assert any(i['kkbs_row'] == '3, 4' for i in report['issues'])


@pytest.mark.parametrize('raw,expected', [(123.0, '123'), ('1.980.172', '1980172'), ('1 980 172', '1980172'),
    ('2026/123', '2026/123'), ('E-123', 'E-123'), ('00123', '00123'), (True, ''), (None, ''), ('Esas No', '')])
def test_document_id_normalization(raw, expected):
    assert document_id(raw) == expected


def test_workbook_headers_blank_descriptions_and_repeated_headers():
    data = workbook(left=[[100, 'Çiçek Otlu', 'Çevre Bakanı', '7/50000', None], HEADERS,
                          [101, 'Cengiz Çiçek', 'Adalet Bakanı', '7/50001', '']])
    sheets = read_sheets(data, ['KKBS', 'EBYS'])
    assert suggest_header(sheets[0]) == 2
    rows = records(sheets[0], 2, suggest_columns(sheets[0].headers(2)))
    assert len(rows) == 2 and [r['row'] for r in rows] == [3, 5]
    assert rows[0]['id'] == '100'


def test_manual_mapping_and_combined_text_work_without_known_headers():
    combined = "İstanbul Milletvekili Çiçek Otlu'nun, ulaşım sorunlarına ilişkin Çevre Bakanı'ndan yazılı soru önergesi"
    sheet = Sheet('EBYS', [(1, ('Kayıt', 'İçerik')), (2, ('100', combined))])
    rows = records(sheet, 1, {'document': 0, 'member': 1, 'ministry': 1, 'case': None})
    assert compare(right=rows)['clean'] == 1


@pytest.mark.parametrize('mapping', [dict(document=None, member=1, ministry=2),
    dict(document=0, member=0, ministry=2), dict(document=7, member=1, ministry=2)])
def test_invalid_mapping_cannot_produce_success(mapping):
    sheet = read_sheets(workbook(), ['KKBS', 'EBYS'])[0]
    with pytest.raises(TableError):
        records(sheet, 2, mapping)


@pytest.mark.parametrize('names', [['KKBS', 'KKBS'], ['KKBS', 'missing']])
def test_invalid_sheet_pair_is_a_friendly_error(names):
    with pytest.raises(TableError):
        read_sheets(workbook(), names)


def test_csv_escapes_formula_fields_and_includes_control_rows():
    report = compare([record('=1+2', member='=BAD()')], [record('100')])
    csv = report_csv(report).decode('utf-8-sig')
    assert "'=1+2" in csv and 'Kontrol gerekli' in csv


def test_unrecognized_ministry_is_not_approved_even_when_both_values_match():
    report = compare([record(ministry='Bilinmeyen')], [record(ministry='Bilinmeyen')])
    assert report['uncertain'] == 1 and not report['complete']
