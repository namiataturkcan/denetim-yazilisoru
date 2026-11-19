from unittest.mock import patch

import streamlit as st

from test_entry_comparison import workbook
from test_incoming_ui import click, login
from test_streamlit import configured


class Upload:
    name = 'rapor.xlsx'

    def __init__(self, data=None, name='rapor.xlsx'):
        self.data = data or workbook()
        self.name = name

    def getvalue(self):
        return self.data


def setup(monkeypatch):
    at = configured(monkeypatch, module="second_reader")
    for name in ('ONERGE_DIRECT_API_KEY', 'ONERGE_API_KEY', 'OPENAI_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    login(at)
    return at


def test_route_upload_compare_without_api_and_logout(monkeypatch):
    with patch('app.analyze', side_effect=AssertionError('No API allowed')):
        at = setup(monkeypatch)
        assert not at.exception and not at.error
        assert len(at.get('file_uploader')) == 1
        data = workbook(right=[[100, 'Cengiz Çiçek', 'Adalet Bakanı', '7/50000', None]])
        with patch('streamlit.file_uploader', return_value=[Upload(data)]):
            at.run()
            click(at, 'Girişleri karşılaştır')
            assert at.session_state['entry_result']['different'] == 1
            assert len(at.get('download_button')) == 2
            assert any('1 evrakta' in error.value for error in at.error)
            assert not any('Kontrol gerekli' in x.label for x in at.expander)
            click(at, 'Çıkış yap')
            assert 'entry_result' not in at.session_state and 'entry_sheets' not in at.session_state


def test_file_and_mapping_changes_invalidate_result(monkeypatch):
    at = setup(monkeypatch)
    with patch('streamlit.file_uploader', return_value=[Upload()]):
        at.run()
        click(at, 'Girişleri karşılaştır')
        assert at.success
        next(s for s in at.selectbox if s.label == 'EBYS · Bakanlık / muhatap').set_value(1).run()
        assert 'entry_result' not in at.session_state and not at.get('download_button')
    with patch('streamlit.file_uploader', return_value=[Upload(workbook(right=[[100, 'Cengiz Çiçek', 'Adalet Bakanı']]))]):
        at.run()
        assert 'entry_result' not in at.session_state
        click(at, 'Girişleri karşılaştır')
        assert at.session_state['entry_result']['different'] == 1
    with patch('streamlit.file_uploader', return_value=None):
        at.run()
        assert 'entry_result' not in at.session_state and 'entry_sheets' not in at.session_state


def test_sheet_change_clears_old_result_and_same_sheets_are_rejected(monkeypatch):
    at = setup(monkeypatch)
    with patch('streamlit.file_uploader', return_value=[Upload()]):
        at.run()
        click(at, 'Girişleri karşılaştır')
        next(s for s in at.selectbox if s.label == 'EBYS çalışma sayfası').set_value('KKBS').run()
        assert not at.exception and at.error
        assert 'entry_result' not in at.session_state


def test_interrupted_reader_and_missing_cached_data_are_retried(monkeypatch):
    from entry_comparison import read_sheets
    calls = []
    def interrupted(*args, **kwargs):
        if kwargs.get('preview'):
            return read_sheets(*args, **kwargs)
        calls.append(1)
        if len(calls) == 1:
            st.rerun()
        return read_sheets(*args, **kwargs)
    at = setup(monkeypatch)
    with patch('streamlit.file_uploader', return_value=[Upload()]), patch('entry_comparison_ui.read_sheets', side_effect=interrupted):
        at.run()
        assert not at.exception and len(calls) == 2
        click(at, 'Girişleri karşılaştır')
        del at.session_state['entry_sheets']
        at.run()
        assert not at.exception and len(calls) == 3
        assert 'entry_result' not in at.session_state


def test_no_common_id_is_not_green_and_control_list_is_collapsed(monkeypatch):
    at = setup(monkeypatch)
    with patch('streamlit.file_uploader', return_value=[Upload(workbook(right=[[999, 'Çiçek Otlu', 'Çevre Bakanı']]))]):
        at.run()
        click(at, 'Girişleri karşılaştır')
        assert not at.success
        assert any('birebir eşleşen kayıt bulunamadı' in e.value for e in at.error)
        expander = next(e for e in at.expander if e.label.startswith('Kontrol gerekli'))
        assert not expander.proto.expanded
