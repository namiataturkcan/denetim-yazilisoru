import pytest
from test_app import report
import app
from reading_validation import serious_disagreement


def evaluate(name='Ömer Faruk GERGERLİOĞLU', city='Kocaeli', *, ocr=None, unrelated_uncertainty=False, uncertain=False):
    r=report()
    evidence=f'{name}\n{city} Milletvekili'
    r.pages[0].text=evidence+'\nKonu: kamu personeli. Kaşe: [OKUNAMADI]' if unrelated_uncertainty else evidence
    r.pages[0].uncertainties=['Kaşe okunamadı'] if unrelated_uncertainty else []
    for c in r.checks:
        c.quote=evidence
    r.signatories=[app.Signatory(page=1,name=name,constituency=city,evidence=evidence,constituency_uncertain=uncertain)]
    result=app.finalize(r,[{'ocr':r.pages[0].text if ocr is None else ocr}])
    return next(c for c in result['review']['checks'] if c['kind']=='secim_cevresi'),result


@pytest.mark.parametrize('name,city', list(app.MEMBER_REFERENCE['members'].items()))
def test_every_excel_pair_is_accepted(name,city):
    assert evaluate(name,city)[0]['status']=='uygun'


def test_previous_or_different_province_is_wrong():
    c,_=evaluate(city='İstanbul')
    assert c['status']=='uyari'
    assert 'Kocaeli' in c['explanation']
    assert c['quote']=='İstanbul'


def test_dersim_is_not_silently_normalized():
    c,_=evaluate('Ayten KORDU','Dersim')
    assert c['status']=='uyari'
    assert 'Tunceli' in c['explanation']
    assert c['quote']=='Dersim'


def test_invented_geography_is_wrong_for_known_member():
    assert evaluate(city='Olmayanşehir')[0]['status']=='uyari'


def test_unrelated_page_uncertainty_does_not_mark_kocaeli_yellow():
    assert evaluate(unrelated_uncertainty=True)[0]['status']=='uygun'


def test_missing_ocr_is_not_an_error():
    assert evaluate(ocr='')[0]['status']=='uygun'


def test_material_ocr_city_disagreement_is_yellow():
    c,_=evaluate(ocr='Ömer Faruk GERGERLİOĞLU\nİstanbul Milletvekili')
    assert c['status']=='belirsiz'
    assert 'farklı' in c['explanation']


def test_typography_does_not_count_as_disagreement():
    assert evaluate(ocr='Ömer  Faruk GERGERLİOĞLU\nKocaeli Milletvekili.')[0]['status']=='uygun'


def test_unreadable_field_is_yellow():
    assert evaluate(uncertain=True)[0]['status']=='belirsiz'


def test_unknown_member_is_missing_source_not_ocr_uncertainty():
    c,_=evaluate('Kaynakta Olmayan İsim')
    assert c['status']=='kaynak_yok'
    assert 'Kaynak olmadan' in c['explanation']


def test_absent_province_is_a_form_error():
    assert evaluate(city='')[0]['status']=='uyari'


def test_style_accepts_reference_length_not_old_ten_word_limit():
    r=report();r.summary='Kocaeli ilindeki okulların depreme dayanıklılığının araştırılması için Bakanlık tarafından yürütülen çalışmalara ilişkin'
    out=app.finalize(r,[{'ocr':''}])
    assert out['review']['summary']==r.summary
    r.summary='kelime '*32+'ilişkin'
    assert app.finalize(r,[{'ocr':''}])['review']['summary']==''


def test_comparison_ignores_case_space_and_punctuation():
    assert not serious_disagreement('Ali Yerlikaya tarafından', 'ALİ YERLİKAYA  tarafından.', 'Ali Yerlikaya')
    assert serious_disagreement('Ali Yerlikaya tarafından','Mustafa Çiftçi tarafından','Ali Yerlikaya')


def test_previous_istanbul_instead_of_reference_diyarbakir():
    c,_=evaluate('Mustafa Sezgin TANRIKULU','İstanbul')
    assert c['status']=='uyari'
    assert 'Diyarbakır' in c['explanation']


def test_model_cannot_correct_province_during_extraction():
    r=report();r.pages[0].text='Ayten KORDU\nDersim Milletvekili'
    r.signatories=[app.Signatory(page=1,name='Ayten KORDU',constituency='Tunceli',evidence=r.pages[0].text)]
    c=next(c for c in app.finalize(r,[{'ocr':''}])['review']['checks'] if c['kind']=='secim_cevresi')
    assert c['status']=='belirsiz'


def test_ocr_diacritic_noise_is_not_serious():
    assert not serious_disagreement('Ömer Faruk GERGERLİOĞLU Kocaeli Milletvekili', 'Omer Faruk GERGERLIOGLU Kocaeli Milletvekili', 'Ömer Faruk GERGERLİOĞLU Kocaeli Milletvekili')


def test_independent_ocr_for_scan():
    import pymupdf
    with pymupdf.open() as d:
        p=d.new_page();p.insert_text((70,90),'Kocaeli Milletvekili',fontsize=22)
        png=p.get_pixmap(matrix=pymupdf.Matrix(2,2)).tobytes('png')
    with pymupdf.open() as d:
        p=d.new_page();p.insert_image(p.rect,stream=png);data=d.tobytes()
    pages=app.prepare_pdf(data)
    assert not pages[0]['ocr'].strip()
    app.fill_missing_ocr(pages)
    assert 'Kocaeli' in pages[0]['ocr']
    assert pages[0]['ocr_source']=='tesseract'


def test_source_coverage_and_ministers_are_separate():
    from recipient_validation import normalize
    members=app.MEMBER_REFERENCE['members']
    assert len({normalize(n) for n in members})==len(members)==312
    assert app.RULES['recipients']['İçişleri Bakanı']=='Mustafa ÇİFTÇİ'
    assert app.RULES['recipients']['Adalet Bakanı']=='Akın GÜRLEK'
    assert app.SUMMARY_STYLE['statistics']['count']==50416


def test_clearly_absent_field_is_not_uncertainty():
    r=report()
    c=next(c for c in r.checks if c.kind=='secim_cevresi')
    c.status='uyari';c.quote=''
    c=next(c for c in app.finalize(r,[{'ocr':''}])['review']['checks'] if c['kind']=='secim_cevresi')
    assert c['status']=='uyari'


def test_multiple_signatures_keep_definite_mismatch_visible():
    r=report()
    r.pages[0].text='Ömer Faruk GERGERLİOĞLU\nKocaeli Milletvekili\nAyten KORDU\nDersim Milletvekili'
    r.signatories=[app.Signatory(page=1,name='Ömer Faruk GERGERLİOĞLU',constituency='Kocaeli',evidence='Ömer Faruk GERGERLİOĞLU\nKocaeli Milletvekili'),app.Signatory(page=1,name='Ayten KORDU',constituency='Dersim',evidence='Ayten KORDU\nDersim Milletvekili')]
    c=next(c for c in app.finalize(r,[{'ocr':r.pages[0].text}])['review']['checks'] if c['kind']=='secim_cevresi')
    assert c['status']=='uyari'
    assert 'Kocaeli' in c['explanation'] and 'Tunceli' in c['explanation']


def test_unknown_province_does_not_match_partial_word():
    r=report();r.pages[0].text='Ayten KORDU\nTuncelili'
    r.signatories=[app.Signatory(page=1,name='Ayten KORDU',constituency='Tunceli',evidence=r.pages[0].text)]
    c=next(c for c in app.finalize(r,[{'ocr':''}])['review']['checks'] if c['kind']=='secim_cevresi')
    assert c['status']=='belirsiz'
