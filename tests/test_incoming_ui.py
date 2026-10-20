from unittest.mock import patch

import pytest
import streamlit as st

from incoming_papers import read_excel, read_paste
from test_streamlit import configured
from test_incoming_papers import PENDING, workbook


def login(at):
    at.run()
    at.text_input[0].set_value('test-password-only')
    at.button[0].click().run()
    return at


def click(at, label):
    next(button for button in at.button if button.label == label).click().run()
    assert not at.exception


def enter_range(at, first, last):
    at.number_input[0].set_value(first)
    at.number_input[1].set_value(last).run()
    assert not at.exception


@pytest.mark.parametrize('mode', ['Excel yükle', 'Tablo yapıştır'])
def test_interrupted_read_retries_instead_of_trusting_incomplete_session(mode, monkeypatch):
    data = workbook([['Esas No', 'Son Durum', 'Muhatap Unvanı'], [5, PENDING, 'Adalet Bakanı']])

    class Upload:
        name = 'test.xlsx'
        def getvalue(self): return data

    original = read_excel if mode == 'Excel yükle' else read_paste
    calls = []

    def interrupted_once(*args):
        calls.append(args)
        if len(calls) == 1:
            # A widget interaction can interrupt the script while a file is loading.
            st.rerun()
        return original(*args)

    at = login(configured(monkeypatch, module='incoming'))
    enter_range(at, 5, 5)
    if mode == 'Tablo yapıştır':
        at.radio[0].set_value(mode).run()
    loader_name = 'read_excel' if mode == 'Excel yükle' else 'read_paste'
    with patch('streamlit.file_uploader', return_value=Upload()), \
         patch('incoming_ui.' + loader_name, side_effect=interrupted_once):
        if mode == 'Excel yükle':
            at.run()
        else:
            at.text_area[0].set_value(f'5\t{PENDING}\tAdalet Bakanı').run()
        assert not at.exception
        assert len(calls) == 2
        click(at, 'Listeyi oluştur')
        assert at.session_state['incoming_result']['present_recipients'] == ['Adalet Bakanlığı']
        # Recover sessions left incomplete by an older deployed version too.
        del at.session_state['incoming_records']
        at.run()
        assert not at.exception
        assert len(calls) == 3
        assert 'incoming_result' not in at.session_state
        click(at, 'Listeyi oluştur')
        assert at.session_state['incoming_result']['selected_count'] == 1


def test_home_routes_to_both_modules_and_returns(monkeypatch):
    at = login(configured(monkeypatch, module=None))
    assert not at.get('file_uploader')
    click(at, 'Gelen kağıt işlemlerine geç')
    assert 'Gelen Kağıt İşlemleri' in '\n'.join(m.value for m in at.markdown)
    assert at.get('file_uploader')[0].label == 'KKBS raporunu yükle (.xlsx)'
    assert [field.value for field in at.number_input] == [None, None]
    assert not at.selectbox
    click(at, '← İşlem seçimine dön')
    click(at, 'Önerge incelemesine geç')
    assert 'Yazılı Soru Önergesi İncelemesi' in '\n'.join(m.value for m in at.markdown)
    assert at.get('file_uploader')[0].label == 'Önerge PDF’sini yükle'


