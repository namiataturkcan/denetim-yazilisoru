"""Separate raw registers and the combined report must yield the same findings."""
import io
from unittest.mock import patch

import pytest
import streamlit as st
from openpyxl import Workbook, load_workbook

from entry_comparison import records, read_sheets, suggest_header, suggest_mapping
from test_entry_comparison import compare, record
from test_entry_comparison_ui import Upload, setup
from test_incoming_ui import click, login
from test_streamlit import configured


def raw_files():
    sources = []
    for side in ('kkbs', 'ebys'):
        book = Workbook()
        sheet = book.active
        sheet.title = 'Sheet1'  # Same sheet name across files is valid.
        if side == 'kkbs':
            sheet.append(['KKBS - Kanunlar Kararlar Bilgi Sistemi'])
            sheet.append(['Paket Adı', 'Genel Evrak No', 'Önerge Sahibi Özeti', 'Açıklama'])
            for doc, owner, office in [(100, 'Cengiz Çiçek', 'Adalet'), (101, 'Çiçek Otlu', 'Çevre')]:
                sheet.append(['Paket', doc, f"Ankara Milletvekili {owner}'nun, bir konuya ilişkin {office} Bakanı'ndan yazılı soru önergesi", None])
        else:
            sheet.append(['Gelen Evrak Listesi'])
            sheet.append([])
            sheet.append(['Barkod No', 'Sahip Birim', 'Üretici', 'Havale Eden', 'Konu', 'Sayı'])
            for doc in (100, 101):
                sheet.append([doc, 'Birim', 'Üretici', 'Test', "Yazılı Soru Ankara Mv. Çiçek Otlu'nun Adalet Bakanından Yazılı Sorusu", f'FARKLI-{doc}'])
            sheet.append([102, 'Birim', 'Üretici', 'Test', 'Soru Önergesi', 'FARKLI-102'])
        output = io.BytesIO()
        book.save(output)
        sources.append(output.getvalue())
    return sources


def combine(files):
    book = Workbook()
    book.remove(book.active)
    for name, data in zip(('KKBS', 'EBYS'), files):
        source = load_workbook(io.BytesIO(data), data_only=True)
        target = book.create_sheet(name)
        for row in source.active.values:
            target.append(row)
        source.close()
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def test_barcode_has_priority_over_external_sayi_and_original_rows_preserved():
    s = read_sheets(raw_files()[1], ['Sheet1'])[0]
    h = suggest_header(s)
    m = suggest_mapping(s, h)
    assert h == 3 and m['document'] == 0 and m['member'] == m['ministry'] == 4
    result = records(s, h, m)
    assert [r['id'] for r in result] == ['100', '101', '102']
    assert [r['row'] for r in result] == [4, 5, 6]


@pytest.mark.parametrize('reversed_order', [False, True])
def test_raw_files_match_combined_result_and_file_order_is_detected(monkeypatch, reversed_order):
    data = raw_files()
    files = [Upload(d, name='rapor.xlsx') for d in data]
    if reversed_order:
        files.reverse()
    at = setup(monkeypatch)
    with patch('app.analyze', side_effect=AssertionError('No API allowed')), patch('streamlit.file_uploader', return_value=files):
        at.run()
        assert not at.exception
        assert next(s for s in at.selectbox if s.label == 'KKBS dosyası').value == int(reversed_order)
        assert any(h.value == 'Okuma Öncesi Kontrolü' for h in at.subheader)
        click(at, 'Girişleri karşılaştır')
        before = at.session_state['entry_result']
        assert before['matched'] == 2 and before['different'] == 2 and before['unmatched_ebys'] == 1
        assert before['source']['workflow'] == 'before' and before['api_requests'] == 0
        assert before['source']['kkbs']['document_sha256'] != before['source']['ebys']['document_sha256']
        assert {i['field'] for i in before['issues'] if i['status'] == 'uyari'} == {'member', 'ministry'}
    with patch('streamlit.file_uploader', return_value=[Upload(combine(data))]):
        at.run()
        assert 'entry_result' not in at.session_state
        assert any(h.value == 'Okuma Sonrası Kontrolü' for h in at.subheader)
        click(at, 'Girişleri karşılaştır')
        after = at.session_state['entry_result']
        assert {k:v for k,v in before.items() if k != 'source'} == {k:v for k,v in after.items() if k != 'source'}
        assert after['source']['workflow'] == 'after'


def test_one_raw_file_waits_for_second_then_removal_clears_result(monkeypatch):
    data = raw_files()
    files = [Upload(d, name=n) for d,n in zip(data, ['kkbs.xlsx', 'ebys.xlsx'])]
    at = setup(monkeypatch)
    with patch('streamlit.file_uploader', return_value=files[:1]):
        at.run()
        assert not at.exception and not at.error
        assert any('diğer Excel dosyasını' in i.value for i in at.info)
        assert not any(b.label == 'Girişleri karşılaştır' for b in at.button)
    with patch('streamlit.file_uploader', return_value=files):
        at.run()
        click(at, 'Girişleri karşılaştır')
        assert at.session_state['entry_result']['matched'] == 2
    with patch('streamlit.file_uploader', return_value=files[:1]):
        at.run()
        assert 'entry_result' not in at.session_state and not at.get('download_button')


