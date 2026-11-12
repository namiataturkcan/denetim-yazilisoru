import pymupdf
import pytest

import app
from reading_validation import damaged_ocr, serious_disagreement


DAMAGED = ('Kamu h1zmetleri soru~turma \n' * 12) + 'Kocaeli Milletvekili'
CLEAN = ('Kamu hizmetleri sorusturma \n' * 12) + 'Kocaeli Milletvekili'


def replacement(monkeypatch, text):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 40), text, fontsize=10)
        data = doc.tobytes()
    attempts = []
    class Pix:
        def pdfocr_tobytes(self, **kwargs):
            attempts.append(kwargs['language'])
            return data
    monkeypatch.setattr(pymupdf, 'Pixmap', lambda *args: Pix())
    return attempts


def test_reprocesses_heavily_damaged_layer_without_using_model_or_reference(monkeypatch):
    attempts = replacement(monkeypatch, CLEAN)
    page = {'ocr': DAMAGED, 'ocr_source': 'pdf_text', 'image': ''}
    app.fill_missing_ocr([page])
    assert page['ocr_source'] == 'tesseract'
    assert page['ocr_original'] == DAMAGED and 'hizmetleri' in page['ocr']
    app.fill_missing_ocr([page])
    assert attempts == ['tur+eng']
    assert not serious_disagreement(CLEAN, page['ocr'], 'Kocaeli Milletvekili')
    assert serious_disagreement(CLEAN.replace('Kocaeli', 'Istanbul'), page['ocr'], 'Istanbul Milletvekili')


@pytest.mark.parametrize('text', ['', 'Kocaeli Milletvekili', DAMAGED])
def test_failed_incomplete_or_equally_noisy_replacement_keeps_original(monkeypatch, text):
    attempts = replacement(monkeypatch, text)
    page = {'ocr': DAMAGED, 'ocr_source': 'pdf_text', 'image': ''}
    app.fill_missing_ocr([page])
    app.fill_missing_ocr([page])
    assert page['ocr'] == DAMAGED and page['ocr_source'] == 'pdf_text'
    assert not page.get('ocr_original')
    assert attempts == ['tur+eng', 'eng']


def test_normal_names_numbers_accents_and_meaningful_conflicts_do_not_trigger_rewrite(monkeypatch):
    attempts = replacement(monkeypatch, CLEAN)
    for text in ['7/50000 İçişleri Bakanı Ali YERLİKAYA', 'Anayasa 98 ve 96. madde B2B iletişimine ilişkin', CLEAN]:
        assert not damaged_ocr(text)
        page = {'ocr': text, 'image': ''}
        app.fill_missing_ocr([page])
        assert page['ocr'] == text
    assert not attempts
