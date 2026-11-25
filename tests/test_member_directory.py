from copy import deepcopy
from dataclasses import replace

import pytest
from openpyxl import Workbook

import app
import bulk_review as bulk
from entry_comparison import compare_records, member_province, records, Sheet, suggest_columns
from scripts.import_member_directory import build
from test_bulk_review import reading, record as bulk_record
from test_constituency import evaluate
from test_entry_comparison import record


def compare(left, right):
    return compare_records([left], [right], app.RULES['recipients'], member_reference=app.MEMBER_REFERENCE)


def owner(name, province):
    return f'{province} Milletvekili {name}’nin, ulaşım sorunlarına ilişkin Adalet Bakanı’ndan yazılı soru önergesi'


@pytest.mark.parametrize('province', ['İstanbul', 'Kilis'])
def test_namesake_pairs_are_both_valid_in_scan(province):
    assert evaluate('Mustafa DEMİR', province)[0]['status'] == 'uygun'


def test_namesake_wrong_province_is_not_approved_or_arbitrarily_resolved():
    check, _ = evaluate('Mustafa DEMİR', 'Ankara')
    assert check['status'] == 'uyari'
    assert 'İstanbul' in check['explanation'] and 'Kilis' in check['explanation']


def test_new_member_uses_directory_and_not_the_previous_partial_report():
    assert evaluate('Gökhan DİKTAŞ', 'Tekirdağ')[0]['status'] == 'uygun'
    assert evaluate('Gökhan DİKTAŞ', 'İstanbul')[0]['status'] == 'uyari'


def test_bulk_does_not_trust_same_wrong_province_in_pdf_and_kkbs():
    review, pages = reading()
    review = bulk.BulkReading.model_validate_json(review.model_dump_json().replace('Kocaeli', 'İstanbul'))
    pages[0]['ocr'] = review.pages[0].text
    result = bulk.compare_proposal(review, pages, [12], [replace(bulk_record(), province='İstanbul')])
    issue = next(i for i in result['issues'] if i['field'] == 'Şekil · Seçim çevresi')
    assert issue['status'] == 'uyari' and issue['pages'] == [12] and 'Kocaeli' in issue['explanation']
    assert not any(i['field'] == 'KKBS · Seçim çevresi' for i in result['issues'])


def test_bulk_uses_directory_when_uploaded_group_has_no_province():
    review, pages = reading()
    result = bulk.compare_proposal(review, pages, [12], [replace(bulk_record(), province='')])
    assert not any(i['field'] == 'Şekil · Seçim çevresi' for i in result['issues'])
    assert any(i['field'] == 'KKBS · Seçim çevresi' for i in result['issues'])


@pytest.mark.parametrize('value,expected', [
    (owner('Mahmut TANAL', 'Şanlıurfa'), 'Şanlıurfa'),
    ('Yazılı Soru Şanlıurfa Mv. Mahmut Tanal’ın Adalet Bakanı’na Yazılı Sorusu', 'Şanlıurfa'),
    ('Yazılı Soru Önergesi Şanlıurfa Mv. Mahmut Tanal’ın Adalet Bakanı’na Yazılı Sorusu', 'Şanlıurfa'),
    ('Mahmut TANAL (Şanlıurfa Milletvekili)', 'Şanlıurfa'),
    ('Mahmut TANAL', ''),
    ('Konu İstanbul Milletvekili Mahmut Tanal ve Ankara hakkında uzun açıklama', ''),
])
def test_only_explicit_owner_province_is_extracted(value, expected):
    assert member_province(value) == expected


@pytest.mark.parametrize('province', ['İstanbul', 'Dersim', 'Olmayanşehir'])
def test_second_reader_detects_wrong_province_even_when_both_sources_agree(province):
    row = record(member=owner('Ayten KORDU', province))
    report = compare(row, deepcopy(row))
    assert report['different'] == 1
    assert report['issues'][0]['field'] == 'province' and 'Tunceli' in report['issues'][0]['explanation']
    assert report['member_reference_source'] == app.MEMBER_REFERENCE['source']
    assert report['api_requests'] == 0


def test_second_reader_does_not_merge_namesakes_from_two_valid_provinces():
    report = compare(record(member=owner('Mustafa DEMİR', 'İstanbul')),
                     record(member=owner('Mustafa DEMİR', 'Kilis')))
    assert report['different'] == 1
    assert report['issues'][0]['field'] == 'province'


def test_namesake_without_province_is_not_assumed_same_person():
    report = compare(record(member='Mustafa DEMİR'), record(member='Mustafa DEMİR'))
    assert report['uncertain'] == 1 and not report['clean']
    typo = compare(record(member='Mustafa DEMİR'), record(member='Mustafa Demirr'))
    assert typo['uncertain'] == 1 and not typo['spelling']


def test_no_province_required_for_unique_name_and_ebys_typo_still_tolerated():
    report = compare(record(member='Gökhan DİKTAŞ'), record(member='Gökhan Dikttaş'))
    assert report['spelling'] == 1 and not report['issues']