def test_changed_second_file_cannot_reuse_previous_report(monkeypatch):
    first, second = raw_files()
    at = setup(monkeypatch)
    with patch('streamlit.file_uploader', return_value=[Upload(first), Upload(second)]):
        at.run()
        click(at, 'Girişleri karşılaştır')
    book = load_workbook(io.BytesIO(second))
    book.active['A4'] = 999
    output = io.BytesIO(); book.save(output)
    with patch('streamlit.file_uploader', return_value=[Upload(first), Upload(output.getvalue())]):
        at.run()
        assert 'entry_result' not in at.session_state and not at.get('download_button')
        click(at, 'Girişleri karşılaştır')
        assert at.session_state['entry_result']['matched'] == 1


@pytest.mark.parametrize('kind', ['same_content', 'three', 'corrupt'])
def test_invalid_file_combinations_do_not_keep_results(monkeypatch, kind):
    data = raw_files()
    files = ([Upload(data[0]), Upload(data[0])] if kind == 'same_content' else
             [Upload(data[0]), Upload(data[1]), Upload(data[0])] if kind == 'three' else
             [Upload(data[0]), Upload(b'invalid')])
    at = setup(monkeypatch)
    with patch('streamlit.file_uploader', return_value=files):
        at.session_state['entry_result'] = {'old': True}
        at.run()
        assert not at.exception and at.error
        assert 'entry_result' not in at.session_state


def test_same_file_role_selection_is_rejected(monkeypatch):
    at = setup(monkeypatch)
    with patch('streamlit.file_uploader', return_value=[Upload(d) for d in raw_files()]):
        at.run()
        click(at, 'Girişleri karşılaştır')
        next(s for s in at.selectbox if s.label == 'EBYS dosyası').set_value(0).run()
        assert not at.exception and any('iki farklı dosya' in e.value for e in at.error)
        assert 'entry_result' not in at.session_state


def test_second_file_read_interruption_recovers(monkeypatch):
    calls = []
    def interrupted(*args, **kwargs):
        if not kwargs.get('preview'):
            calls.append(1)
            if len(calls) == 2:
                st.rerun()
        return read_sheets(*args, **kwargs)
    at = setup(monkeypatch)
    with patch('streamlit.file_uploader', return_value=[Upload(d) for d in raw_files()]), \
         patch('entry_comparison_ui.read_sheets', side_effect=interrupted):
        at.run()
        assert not at.exception and len(calls) == 4
        click(at, 'Girişleri karşılaştır')
        assert at.session_state['entry_result']['matched'] == 2


def test_main_menu_route_old_session_migration_and_logout(monkeypatch):
    at = login(configured(monkeypatch, module=None))
    click(at, 'İkinci okuyucu işlemlerine geç')
    assert 'İkinci Okuyucu İşlemleri' in '\n'.join(x.value for x in at.markdown)
    assert len(at.get('file_uploader')) == 1 and not at.radio
    click(at, '← İşlem seçimine dön')
    click(at, 'Önerge incelemesine geç')
    assert at.radio[0].options == ['Tekli inceleme', 'Toplu inceleme']
    # Model persisted state before the new widget tree is constructed.
    at = configured(monkeypatch, module='review')
    at.session_state['review_mode'] = 'EBYS–KKBS karşılaştırması'
    login(at)
    assert not at.exception and at.session_state['active_module'] == 'second_reader'
    with patch('streamlit.file_uploader', return_value=[Upload(d) for d in raw_files()]):
        at.run()
        click(at, 'Girişleri karşılaştır')
        click(at, 'Çıkış yap')
        assert 'entry_result' not in at.session_state and 'entry_sheets' not in at.session_state


@pytest.mark.parametrize('full,short', [('Sevda Karaca Demir', 'Sevda Karaca'),
    ('Perihan Koca Doğan', 'Perihan Koca'), ('Keziban Konukcu Kok', 'Kezban Konukçu')])
def test_omitted_last_name_component_is_only_accepted_for_unique_person(full, short):
    assert compare([record(member=full)], [record(member=short)])['spelling'] == 1
    # A different known person with the short name is never merged.
    assert compare([record(member=full)], [record(member=short)], names=[short])['different'] == 1


def test_partial_name_ambiguity_stays_in_control_list():
    report = compare([record(member='Selin Aksoy Demir')], [record(member='Selin Aksoy')], names=['Selin Aksoy Kaya'])
    assert report['uncertain'] == 1
    assert compare([record(member='Çiçek Otlu')], [record(member='Cengiz Çiçek')])['different'] == 1
