import pymupdf
from annotations import annotate_pdf, marked_text


def check(quote, status='uyari', page=1):
    return dict(quote=quote, status=status, page=page, explanation='Test finding')


def test_marked_text_escapes_merges_and_respects_page_status():
    text = '<script>alert(1)</script> Wrong\n wording here'
    result = marked_text(text, [check('Wrong wording'), check('wording here'), check('script', 'uygun'), check('alert', page=2)], 1)
    assert '<script>' not in result
    assert '&lt;script&gt;' in result
    assert result.count('<mark ') == 1
    assert 'Wrong\n wording here</mark>' in result


def test_pdf_marks_exact_quote_and_reports_missing():
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), 'Wrong wording here')
        original = doc.tobytes()
    result = annotate_pdf(original, [check('Wrong wording'), check(''), check('here','uygun'), check('Wrong wording',page=2)])
    assert len(result['locations']) == 1
    assert len(result['missing']) == 1
    assert result['missing'][0]['number'] == 2
    with pymupdf.open(stream=result['pdf'],filetype='pdf') as doc:
        assert len(list(doc[0].annots())) == 2
        assert 'Wrong wording here' in doc[0].get_text()
    with pymupdf.open(stream=original,filetype='pdf') as doc:
        assert list(doc[0].annots()) == []


def test_scan_ocr_maps_quote():
    with pymupdf.open() as doc:
        p=doc.new_page(); p.insert_text((72, 100), 'Wrong wording here',fontsize=22)
        png=p.get_pixmap(matrix=pymupdf.Matrix(2,2)).tobytes('png')
    with pymupdf.open() as doc:
        p=doc.new_page();p.insert_image(p.rect,stream=png);data=doc.tobytes()
    result=annotate_pdf(data,[check('Wrong wording')])
    assert len(result['locations']) == 1
    assert not result['missing']


def test_missing_ocr_is_explicit(monkeypatch):
    def fail(*a,**k): raise RuntimeError('unavailable')
    monkeypatch.setattr(pymupdf.Page,'get_textpage_ocr',fail)
    with pymupdf.open() as doc:
        doc.new_page();data=doc.tobytes()
    result=annotate_pdf(data,[check('not found')])
    assert not result['locations']
    assert len(result['missing']) == 1
