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
            cards = [x.value for x in at.markdown if '<table class="entry-review-table">' in x.value]
            assert len(cards) == 1  # Both mismatches belong to the same document.
            assert 'Milletvekili farklı' in cards[0] and 'Bakanlık farklı' in cards[0]
            assert 'KKBS: Çiçek Otlu' in cards[0] and 'EBYS: Cengiz Çiçek' in cards[0]
            assert cards[0].count('<details ') == 1
            assert 'Esas No' not in cards[0] and 'Excel satırı' not in cards[0] and 'Sonuç' not in cards[0]
            from copy import deepcopy
            saved = deepcopy(at.session_state['entry_result'])
            at.run()
            assert not at.exception and at.session_state['entry_result'] == saved
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


def test_writing_check_uses_only_kkbs_summary_and_moves_control_count_to_note(monkeypatch):
    from copy import deepcopy
    from test_entry_comparison import HEADERS
    headers = [*HEADERS[:4], 'Özet']
    data = workbook(headers=headers,
        left=[[100, 'Çiçek Otlu', 'Çevre Bakanı', '', "personelin  unvan değişikliğine ve Sayıştay Başkanlığı'na ilişkin"],
              [102, 'Çiçek Otlu', 'Çevre Bakanı', '', 'haklara  ilişkin']],
        right=[[100, 'Cengiz Çiçek', 'Adalet Bakanı', '', 'herkez yalnış']])
    at = setup(monkeypatch)
    with patch('streamlit.file_uploader', return_value=[Upload(data)]), \
         patch('app.analyze', side_effect=AssertionError('No API allowed')):
        at.run()
        assert next(s for s in at.selectbox if s.label == 'KKBS · Denetlenecek özet sütunu').value == 4
        click(at, 'Girişleri karşılaştır')
        assert not at.exception
        result = deepcopy(at.session_state['entry_result'])
        assert result['different'] == 1 and result['matched'] == 1 and result['unmatched_kkbs'] == 1
        suggestions = result['summary_review']['suggestions']
        assert len(suggestions) == 4 and {s['document'] for s in suggestions} == {'100', '102'}
        assert not any(s['before'] in ('herkez', 'yalnış') for s in suggestions)
        counters = [m.value for m in at.markdown if 'class="status-card' in m.value]
        assert 'Yazım önerisi' in counters[-1] and 'Kontrol bulgusu' not in ''.join(counters)
        assert any('Not: Kayıt karşılaştırmasında 1 kontrol bulgusu' in c.value for c in at.caption)
        assert not at.warning
        assert any('Olması gereken' in m.value and 'Olan' in m.value for m in at.markdown)
        at.run()
        assert at.session_state['entry_result'] == result  # Widget reruns preserve the report.
        next(s for s in at.selectbox if s.label == 'KKBS · Denetlenecek özet sütunu').set_value(-1).run()
        assert 'entry_result' not in at.session_state
        click(at, 'Girişleri karşılaştır')
        assert not at.session_state['entry_result']['summary_review']['available']
        assert at.session_state['entry_result']['different'] == 1


def test_misspelled_ending_and_kayyum_are_shown_and_old_report_is_invalidated(monkeypatch):
    from test_entry_sources import joined_workbook
    from openpyxl import load_workbook
    import io
    book = load_workbook(io.BytesIO(joined_workbook()))
    book['Sheet1']['C3'] = ("Ankara Milletvekili Ahmet Yılmaz'ın, belediyeye kayyum atanmasına ilişki "
                          "Çevre Bakanı'ndan yazılı soru önergesi")
    data = io.BytesIO(); book.save(data)
    at = setup(monkeypatch)
    with patch('streamlit.file_uploader', return_value=[Upload(data.getvalue())]), \
         patch('app.analyze', side_effect=AssertionError('No API allowed')):
        at.run(); click(at, 'Girişleri karşılaştır')
        assert not at.exception
        report = at.session_state['entry_result']
        assert report['summary_review']['checked_count'] == 2
        assert not report['summary_review']['skipped_documents']
        findings = report['summary_review']['suggestions']
        assert [(i['before'], i['after']) for i in findings] == [('kayyum', 'kayyım'), ('ilişki', 'ilişkin')]
        assert all(i['document'] == '90001' for i in findings)
        html = ''.join(m.value for m in at.markdown if 'entry-writing-table' in m.value)
        assert all(v in html for v in ('90001', 'kayyım', 'ilişkin'))
        assert any('Yazım önerisi' in m.value and '>2<' in m.value for m in at.markdown)
        with patch('entry_comparison_ui.WRITING_VERSION', 'new-rules'):
            at.run()
            assert not at.exception and 'entry_result' not in at.session_state
