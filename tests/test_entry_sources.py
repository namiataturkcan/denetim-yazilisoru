"""Regression for a headerless EBYS source beside a copied KKBS summary.

The workbook is synthetic; uploaded registers are not committed as fixtures.
"""
import io
from unittest.mock import patch

import pytest
import streamlit as st
from openpyxl import Workbook

from app import RULES
from entry_comparison import (Sheet, compare_records, ministry_identity, read_sheets,
    records, suggest_header, suggest_mapping, suggest_sheet_pair, validate_ebys_source)
from incoming_papers import TableError, sheet_names
from test_entry_comparison import compare, record
from test_entry_comparison_ui import Upload, setup
from test_incoming_ui import click


def joined_workbook():
    book = Workbook()
    kkbs = book.active
    kkbs.title = 'Sheet1'
    helper = book.create_sheet('Sayfa2')
    ebys = book.create_sheet('Sayfa1')
    kkbs.append(['KKBS'])
    kkbs.append(['Paket Adı', 'Genel Evrak No', 'Önerge Sahibi Özeti', 'Açıklama', 'Kullanıcı'])
    for number, title in [(90001, 'Çevre'), (90002, 'Çalışma ve Sosyal Güvenlik')]:
        summary = f"Ankara Milletvekili Ahmet Yılmaz'ın, konut sorunlarına ilişkin {title} Bakanı'ndan yazılı soru önergesi"
        kkbs.append(['Paket', number, summary, None, 'Test'])
        helper.append([f'7/{number}', number])
        original = "Yazılı Soru Ankara Mv. Ahmet Yılmaz'ın Çevre Bakanı'na Yazılı Sorusu"
        ebys.append([original, number, 0, number, summary])
    ebys.append([None]*5)
    ebys.append(["Yazılı Soru Ankara Mv Ahmet Yılmaz'ın Adalet Bakanından Yazılı Sorusu", 90003, 0, 90003])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def test_detects_original_subject_skips_helper_and_preserves_first_record():
    data = joined_workbook()
    pair = suggest_sheet_pair(read_sheets(data, sheet_names(data), preview=True))
    assert pair == ('Sheet1', 'Sayfa1')
    kkbs, ebys = read_sheets(data, pair)
    assert suggest_header(kkbs) == 2 and suggest_header(ebys) == 0
    km, em = suggest_mapping(kkbs, 2), suggest_mapping(ebys, 0)
    assert em == dict(document=1, member=0, ministry=0, case=None)
    validate_ebys_source(ebys, 0, em)
    right = records(ebys, 0, em)
    assert [r['row'] for r in right] == [1, 2, 4]
    report = compare_records(records(kkbs, 2, km), right, RULES['recipients'])
    assert report['matched'] == 2 and report['different'] == 1 and report['clean'] == 1
    assert report['unmatched_kkbs'] == 0 and report['unmatched_ebys'] == 1
    red = [i for i in report['issues'] if i['status'] == 'uyari']
    assert len(red) == 1 and red[0]['document'] == '90002' and red[0]['field'] == 'ministry'
    assert red[0]['kkbs_row'] == 4 and red[0]['ebys_row'] == 2


def test_copied_summary_and_skipping_first_ebys_record_are_rejected():
    sheet = read_sheets(joined_workbook(), ['Sheet1', 'Sayfa1'])[1]
    mapping = suggest_mapping(sheet, 0)
    with pytest.raises(TableError, match='A sütununda'):
        validate_ebys_source(sheet, 0, dict(mapping, ministry=4))
    with pytest.raises(TableError, match='gerçek kayıtları atlıyor'):
        validate_ebys_source(sheet, 1, mapping)


def test_explicit_separate_ebys_fields_are_allowed():
    s = Sheet('EBYS', [(1, ('Konu', 'Evrak No', 'Milletvekili', 'Bakanlık')),
                      (2, ("Yazılı Soru Ankara Mv Ahmet Yılmaz'ın Adalet Bakanından Yazılı Sorusu",
                           123, 'Ahmet Yılmaz', 'Adalet Bakanı'))])
    validate_ebys_source(s, 1, suggest_mapping(s, 1))


def test_conflicting_document_id_columns_require_selection():
    s = read_sheets(joined_workbook(), ['Sheet1', 'Sayfa1'])[1]
    s.rows = [(n, (*v[:3], 123456, *v[4:])) for n, v in s.rows]
    assert suggest_mapping(s, 0)['document'] is None


