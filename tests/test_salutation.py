import pytest

import app
from test_bulk_review import reading


HEAD = 'TÜRKİYE BÜYÜK MİLLET MECLİSİ '
FORMS = [HEAD + 'BAŞKANLIĞINA', HEAD + 'BAŞKANLIĞI’NA', HEAD + "BAŞKANLIĞI'NA"]


def heading_report(vision, ocr=None, kind='hitap'):
    review, pages = reading()
    old = review.checks[0].quote
    review.pages[0].text = review.pages[0].text.replace(old, vision)
    pages[0]['ocr'] = pages[0]['ocr'].replace(old, ocr if ocr is not None else vision)
    check = next(c for c in review.checks if c.kind == kind)
    check.quote, check.status, check.explanation = vision, 'uyari', 'Kesme işareti farklı.'
    return review, pages


@pytest.mark.parametrize('vision', FORMS)
@pytest.mark.parametrize('ocr', FORMS)
@pytest.mark.parametrize('kind', ['hitap', 'harf'])
def test_accepted_headings_do_not_become_errors_or_ocr_suspicions(vision, ocr, kind):
    review, pages = heading_report(vision, ocr, kind)
    result = app.finalize(review, pages)
    check = next(c for c in result['review']['checks'] if c['kind'] == kind)
    assert check['status'] == 'uygun'
    assert check['quote'] == vision  # Original apostrophe preserved for highlighting.
    assert next(c for c in review.checks if c.kind == kind).status == 'uyari'


@pytest.mark.parametrize('heading', [HEAD + 'BAŞKANLIĞI', HEAD + 'BAŞKANLIĞINDA',
                                    'TÜRKİYE BÜYÜK MİLLET MECLİSİ KOMİSYONUNA'])
def test_wrong_salutation_is_not_accepted_as_a_punctuation_variant(heading):
    review, pages = heading_report(heading)
    assert app.finalize(review, pages)['review']['checks'][0]['status'] == 'uyari'


@pytest.mark.parametrize('problem', ['uncertain', 'absent', 'ocr_conflict'])
def test_accepted_spelling_never_overrides_unreadable_or_unsubstantiated_heading(problem):
    review, pages = heading_report(FORMS[1])
    if problem == 'uncertain':
        review.checks[0].reading_uncertain = True
    elif problem == 'absent':
        review.pages[0].text = review.pages[0].text.replace(FORMS[1], '')
    else:
        pages[0]['ocr'] = pages[0]['ocr'].replace(FORMS[1], 'İSTANBUL BÜYÜKŞEHİR BELEDİYESİ BAŞKANLIĞINA')
    assert app.finalize(review, pages)['review']['checks'][0]['status'] == 'belirsiz'


def test_apostrophe_permission_does_not_erase_lowercase_warning():
    review, pages = heading_report('Türkiye Büyük Millet Meclisi Başkanlığına'.lower(), kind='harf')
    assert app.finalize(review, pages)['review']['checks'][-1]['status'] == 'uyari'
