from unittest.mock import patch

import pymupdf
from streamlit.testing.v1 import AppTest


def configured(monkeypatch, module='review'):
    monkeypatch.setenv('APP_PASSWORD', 'test-password-only')
    monkeypatch.setenv('ONERGE_DIRECT_API_KEY', 'test-api-only')
    at = AppTest.from_file('../streamlit_app.py', default_timeout=15)
    if module:
        at.session_state['active_module'] = module
    return at


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
        at.session_state['result']['analysis_version']='old-version'
        at.run()
        assert 'result' not in at.session_state
        assert 'markings' not in at.session_state
        assert any('Analiz kuralları güncellendi' in x.value for x in at.info)
    with patch('streamlit.file_uploader', return_value=None):
        at.run()
        assert 'result' not in at.session_state
        assert 'pages' not in at.session_state
        assert 'markings' not in at.session_state


def test_missing_source_card_is_gray_and_not_all_suitable():
    from test_app import report
    r=report().model_dump()
    r['checks'][2]['status']='kaynak_yok'
    r['checks'][2]['explanation']='Kaynakta kayıt yok.'
    payload={'review':r,'warnings':[],'comparisons':[]}
    at=AppTest.from_string('from streamlit_app import render_report, render_status_summary\n'+'result='+repr(payload)+'\nrender_status_summary(result["review"]["checks"])\nrender_report(result)').run()
    assert not at.exception
    assert not at.success
    assert 'check-card kaynak_yok' in '\n'.join(x.value for x in at.markdown)
    assert 'Kaynakta kayıt yok: 1' in at.caption[0].value


def test_render_failure_preserves_report_and_retry_does_not_call_api(monkeypatch):
    from test_app import report, pdf
    data = pdf()
    class Upload:
        def getvalue(self): return data
    calls = []
    async def analyze(*args, **kwargs):
        calls.append(1)
        raw = report()
        raw.pages[0].text = 'Reference text 10'
        for check in raw.checks:
            check.quote = raw.pages[0].text
        raw.checks[0].status = 'uyari'
        return raw
    at = configured(monkeypatch)
    with patch('streamlit.file_uploader', return_value=Upload()), patch('app.analyze', analyze):
        at.run()
        at.text_input[0].set_value('test-password-only')
        at.button[0].click().run()
        with patch('annotations.annotate_pdf', side_effect=RuntimeError('private parser detail')):
            next(b for b in at.button if b.label == 'İncelemeyi başlat').click().run()
        assert not at.exception
        assert 'result' in at.session_state
        assert 'markings' not in at.session_state
        assert len(at.get('download_button')) == 1
        assert any('Analiz tamamlandı' in item.value for item in at.warning)
        assert 'private parser detail' not in '\n'.join(item.value for item in at.warning)
        assert '<mark class="issue-text">' in '\n'.join(item.value for item in at.markdown)
        next(b for b in at.button if b.label == 'PDF işaretlerini yeniden oluştur').click().run()
        assert not at.exception
        assert 'markings_error' not in at.session_state
        assert len(at.get('download_button')) == 2
        at.run()
        assert len(calls) == 1
        for name in ('ONERGE_DIRECT_API_KEY', 'ONERGE_API_KEY', 'OPENAI_API_KEY'):
            monkeypatch.delenv(name, raising=False)
        at.run()
        assert len(at.get('download_button')) == 2
        assert next(b for b in at.button if b.label == 'İncelemeyi başlat').disabled


def test_invalid_file_error_remains_specific_across_reruns(monkeypatch):
    import pymupdf
    with pymupdf.open() as doc:
        doc.new_page()
        data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='test')
    class Upload:
        def getvalue(self): return data
    at = configured(monkeypatch)
    with patch('streamlit.file_uploader', return_value=Upload()):
        at.run()
        at.text_input[0].set_value('test-password-only')
        at.button[0].click().run()
        assert 'Şifreli PDF' in at.error[0].value
        at.run()
        assert 'Şifreli PDF' in at.error[0].value
        assert not at.exception


def test_all_green_and_zero_counter_colors():
    from test_app import report
    payload = report().model_dump()
    at = AppTest.from_string('from streamlit_app import render_status_summary\n'
                            + 'render_status_summary(' + repr(payload['checks']) + ')').run()
    assert at.success[0].value == 'Şekli bakımdan tüm koşullara uygundur.'
    rendered = '\n'.join(item.value for item in at.markdown)
    assert rendered.count('status-card uygun') == 1
    assert rendered.count('status-card neutral') == 2


def test_version_is_visible_without_upload_or_api_charge(monkeypatch):
    from app import RELEASE
    at = configured(monkeypatch).run()
    assert any(RELEASE in item.value for item in at.caption)
