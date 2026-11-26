import pymupdf
import pytest

from district_validation import DistrictDirectory
from scripts.import_district_reference import build, title
from summary_proofreading import DISTRICT_REFERENCE, review_summaries


@pytest.fixture(scope='module')
def directory():
    return DistrictDirectory(DISTRICT_REFERENCE)


@pytest.mark.parametrize('province,district', [
    (province, district) for province, districts in DISTRICT_REFERENCE['provinces'].items() for district in districts
])
def test_every_imported_pair_is_accepted_with_explicit_province(directory, province, district):
    assert directory.check(f'{province} ili {district} ilçesindeki hizmetlere ilişkin') == []


def test_verified_source_count_continuations_and_recent_rows():
    reference = DISTRICT_REFERENCE
    assert reference['source']['province_count'] == len(reference['provinces']) == 81
    assert reference['source']['district_count'] == sum(map(len, reference['provinces'].values())) == 922
    assert reference['source']['page_count'] == 86 and reference['source']['list_year'] == 2018
    assert len(reference['provinces']['İstanbul']) == 39
    assert len(reference['provinces']['Ankara']) == 25
    assert len(reference['provinces']['Konya']) == 31
    assert len(reference['provinces']['İzmir']) == 30
    assert len(reference['provinces']['Hatay']) == 15
    assert 'Derecik' in reference['provinces']['Hakkari']
    assert 'Sultanhanı' in reference['provinces']['Aksaray']
    assert 'Kemalpaşa' in reference['provinces']['Artvin']
    assert reference['province_pages']['İstanbul'] == [42, 43]
    assert sorted(p for pages in reference['province_pages'].values() for p in pages) == list(range(2, 87))
    assert 'Merkez' not in {d for ds in reference['provinces'].values() for d in ds}


@pytest.mark.parametrize('province,district,expected', [
    ('İstanbul', 'Esenyurtt', 'Esenyurt'),
    ('İstanbul', 'Kadikoy', 'Kadıköy'),
    ('Tekirdağ', 'Marmara Ereğlisi', 'Marmaraereğlisi'),
    ('İstanbul', 'Büyük Çekmece', 'Büyükçekmece'),
    ('Samsun', '19 Mayıs', 'Ondokuzmayıs'),
    ('Kahramanmaraş', '12 Şubat', 'Onikişubat'),
])
def test_spelling_suggestions_come_from_actual_source(directory, province, district, expected):
    value = f'{province} ili {district} ilçesindeki okullara ilişkin'
    [finding] = directory.check(value)
    assert finding['rule'] == 'district_spelling' and finding['after'] == expected
    assert value[finding['start']:finding['end']] == finding['before'] == district
    assert finding['conditional']


def test_wrong_province_and_unknown_settlement_have_distinct_findings(directory):
    [wrong] = directory.check('Ankara’nın Kadıköy ilçesindeki sorunlara ilişkin')
    assert wrong['rule'] == 'district_province' and wrong['after'] == 'İstanbul / Kadıköy'
    [unknown] = directory.check('Muğla’nın Gümüşlük ilçesindeki sorunlara ilişkin')
    assert unknown['rule'] == 'district_not_in_source' and '2018' in unknown['reason']
    assert 'kanıtlamaz' in unknown['reason']


@pytest.mark.parametrize('value', [
    'İstanbul’un Esenyurt ve Avcılar ilçelerindeki sorunlara ilişkin',
    'Çanakkale ili Yenice ilçesindeki sorunlara ilişkin',
    'Karabük ili Yenice ilçesindeki sorunlara ilişkin',
    'Ankara’da yapılan toplantıda Kadıköy ilçesindeki sorunların görüşülmesine ilişkin',
    'Muğla’nın Gümüşlük beldesindeki sorunlara ilişkin',
    'Gümüşlük köyünün sorunlarına ilişkin',
    'Rize merkez ilçesindeki sorunlara ilişkin',
    'İstanbul’un 39 ilçesindeki okullara ilişkin',
    'Ankara’nın üç ilçesinde yaşanan sorunlara ilişkin',
    'Ankara’nın on iki ilçesinde yaşanan sorunlara ilişkin',
])
def test_same_name_districts_and_places_outside_district_scope_are_not_false_errors(directory, value):
    assert directory.check(value) == []


def test_actual_source_is_used_by_default_for_manual_summary_only():
    from app import RULES
    from entry_comparison import Sheet
    raw = ('İstanbul Milletvekili Çiçek Otlu’nun, Ankara’nın Kadıköy ilçesindeki okullara ilişkin '
           'Adalet Bakanı’ndan yazılı soru önergesi')
    sheet = Sheet('KKBS', [(1, ('Evrak No', 'Önerge Sahibi Özeti')), (2, ('100', raw))])
    report = review_summaries(sheet, [dict(row=2, document='100')], 1, RULES['recipients'], header=1)
    assert report['district_review']['available']
    assert report['district_review']['source'] == DISTRICT_REFERENCE['source']
    [finding] = report['suggestions']
    assert finding['rule'] == 'district_province' and finding['document'] == '100'
    assert 'Milletvekili' not in finding['summary']


def pdf_table(tmp_path, tables):
    path = tmp_path / 'synthetic.pdf'
    with pymupdf.open() as doc:
        for heading, rows in tables:
            page = doc.new_page()
            page.insert_text((270, 80), heading)
            for position, (number, name) in enumerate(rows):
                y = 210 + position * 28
                page.insert_text((85, y), str(number))
                page.insert_text((150, y), name)
                page.insert_text((300, y), 'CUMHURIYET ONCESI')
        doc.save(path)
    return path


def test_importer_preserves_continuation_rows_and_optional_closing_star(tmp_path):
    path = pdf_table(tmp_path, [('*HATAY', [(1, 'ALTINOZU')]), ('*HATAY*', [(2, 'ANTAKYA')])])
    source = build(path, expected_counts=(1, 2))
    assert source['province_pages'] == {'Hatay': [1, 2]}
    assert len(source['provinces']['Hatay']) == 2
    with pytest.raises(ValueError, match='kapsamı eksik'):
        build(path)


@pytest.mark.parametrize('tables', [
    [('*ADANA*', [(1, 'ALADAG'), (3, 'CEYHAN')])],
    [('*ADANA*', [(1, 'ALADAG')]), ('*ADANA*', [(1, 'CEYHAN')])],
    [('*ADANA*', [(1, 'ALADAG')]), ('NO HEADING', [(2, 'CEYHAN')])],
])
def test_importer_rejects_gaps_duplicates_and_missing_province(tmp_path, tables):
    with pytest.raises(ValueError):
        build(pdf_table(tmp_path, tables), expected_counts=(1, 2))


def test_turkish_source_case_does_not_lose_dotted_or_dotless_i():
    assert title('İZMİR') == 'İzmir'
    assert title('IĞDIR') == 'Iğdır'
    assert title('İSKENDERUN') == 'İskenderun'
    assert title('ONDOKUZMAYIS') == 'Ondokuzmayıs'
