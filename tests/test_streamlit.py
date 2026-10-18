from unittest.mock import patch

import pymupdf
from streamlit.testing.v1 import AppTest


def configured(monkeypatch):
    monkeypatch.setenv('APP_PASSWORD', 'test-password-only')
    monkeypatch.setenv('ONERGE_DIRECT_API_KEY', 'test-api-only')
    return AppTest.from_file('../streamlit_app.py', default_timeout=15)


def test_password_required(monkeypatch):
    monkeypatch.delenv('APP_PASSWORD', raising=False)
    at = AppTest.from_file('../streamlit_app.py').run()
    assert not at.exception
    assert 'parolası' in at.error[0].value
    assert not at.get('file_uploader')


def test_login_logout_and_rotation(monkeypatch):
    at = configured(monkeypatch).run()
    at.text_input[0].set_value('wrong')
    at.button[0].click().run()
    assert at.error[0].value == 'Parola doğru değil.'
    assert not at.get('file_uploader')
    at.text_input[0].set_value('test-password-only')
    at.button[0].click().run()
    assert not at.exception
    assert len(at.get('file_uploader')) == 1
    next(b for b in at.button if b.label == 'Çıkış yap').click().run()
    assert not at.get('file_uploader')
    at.text_input[0].set_value('test-password-only')
    at.button[0].click().run()
    monkeypatch.setenv('APP_PASSWORD', 'rotated-password')
    at.run()
    assert not at.get('file_uploader')


def test_upload_analysis_and_clear(monkeypatch):
    from test_app import report
    at = configured(monkeypatch)
    with pymupdf.open() as d:
        d.new_page().insert_text((72, 72), 'Reference text 10')
        data = d.tobytes()
    class Upload:
        def getvalue(self):
            return data
    async def mock_analyze(pages, *, credential, model):
        assert credential == 'test-api-only'
        assert len(pages) == 1
        result = report()
        result.pages[0].text = 'Reference text 10'
        for c in result.checks:
            c.quote = 'Reference text 10'
        result.checks[0].status = 'uyari'
        return result
    with patch('streamlit.file_uploader', return_value=Upload()), patch('app.analyze', mock_analyze):
        at.run()
        at.text_input[0].set_value('test-password-only')
        at.button[0].click().run()
        next(b for b in at.button if b.label == 'İncelemeyi başlat').click().run()
        assert not at.exception
        assert at.session_state['result']['review']['summary'].endswith('ilişkin')
        assert len(at.get('download_button')) == 2
        assert len(at.session_state['markings']['locations']) == 1
        rendered = '\n'.join(m.value for m in at.markdown)
        assert 'check-card uyari' in rendered
        assert 'check-card uygun' in rendered
        assert '<mark class="issue-text">Reference text 10</mark>' in rendered
    with patch('streamlit.file_uploader', return_value=None):
        at.run()
        assert 'result' not in at.session_state
        assert 'pages' not in at.session_state
        assert 'markings' not in at.session_state