@pytest.mark.parametrize('role', ['Mv.', 'Mv', 'MV', 'Milletvekili'])
def test_incoming_register_owner_abbreviations_and_titles(role):
    incoming = f"Yazılı Soru Ankara {role} Grup Başkanvekili Ahmet Yılmaz'ın Çevre Bakanı'na Yazılı Sorusu"
    assert compare([record(member='Ahmet Yılmaz')], [record(member=incoming)])['clean'] == 1


def test_unique_initial_is_a_variant_but_ambiguous_initial_is_not_accepted():
    left = [record(member='Mustafa Sezgin Tanrıkulu')]
    right = [record(member="Yazılı Soru Diyarbakır Mv. M. Sezgin Tanrıkulu'nun Adalet Bakanından Yazılı Sorusu")]
    assert compare(left, right)['spelling'] == 1
    ambiguous = compare(left, right, names=['Mehmet Sezgin Tanrıkulu'])
    assert ambiguous['uncertain'] == 1 and not ambiguous['complete']
    wrong = compare(left, [record(member='A. Sezgin Tanrıkulu')], names=['Ahmet Sezgin Tanrıkulu'])
    assert wrong['different'] == 1


def test_short_surname_and_no_initial_reference_are_not_approved():
    assert compare(right=[record(member='Çiçek O.')])['uncertain'] == 1
    assert compare([record(member='M. Sezgin Tanrıkulu')], [record(member='M. Sezgin Tanrıkulu')])['uncertain'] == 1


def test_small_syllable_typo_needs_unique_reference_and_distinct_people_stay_red():
    left, right = [record(member='Semih Işıkver')], [record(member='Semih Işıksever')]
    assert compare(left, right)['spelling'] == 1
    assert compare(left, right, names=['Semih Işıksever'])['different'] == 1
    assert compare(left, right, names=['Semih Işıkseven'])['uncertain'] == 1
    assert compare([record(member='Çiçek Otlu')], [record(member='Cengiz Çiçek')])['different'] == 1


@pytest.mark.parametrize('target,expected', [('Sağlık', 'Sağlık Bakanlığı'),
    ('Çalışma Ve Sosyal Güvenlik', 'Çalışma ve Sosyal Güvenlik Bakanlığı'), ('Bilinmeyen', None)])
def test_subject_mention_cannot_replace_requested_addressee(target, expected):
    summary = f"Ankara Milletvekili Ahmet Yılmaz'ın, Aile ve Sosyal Hizmetler Bakanı'nın bir açıklamasına ilişkin {target} Bakanı'ndan yazılı soru önergesi"
    assert ministry_identity(summary, RULES['recipients'])[0] == expected


def test_ui_selects_independent_sources_and_prevents_unsafe_manual_override(monkeypatch):
    at = setup(monkeypatch)
    with patch('streamlit.file_uploader', return_value=Upload(joined_workbook())), \
         patch('app.analyze', side_effect=AssertionError('No API allowed')):
        at.session_state['entry_result'] = {'old': 'report'}
        at.session_state['entry_result_key'] = 'old-version'
        at.run()
        assert not at.exception
        assert next(s for s in at.selectbox if s.label == 'EBYS çalışma sayfası').value == 'Sayfa1'
        assert next(n for n in at.number_input if n.label == 'EBYS başlık satırı').value == 0
        assert 'entry_result' not in at.session_state
        click(at, 'Girişleri karşılaştır')
        result = at.session_state['entry_result']
        assert result['different'] == 1 and result['matched'] == 2 and result['api_requests'] == 0
        assert result['source']['ebys']['columns']['ministry'] == 0
        next(s for s in at.selectbox if s.label == 'EBYS · Bakanlık / muhatap').set_value(4).run()
        assert not at.exception and any('A sütununda' in e.value for e in at.error)
        assert 'entry_result' not in at.session_state and not at.get('download_button')


def test_interrupted_sheet_detection_is_retried(monkeypatch):
    calls = []
    def interrupted(*args, **kwargs):
        if kwargs.get('preview'):
            calls.append(1)
            if len(calls) == 1:
                st.rerun()
        return read_sheets(*args, **kwargs)
    at = setup(monkeypatch)
    with patch('streamlit.file_uploader', return_value=Upload(joined_workbook())), \
         patch('entry_comparison_ui.read_sheets', side_effect=interrupted):
        at.run()
        assert not at.exception and len(calls) == 2
        click(at, 'Girişleri karşılaştır')
        assert at.session_state['entry_result']['different'] == 1
