import pytest
from test_app import report
import app


def validate(text, uncertainties=None):
    r=report();r.pages[0].text=text;r.pages[0].uncertainties=uncertainties or []
    for c in r.checks:
        c.quote=text
        c.reading_uncertain=bool(uncertainties) if c.kind == "muhatap" else False
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


def test_addressee_conflict_is_not_hidden_by_name_elsewhere():
    r=report()
    r.pages[0].text='İçişleri Bakanı Mustafa Çiftçi tarafından cevaplandırılması. Ek bilgiler.'
    for c in r.checks:
        c.quote=r.pages[0].text
    ocr='İçişleri Bakanı Ali Yerlikaya tarafından cevaplandırılması. Konuşmada İçişleri Bakanı Mustafa Çiftçi adı anılmıştır.'
    result=app.finalize(r,[{'ocr':ocr}])
    check=next(c for c in result['review']['checks'] if c['kind']=='muhatap')
    assert check['status']=='belirsiz'
    assert 'Ali Yerlikaya' in check['explanation']
    assert 'Mustafa Çiftçi' in check['explanation']
    assert result['recipient_audit']['vision'][0]['name']=='Mustafa Çiftçi'
    assert result['recipient_audit']['comparison'][0]['name']=='Ali Yerlikaya'


def test_confirmed_reference_is_recorded_in_report():
    result=app.finalize(report(),[{'ocr':''}])
    reference=result['recipient_audit']['reference']
    assert reference['İçişleri Bakanı']=='Mustafa ÇİFTÇİ'
    assert reference['Adalet Bakanı']=='Akın GÜRLEK'
    assert result['analysis_version']==app.ANALYSIS_VERSION


@pytest.mark.parametrize('title,old_name,expected',[
    ('İçişleri Bakanı','Ali YERLİKAYA','Mustafa ÇİFTÇİ'),
    ('Adalet Bakanı','Yılmaz TUNÇ','Akın GÜRLEK')])
def test_both_explicitly_reconfirmed_ministers(title,old_name,expected):
    c=validate(f'{title} {old_name} tarafından cevaplandırılmasını arz ederim.')
    assert c['status']=='uyari'
    assert expected in c['explanation']


def test_conflicting_addressees_in_comparison_are_not_green():
    r=report();r.pages[0].text='İçişleri Bakanı Mustafa Çiftçi tarafından cevaplandırılması.'
    for c in r.checks:
        c.quote=r.pages[0].text
    ocr=r.pages[0].text+' İçişleri Bakanı Ali Yerlikaya tarafından cevaplandırılması.'
    c=next(c for c in app.finalize(r,[{'ocr':ocr}])['review']['checks'] if c['kind']=='muhatap')
    assert c['status']=='belirsiz'
