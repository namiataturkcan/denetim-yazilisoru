"""Synthetic directories exercise logic; they are not production geography data."""
from copy import deepcopy

import pytest

from district_validation import DistrictDirectory


REFERENCE = {'source': {'file': 'SENTETİK TEST LİSTESİ', 'url': 'https://example.invalid/test'},
             'provinces': {'Birinciil': ['Çınarlı', 'Dereyaka', 'Ortak', '19 Örnekkent'],
                           'İkinciil': ['Ortak', 'Yazlık', 'Derelya']}}


@pytest.fixture
def directory():
    return DistrictDirectory(REFERENCE)


@pytest.mark.parametrize('summary', [
    'Birinciil’in Çınarlı ilçesindeki yollara ilişkin',
    'Birinciil ili Çınarlı ilçesinde yaşanan sorunlara ilişkin',
    'Ortak ilçesindeki sorunlara ilişkin',
    'İkinciil’in Ortak ilçesindeki sorunlara ilişkin',
    'Birinciil’in 19 Örnekkent ilçesindeki sorunlara ilişkin',
    'Birinciil’in Çınarlı ve Dereyaka ilçelerindeki sorunlara ilişkin',
    'Birinciil’in Çınarlı, Dereyaka ve Ortak ilçelerindeki sorunlara ilişkin',
])
def test_valid_district_mentions(directory, summary):
    assert directory.check(summary) == []


@pytest.mark.parametrize('name', ['Çınarl', 'Cinarli', 'Çınalrı'])
def test_typos_are_suggestions_with_exact_source_offsets(directory, name):
    value = f'Birinciil’in {name} ilçesindeki okullara ilişkin'
    [finding] = directory.check(value)
    assert finding['rule'] == 'district_spelling' and finding['after'] == 'Çınarlı'
    assert value[finding['start']:finding['end']] == finding['before'] == name
    assert finding['conditional']


def test_known_district_wrong_province_is_not_fuzzily_reassigned(directory):
    [finding] = directory.check('Birinciil’in Yazlık ilçesine ilişkin')
    assert finding['rule'] == 'district_province'
    assert finding['after'] == 'İkinciil / Yazlık'


def test_multiple_districts_share_only_the_immediate_explicit_province(directory):
    results = directory.check('Birinciil’in Çınarlı ve Yazlık ilçelerindeki hizmetlere ilişkin')
    assert len(results) == 1 and results[0]['before'] == 'Yazlık'
    assert results[0]['rule'] == 'district_province'


def test_absence_is_not_a_claim_that_place_is_a_village_or_not_current_district(directory):
    [finding] = directory.check('Yeniörek ilçesinin sorunlarına ilişkin')
    assert finding['rule'] == 'district_not_in_source'
    assert 'kanıtlamaz' in finding['reason'] and 'güncel' in finding['reason']


@pytest.mark.parametrize('summary', [
    'Yeniörek beldesinin sorunlarına ilişkin',
    'Yeniörek köyüne ilişkin',
    'Birinciil’de düzenlenen toplantıda Yazlık ilçesinin sorunlarına ilişkin',
    'Birinciil’in yolları ve Yazlık ilçesindeki okullara ilişkin',
    'bazı ilçelerdeki sorunlara ilişkin',
    'bir ilçesinde yaşanan sorunlara ilişkin',
    'Çınarlı Bey’in açıklamasına ilişkin',
])
def test_people_settlements_and_unrelated_provinces_are_not_treated_as_district_mistakes(directory, summary):
    assert directory.check(summary) == []


def test_source_is_required_and_never_changed():
    original = deepcopy(REFERENCE)
    DistrictDirectory(REFERENCE).check('Yeniörek ilçesine ilişkin')
    assert REFERENCE == original
    with pytest.raises(ValueError):
        DistrictDirectory({'source': REFERENCE['source'], 'provinces': {}})


def test_only_manual_summary_is_checked_and_district_suggestions_use_existing_exports():
    from app import RULES
    from entry_comparison import Sheet
    from summary_proofreading import review_summaries, suggestions_csv
    value = ('Yanlışil Milletvekili Örnek İsim’in, Birinciil’in Yazlık ilçesindeki okullara ilişkin '
             'Adalet Bakanı’ndan yazılı soru önergesi')
    sheet = Sheet('KKBS', [(1, ('Evrak No', 'Önerge Sahibi Özeti')), (2, ('100', value))])
    records = [dict(row=2, document='100')]
    report = review_summaries(sheet, records, 1, RULES['recipients'], header=1, district_reference=REFERENCE)
    assert report['district_review']['source'] == REFERENCE['source']
    assert report['checked_count'] == report['affected_count'] == 1
    [finding] = report['suggestions']
    assert finding['document'] == '100' and finding['rule'] == 'district_province'
    assert 'Milletvekili' not in finding['summary']
    assert 'İkinciil / Yazlık' in suggestions_csv(report).decode('utf-8-sig')
    # An inaccessible source must not silently become a guessed built-in list.
    without_source = review_summaries(sheet, records, 1, RULES['recipients'], header=1, district_reference=None)
    assert without_source['district_review'] == {'available': False, 'source': None}
    assert without_source['suggestions'] == []