def test_unknown_same_name_is_not_approved_by_agreement_alone():
    report = compare(record(member='Kaynakta Olmayan İsim'), record(member='Kaynakta Olmayan İsim'))
    assert report['uncertain'] == 1 and not report['clean']
    assert report['issues'][0]['field'] == 'member_reference'


@pytest.mark.parametrize('left,right', [
    ('Hasan ÖZTÜRK', 'Hasan ÖZTÜRKMEN'),
    ('Hasan ÖZTÜRKMEN', 'Hasan ÖZTÜRK'),
    ('Cengiz ÇİÇEK', 'Çiçek OTLU'),
    ('Çiçek OTLU', 'Cengiz ÇİÇEK'),
])
def test_search_suggestion_selection_errors_are_red_not_typographic(left, right):
    result = compare(record(member=left), record(member=right))
    assert result['different'] == 1 and not result['spelling']
    assert any(i['field'] == 'member' and i['status'] == 'uyari' for i in result['issues'])


@pytest.mark.parametrize('full', ['Hasan ÖZTÜRK', 'Hasan ÖZTÜRKMEN'])
def test_incomplete_search_name_cannot_choose_between_known_members(full):
    result = compare(record(member=full), record(member='Hasan Öztür'))
    assert result['uncertain'] == 1 and not result['clean'] and not result['spelling']
    assert any('birden fazla' in i['explanation'] for i in result['issues'])


def test_same_name_province_disagreement_remains_red_with_typo_in_ebys_name():
    result = compare(record(member=owner('Mustafa DEMİR', 'Kilis')),
                     record(member=owner('Mustafa Demirr', 'İstanbul')))
    assert result['different'] == 1 and not result['spelling']
    assert any(i['field'] == 'province' and i['status'] == 'uyari' for i in result['issues'])


@pytest.mark.parametrize('name,wrong', [
    ('Hasan ÖZTÜRK', 'Hasan ÖZTÜRKMEN'),
    ('Cengiz ÇİÇEK', 'Çiçek OTLU'),
    ('Mustafa DEMİR', 'Mustafa DEMİR'),
])
def test_bulk_scans_keep_similar_members_distinct(name, wrong):
    review, pages = reading()
    province = 'Bursa' if name == 'Hasan ÖZTÜRK' else 'İstanbul'
    review = bulk.BulkReading.model_validate_json(review.model_dump_json()
        .replace('Ömer Faruk GERGERLİOĞLU', name).replace('Kocaeli', province))
    pages[0]['ocr'] = review.pages[0].text
    expected_province = {'Hasan ÖZTÜRKMEN': 'Gaziantep', 'Çiçek OTLU': 'İstanbul', 'Mustafa DEMİR': 'Kilis'}[wrong]
    result = bulk.compare_proposal(review, pages, [12], [replace(bulk_record(), member=wrong, province=expected_province)])
    field = 'KKBS · Seçim çevresi' if name == wrong else 'KKBS · Milletvekili'
    assert any(i['field'] == field and i['status'] == 'uyari' for i in result['issues'])


def test_explicit_province_column_and_case_ascii_normalization():
    headers = ('Evrak No', 'Milletvekili', 'Bakanlık', 'Seçim Çevresi')
    sheet = Sheet('KKBS', [(1, headers), (2, ('100', 'Cicek Otlu', 'Adalet Bakanı', 'Ankara'))])
    row = records(sheet, 1, suggest_columns(headers))[0]
    report = compare(row, row)
    assert report['different'] == 1 and report['issues'][0]['kkbs'] == 'Ankara'
    row['province'] = 'ISTANBUL'
    assert compare(row, row)['clean'] == 1


def test_directory_import_retains_namesakes_departed_members_and_source(tmp_path):
    book = Workbook(); sheet = book.active
    sheet.append(['KKBS'])
    sheet.append(['Adı', 'Soyadı', 'Seçim Çevresi', 'Dönem', 'Ayrılış Tarihi'])
    sheet.append(['Mustafa', 'DEMİR', 'İstanbul', '28.DÖNEM', None])
    sheet.append(['Mustafa', 'DEMİR', 'Kilis', '28.DÖNEM', None])
    sheet.append(['Ahmet', 'ÖNAL', 'Kırıkkale', '28.DÖNEM', '04-04-2024'])
    path = tmp_path / 'liste.xlsx'; book.save(path)
    result = build(path)
    assert result['members'] == {'Ahmet ÖNAL': 'Kırıkkale'}
    assert result['namesakes'] == {'Mustafa DEMİR': ['Kilis', 'İstanbul']}
    assert result['source']['row_count'] == result['source']['member_count'] == 3
    assert result['source']['header_row'] == 2
    sheet.append(['Başka', 'VEKİL', 'Ankara', '27.DÖNEM', None]); book.save(path)
    with pytest.raises(ValueError, match='dönemi'):
        build(path)