def test_paste_flow_needs_no_api_key_and_expires_changed_range(monkeypatch):
    at = configured(monkeypatch, module='incoming')
    for name in ('ONERGE_DIRECT_API_KEY', 'ONERGE_API_KEY', 'OPENAI_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    with patch('app.analyze', side_effect=AssertionError('No API call allowed')):
        login(at)
        enter_range(at, 100, 101)
        at.radio[0].set_value('Tablo yapıştır').run()
        at.text_area[0].set_value(f'100\t{PENDING}\tAdalet Bakanı\n101\tCevaplandı\tİçişleri Bakanı').run()
        click(at, 'Listeyi oluştur')
        assert not at.error
        assert at.session_state['incoming_result']['selected_count'] == 1
        assert at.session_state['incoming_result']['ranges_text'] == '100'
        assert any(code.value == '100' for code in at.code)
        assert len(at.get('download_button')) == 3
        at.number_input[1].set_value(102).run()
        assert 'incoming_result' not in at.session_state
        assert not at.get('download_button')
        click(at, 'Listeyi oluştur')
        assert at.session_state['incoming_result']['absent_count'] == 1
        at.number_input[1].set_value(None).run()
        assert 'incoming_result' not in at.session_state
        assert not at.get('download_button')
        assert next(b for b in at.button if b.label == 'Listeyi oluştur').disabled
        enter_range(at, 103, 102)
        assert next(b for b in at.button if b.label == 'Listeyi oluştur').disabled
        assert 'büyük olamaz' in at.error[0].value
        click(at, 'Çıkış yap')
        assert 'incoming_result' not in at.session_state
        assert 'incoming_records' not in at.session_state


def test_excel_upload_and_source_change_clear_old_results(monkeypatch):
    data = workbook([['Esas No', 'Son Durum', 'Muhatap Unvanı'], [5, PENDING, 'Adalet Bakanı']])
    class Upload:
        name = 'test.xlsx'
        def getvalue(self): return data
    at = configured(monkeypatch, module='incoming')
    with patch('streamlit.file_uploader', return_value=Upload()):
        login(at)
        assert [field.value for field in at.number_input] == [None, None]
        assert next(b for b in at.button if b.label == 'Listeyi oluştur').disabled
        enter_range(at, 5, 8)
        click(at, 'Listeyi oluştur')
        assert at.session_state['incoming_result']['ranges'] == ['5']
        data = workbook([['Esas No', 'Son Durum', 'Muhatap Unvanı'], [8, 'Cevaplandı', 'Adalet Bakanı']])
        at.run()
        assert not at.exception
        assert 'incoming_result' not in at.session_state
        assert [field.value for field in at.number_input] == [5, 8]
        click(at, 'Listeyi oluştur')
        assert at.session_state['incoming_result']['selected_count'] == 0
        assert at.session_state['incoming_result']['ranges_text'] == ''


def test_terms_need_no_user_selection_and_ambiguous_records_are_not_merged(monkeypatch):
    at = login(configured(monkeypatch, module='incoming'))
    enter_range(at, 1, 1)
    at.radio[0].set_value('Tablo yapıştır').run()
    at.text_area[0].set_value('Esas No\tSon Durum\tMuhatap Unvanı\tDönem\n'
                            f'1\t{PENDING}\tAdalet Bakanı\t28\n'
                            '1\tCevaplandı\tAdalet Bakanı\t27').run()
    assert not at.selectbox
    click(at, 'Listeyi oluştur')
    assert 'ayrı bir tablo' in at.error[0].value
    assert 'incoming_result' not in at.session_state
    at.text_area[0].set_value('Esas No\tSon Durum\tMuhatap Unvanı\tDönem\n'
                            f'1\t{PENDING}\tAdalet Bakanı\t28').run()
    assert not at.selectbox
    assert [field.value for field in at.number_input] == [1, 1]
    click(at, 'Listeyi oluştur')
    assert at.session_state['incoming_result']['selected_count'] == 1
    assert at.session_state['incoming_result']['term'] == '28. Dönem'


def test_result_shows_single_line_and_found_ministries_without_mp_names(monkeypatch):
    at = login(configured(monkeypatch, module='incoming'))
    enter_range(at, 45424, 45530)
    at.radio[0].set_value('Tablo yapıştır').run()
    answered = {45494, 45513, 45524, 45526}
    text = 'Esas No\tSon Durum\tMuhatap Unvanı\tSoru Sahibi\n' + '\n'.join(
        f'{n}\t{"Cevaplandı" if n in answered else PENDING}\tAdalet Bakanı\tTest Milletvekili'
        for n in range(45424, 45531))
    at.text_area[0].set_value(text).run()
    click(at, 'Listeyi oluştur')
    expected = '45424–45493;45495–45512;45514–45523;45525;45527–45530'
    assert at.session_state['incoming_result']['ranges_text'] == expected
    assert expected in [code.value for code in at.code]
    found = next(m.value for m in at.markdown if 'incoming-recipients found' in m.value)
    missing = next(m.value for m in at.markdown if 'incoming-recipients missing' in m.value)
    assert '<li>Adalet Bakanlığı</li>' in found
    assert 'recipient-count">1</div>' in found
    assert '<li>Adalet Bakanlığı</li>' not in missing
    assert 'Bulunmayanlar · 17' in missing
    assert not any('Test Milletvekili' in m.value for m in at.markdown)
