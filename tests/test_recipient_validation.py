import pytest
from test_app import report
import app


def validate(text, uncertainties=None):
    r=report();r.pages[0].text=text;r.pages[0].uncertainties=uncertainties or []
    for c in r.checks:
        c.quote=text
    result=app.finalize(r,[{'ocr':text}])
    return next(c for c in result['review']['checks'] if c['kind']=='muhatap')


@pytest.mark.parametrize('text',[
    'İçişleri Bakanı Ali Yerlikaya tarafından cevaplandırılmasını arz ederim.',
    'İÇİŞLERİ BAKANI SAYIN ALİ YERLİKAYA tarafından cevaplandırılmasını arz ederim.',
    "İçişleri Bakanı Ali Yerlikaya’nın cevaplandırmasını arz ederim.",
    'İçişleri Bakanı Ali\nYERLİKAYA tarafından cevaplandırılması. Mustafa Çiftçi başka yerde anılıyor.',
])
def test_wrong_name_cannot_remain_green(text):
    c=validate(text)
    assert c['status']=='uyari'
    assert 'Mustafa ÇİFTÇİ' in c['explanation']
    assert c['quote'] in text
    assert 'yerlikaya' in c['quote'].replace('İ', 'i').lower()


@pytest.mark.parametrize('title,name',list(app.RULES['recipients'].items()))
def test_matching_user_list(title,name):
    assert validate(f'{title} Sayın {name} tarafından cevaplandırılması.')['status']=='uygun'


def test_unknown_format_is_not_approved():
    assert validate('Muhatap okunamıyor.')['status']=='belirsiz'


def test_uncertainty_is_not_red_or_green():
    assert validate('İçişleri Bakanı Ali Yerlikaya tarafından cevaplandırılması.', ['Soyadı belirsiz'])['status']=='belirsiz'


def test_historical_reference_is_not_current_addressee():
    text='İçişleri Bakanı Mustafa ÇİFTÇİ tarafından cevaplandırılması. Eski İçişleri Bakanı Ali Yerlikaya tarafından yapılan açıklama nedir?'
    assert validate(text)['status']=='uygun'


def test_multiple_addressees_require_review():
    text='İçişleri Bakanı Ali Yerlikaya tarafından. İçişleri Bakanı Mustafa Çiftçi tarafından.'
    assert validate(text)['status']=='belirsiz'


def test_model_opinion_cannot_override_matching_list():
    r=report()
    text='İçişleri Bakanı Mustafa Çiftçi tarafından cevaplandırılması.'
    r.pages[0].text=text
    for c in r.checks:
        c.quote=text
    c=next(c for c in r.checks if c.kind=='muhatap')
    c.status='uyari'
    c.explanation='Modelin eski bilgisine göre başka isim olmalı.'
    result=app.finalize(r,[{'ocr':text}])
    c=next(c for c in result['review']['checks'] if c['kind']=='muhatap')
    assert c['status']=='uygun'
    assert 'yalnızca bu liste' in c['explanation']


def test_unverified_model_warning_is_not_list_verification():
    r=report()
    c=next(c for c in r.checks if c.kind=='muhatap')
    c.status='uyari'
    result=app.finalize(r,[{'ocr':''}])
    assert next(c for c in result['review']['checks'] if c['kind']=='muhatap')['status']=='belirsiz'
