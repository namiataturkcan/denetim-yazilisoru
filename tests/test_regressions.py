import asyncio

import pymupdf
import pytest

import app
from annotations import annotate_pdf, marked_text
from reading_validation import ReadingComparison, serious_disagreement
from test_app import report
from test_recipient_validation import validate


def test_report_order_is_independent_of_model_order_and_input_is_not_mutated():
    raw = report()
    raw.checks.reverse()
    original = raw.model_dump()
    first = app.finalize(raw, [{'ocr': ''}])
    assert raw.model_dump() == original
    assert [c['kind'] for c in first['review']['checks']] == list(app.CHECK_ORDER)
    assert first == app.finalize(raw, [{'ocr': ''}])


def test_invalid_signatory_page_rejects_report_cleanly():
    raw = report()
    raw.signatories = [app.Signatory(page=2, name='A B', constituency='Kocaeli', evidence='A B Kocaeli')]
    with pytest.raises(app.HTTPException) as exc:
        app.finalize(raw, [{'ocr': ''}])
    assert exc.value.status_code == 502


def test_summary_accepts_harmless_whitespace_and_terminal_period():
    raw = report()
    raw.summary = '  Kamu\n personeli alımlarına ilişkin.  '
    assert app.finalize(raw, [{'ocr': ''}])['review']['summary'] == 'Kamu personeli alımlarına ilişkin'


@pytest.mark.parametrize('vision,ocr,quote', [
    ('Kocaeli hakkında soru. Ayten KORDU Kocaeli Milletvekili',
     'Kocaeli hakkında soru. Ayten KORDU Tunceli Milletvekili', 'Kocaeli'),
    ('Bu talep kabul edilmiştir', 'Bu talep kabul edilmemiştir', 'Bu talep kabul edilmiştir'),
    ('Bu talep kabul edilmiştir', 'Bu talep kısmen kabul edilmiştir', 'Bu talep kabul edilmiştir'),
    ('Bu talep hiçbir zaman kabul edilmemiştir', 'Bu talep kabul edilmemiştir',
     'Bu talep hiçbir zaman kabul edilmemiştir'),
])
def test_material_ocr_conflicts_include_insertions_and_omissions(vision, ocr, quote):
    assert serious_disagreement(vision, ocr, quote)


def test_fragmentary_ocr_and_unrelated_body_changes_do_not_taint_signature():
    signature = 'Ömer Faruk GERGERLİOĞLU Kocaeli Milletvekili'
    vision = ('Görselden okunan farklı konu sözcükleri ' * 10) + signature
    ocr = ('OCR metninde başka konu bilgileri var ' * 10) + signature
    assert not serious_disagreement(vision, ocr, signature)
    assert not serious_disagreement(vision, 'Kocaeli Milletvekili', signature)


