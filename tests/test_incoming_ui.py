from unittest.mock import patch

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


def test_home_routes_to_both_modules_and_returns(monkeypatch):
    at = login(configured(monkeypatch, module=None))
    assert not at.get('file_uploader')
    click(at, 'Gelen kağıt işlemlerine geç')
    assert 'Gelen Kağıt İşlemleri' in '\n'.join(m.value for m in at.markdown)
    assert at.get('file_uploader')[0].label == 'KKBS raporunu yükle (.xlsx)'
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
        at.radio[0].set_value('Tablo yapıştır').run()
        at.text_area[0].set_value(f'100\t{PENDING}\tAdalet Bakanı\n101\tCevaplandı\tİçişleri Bakanı').run()
        click(at, 'Listeyi oluştur')
        assert not at.error
        assert at.session_state['incoming_result']['selected_count'] == 1
        assert len(at.get('download_button')) == 3
        at.number_input[1].set_value(102).run()
        assert 'incoming_result' not in at.session_state
        assert not at.get('download_button')
        click(at, 'Listeyi oluştur')
        assert at.session_state['incoming_result']['absent_count'] == 1
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
        click(at, 'Listeyi oluştur')
        assert at.session_state['incoming_result']['ranges'] == ['5']
        data = workbook([['Esas No', 'Son Durum', 'Muhatap Unvanı'], [8, 'Cevaplandı', 'Adalet Bakanı']])
        at.run()
        assert not at.exception
        assert 'incoming_result' not in at.session_state
        assert at.number_input[0].value == 8
        click(at, 'Listeyi oluştur')
        assert at.session_state['incoming_result']['selected_count'] == 0


def test_mixed_terms_require_selection(monkeypatch):
    at = login(configured(monkeypatch, module='incoming'))
    at.radio[0].set_value('Tablo yapıştır').run()
    at.text_area[0].set_value('Esas No\tSon Durum\tMuhatap Unvanı\tDönem\n'
                            f'1\t{PENDING}\tAdalet Bakanı\t28\n'
                            '1\tCevaplandı\tAdalet Bakanı\t27').run()
    assert at.selectbox[0].value is None
    assert not any(b.label == 'Listeyi oluştur' for b in at.button)
    at.selectbox[0].set_value('28. Dönem').run()
    click(at, 'Listeyi oluştur')
    assert at.session_state['incoming_result']['selected_count'] == 1