def test_comparison_alignment_is_reused_for_different_checks(monkeypatch):
    import reading_validation
    original = reading_validation.difflib.SequenceMatcher
    calls = []
    def matcher(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(reading_validation.difflib, 'SequenceMatcher', matcher)
    comparison = ReadingComparison('Başvuru kabul edildi. Kocaeli Milletvekili',
                                   'Başvuru reddedildi. Kocaeli Milletvekili')
    assert comparison.disagrees('Başvuru kabul edildi')
    assert not comparison.disagrees('Kocaeli Milletvekili')
    assert len(calls) == 1


def test_correct_signature_not_affected_by_conflicting_province_in_body():
    raw = report()
    signature = 'Ömer Faruk GERGERLİOĞLU\nKocaeli Milletvekili'
    raw.pages[0].text = 'İstanbul hakkında bir soru.\n' + signature
    raw.signatories = [app.Signatory(page=1, name='Ömer Faruk GERGERLİOĞLU', constituency='Kocaeli', evidence=signature)]
    output = app.finalize(raw, [{'ocr': 'Kocaeli hakkında bir soru.\n' + signature}])
    assert output['review']['checks'][2]['status'] == 'uygun'


@pytest.mark.parametrize('text', [
    "İçişleri Bakanı Sayın Mustafa Çiftçi’ye",
    'İçişleri Bakanı Sayın Dr. Mustafa Çiftçi tarafından cevaplandırılması.',
    'İçişleri Bakanı Mustafa Çiftçi tarafından. İçişleri Bakanı Mustafa Çiftçi tarafından.',
])
def test_readable_recipient_formats_do_not_need_manual_review(text):
    assert validate(text)['status'] == 'uygun'


def test_doctor_title_does_not_make_old_minister_acceptable():
    check = validate('İçişleri Bakanı Sayın Dr. Ali Yerlikaya tarafından cevaplandırılması.')
    assert check['status'] == 'uyari'
    assert 'Mustafa ÇİFTÇİ' in check['explanation']


def test_narrative_minister_is_not_confused_with_actual_addressee():
    text = ('İçişleri Bakanı Mustafa Çiftçi tarafından cevaplandırılmasını arz ederim. '
            'İçişleri Bakanı Ali Yerlikaya tarafından yapılan açıklamalar hakkında hangi çalışma yapılmıştır?')
    assert validate(text)['status'] == 'uygun'


def test_ocr_conflict_in_repeated_header_on_second_page_is_detected():
    raw = report()
    text = 'İçişleri Bakanı Mustafa Çiftçi tarafından cevaplandırılması.'
    raw.pages = [app.PageReading(page=i, text=text, uncertainties=[]) for i in (1, 2)]
    for check in raw.checks:
        check.quote = text
    output = app.finalize(raw, [{'ocr': text}, {'ocr': text.replace('Mustafa Çiftçi', 'Ali Yerlikaya')}])
    assert output['review']['checks'][3]['status'] == 'belirsiz'


def test_clearly_missing_recipient_is_red():
    raw = report()
    check = next(c for c in raw.checks if c.kind == 'muhatap')
    check.quote = ''
    check.status = 'uyari'
    assert app.finalize(raw, [{'ocr': ''}])['review']['checks'][3]['status'] == 'uyari'


def test_multiple_wrong_signatures_are_all_marked_in_pdf_and_text():
    raw = report()
    signatures = [('Ayten KORDU', 'Dersim'), ('Ömer Faruk GERGERLİOĞLU', 'İstanbul')]
    raw.pages[0].text = '\n'.join(f'{name}\n{city} Milletvekili' for name, city in signatures)
    raw.signatories = [app.Signatory(page=1, name=name, constituency=city,
                                    evidence=f'{name}\n{city} Milletvekili') for name, city in signatures]
    output = app.finalize(raw, [{'ocr': raw.pages[0].text}])
    findings = [output['review']['checks'][2]]
    markup = marked_text(raw.pages[0].text, findings, 1)
    assert '<mark class="issue-text">Dersim</mark>' in markup
    assert '<mark class="issue-text">İstanbul</mark>' in markup
    with pymupdf.open() as doc:
        page = doc.new_page()
        # Built-in Unicode font keeps Turkish characters searchable.
        page.insert_htmlbox(pymupdf.Rect(60, 60, 500, 300), raw.pages[0].text.replace('\n', '<br>'))
        data = doc.tobytes()
    markings = annotate_pdf(data, findings)
    assert len(markings['locations']) == 2
    assert not markings['missing']


def test_annotations_locate_all_quotes_before_drawing(monkeypatch):
    import annotations
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), 'First issue. Second issue.')
        data = doc.tobytes()
    original = annotations.find_quote
    def find(page, *args, **kwargs):
        assert not list(page.annots())
        return original(page, *args, **kwargs)
    monkeypatch.setattr(annotations, 'find_quote', find)
    result = annotate_pdf(data, [dict(status='uyari', quote=q, page=1, explanation='Test')
                                 for q in ('First issue', 'Second issue')])
    assert len(result['locations']) == 2


def test_word_highlight_does_not_color_substrings():
    result = marked_text('Dersimli kişiler. Dersim', [dict(page=1, status='uyari', quote='Dersim')], 1)
    assert result.count('<mark ') == 1


def test_pdf_limit_applies_to_direct_processing():
    with pytest.raises(app.HTTPException) as exc:
        app.prepare_pdf(b'%PDF-' + b'x' * app.MAX_BYTES)
    assert exc.value.status_code == 413


def test_scan_ocr_failure_is_not_repeated_on_every_analysis(monkeypatch):
    attempts = []
    def fail(*args, **kwargs):
        attempts.append(1)
        raise RuntimeError('No OCR')
    monkeypatch.setattr(pymupdf, 'Pixmap', fail)
    pages = [{'ocr': '', 'image': ''}]
    app.fill_missing_ocr(pages)
    app.fill_missing_ocr(pages)
    assert len(attempts) == 2  # Turkish and English, once each.


def test_analysis_gate_prevents_two_chargeable_calls_and_releases_on_failure(monkeypatch):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def blocked(*args, **kwargs):
            entered.set()
            await release.wait()
            raise ValueError('Invalid upstream report')
        monkeypatch.setattr(app, '_analyze', blocked)
        first = asyncio.create_task(app.analyze([]))
        await entered.wait()
        try:
            with pytest.raises(app.HTTPException) as exc:
                await app.analyze([])
            assert exc.value.status_code == 429
        finally:
            release.set()
        with pytest.raises(ValueError):
            await first
        assert not app.analysis_gate.locked()
    asyncio.run(run())
