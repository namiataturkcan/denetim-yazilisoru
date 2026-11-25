from copy import deepcopy
import csv
import io

import pytest

from app import RULES
from entry_comparison import Sheet
from summary_proofreading import check_summary, review_summaries, suggest_summary_column, suggestions_csv

RECIPIENTS = RULES['recipients']


def check(value):
    return check_summary(value, RECIPIENTS)


def test_spaces_are_visible_suggestions_without_changing_line_breaks():
    original = '  işçi  hakları\n  ve kamu\u00a0\u00a0personeli  '
    suggestions = check(original)
    assert [s['before'] for s in suggestions] == ['  ', '\u00a0\u00a0']
    assert all(s['after'] == ' ' and s['rule'] == 'extra_spaces' for s in suggestions)
    for s in suggestions:
        assert original.strip()[s['start']:s['end']] == s['before']


@pytest.mark.parametrize('wrong,right', [('unvan', 'ünvan'), ('unvanları', 'ünvanları'),
    ('herkez', 'herkes'), ('yalnış', 'yanlış'), ('yanlız', 'yalnız'), ('bir çok', 'birçok'),
    ('bir kaç', 'birkaç'), ('hiç bir', 'hiçbir'), ('herşey', 'her şey'), ('yada', 'ya da'), ('pekçok', 'pek çok')])
def test_verified_dictionary_forms(wrong, right):
    assert any(s['before'] == wrong and s['after'] == right for s in check(f'personelin {wrong} kullanımına ilişkin'))


@pytest.mark.parametrize('wrong,right', [("Sayıştay Başkanlığı'na", 'Başkanlığına'),
    ('Türk Dil Kurumu’ndan', 'Kurumundan'), ("Bakanlar Kurulu'nun", 'Kurulunun'),
    ("İstanbul Üniversitesi'nde", 'Üniversitesinde'), ("X BAŞKANLIĞI’NA", 'BAŞKANLIĞINA')])
def test_institution_suffixes_have_no_apostrophe(wrong, right):
    found = check(wrong)
    assert len(found) == 1 and found[0]['after'] == right
    assert not found[0]['conditional']


@pytest.mark.parametrize('correct', ["Sayıştay Başkanlığına", 'Türk Dil Kurumu Başkanı’na',
    'Avrupa Birliği’ne', 'TBMM’nin', 'Mehmet Bey’e', 'Ankara’ya', 'İstanbul’un',
    "Adalet Bakanı'nın bir açıklamasına ilişkin", "Sayın Bakan'ın açıklamasına ilişkin",
    'Hazine ve Maliye Bakanı', 'HAZİNE VE MALİYE BAKANI', 'ünvan değişikliğine ilişkin'])
def test_valid_titles_abbreviations_and_proper_names_are_not_rewritten(correct):
    assert check(correct) == []


def test_generic_title_is_conditional_and_sentence_case_is_preserved():
    found = check("ilgili Bakan'ın bir açıklamasına ilişkin")
    assert len(found) == 1 and found[0]['after'] == 'bakanın' and found[0]['conditional']
    assert check("Bakan'ın bir açıklaması")[0]['after'] == 'Bakanın'
    assert not check("Ali Bakan'ın açıklamasına ilişkin")  # Personal surname.


def test_conjunction_in_known_office_and_proper_name_protection():
    found = check('Hazine Ve Maliye Bakanı ve Çevre, Şehircilik Ve İklim Değişikliği Bakanı')
    assert len(found) == 2 and all(s['before'] == 'Ve' and s['after'] == 've' for s in found)
    assert not check("Van Milletvekili Ali Unvan'ın, Yanlız köyüne ilişkin")
    assert not check("Van Milletvekili ali unvan'ın, yanlız köyü hakkında")
    assert not check('“herkez unvan” başlıklı bir yayına ilişkin')


def test_summary_column_is_explicit_and_does_not_pick_notes_or_names():
    sheet = Sheet('KKBS', [(1, ('Evrak No', 'Önerge Sahibi Özeti', 'Özet', 'Açıklama'))])
    assert suggest_summary_column(sheet, 1) == 2
    assert suggest_summary_column(Sheet('KKBS', [(1, ('Milletvekili', 'Açıklama'))]), 1) is None
    assert suggest_summary_column(sheet, 0) is None


def test_review_includes_unmatched_rows_retains_original_ids_and_ignores_blank_cells():
    sheet = Sheet('KKBS', [(1, ('Evrak No', 'Özet')), (2, ('100', 'kamu  çalışanlarına ilişkin')),
                          (3, ('101', 'unvan değişikliğine ilişkin')), (4, ('102', None))])
    records = [dict(row=i, document=str(i+98)) for i in (2,3,4)]
    original = deepcopy(sheet)
    report = review_summaries(sheet, records, 1, RECIPIENTS)
    assert report['checked_count'] == 2 and report['empty_count'] == 1 and report['affected_count'] == 2
    assert [s['document'] for s in report['suggestions']] == ['100', '101']
    assert sheet == original
    assert not review_summaries(sheet, records, None, RECIPIENTS)['available']


def test_csv_preserves_spaces_and_escapes_spreadsheet_formulas():
    sheet = Sheet('KKBS', [(1, ('Evrak No', 'Özet')), (2, ('=1+1', 'iki  kelimeye ilişkin'))])
    report = review_summaries(sheet, [dict(row=2, document='=1+1')], 1, RECIPIENTS)
    rows = list(csv.reader(io.StringIO(suggestions_csv(report).decode('utf-8-sig')), delimiter=';'))
    assert rows[1][:3] == ["'=1+1", '  ', ' ']


def test_only_manual_summary_is_checked_and_last_iliskin_marks_end():
    from summary_proofreading import summary_text
    raw = ("Ankara Milletvekili  Ali Unvan'ın, personele ilişkin bir düzenlemenin  unvan değişikliğine ilişkin "
           "Hazine Ve Maliye Bakanı'ndan yazılı soru önergesi (Başkanlığa geliş tarihi: 20-11-2026)")
    body = 'personele ilişkin bir düzenlemenin  unvan değişikliğine ilişkin'
    assert summary_text(raw, True, RECIPIENTS) == body
    sheet = Sheet('KKBS', [(1, ('Evrak No', 'Önerge Sahibi Özeti')), (2, ('100', raw))])
    result = review_summaries(sheet, [dict(row=2, document='100')], 1, RECIPIENTS, header=1)
    assert result['checked_count'] == 1
    assert {s['rule'] for s in result['suggestions']} == {'extra_spaces', 'unvan'}
    assert all(s['summary'] == body for s in result['suggestions'])


def test_unrecognized_combined_summary_is_skipped_not_silently_approved():
    sheet = Sheet('KKBS', [(1, ('Evrak No', 'Önerge Sahibi Özeti')), (2, ('100', 'belirsiz metin  unvan'))])
    result = review_summaries(sheet, [dict(row=2, document='100')], 1, RECIPIENTS, header=1)
    assert result['checked_count'] == 0 and result['skipped_documents'] == ['100']
    assert not result['suggestions']


def test_title_at_start_of_manual_fragment_is_not_a_sentence_start():
    raw = "Ankara Milletvekili Ali Yılmaz'ın, Bakan'ın bir açıklamasına ilişkin Adalet Bakanı'ndan yazılı soru önergesi"
    sheet = Sheet('KKBS', [(1, ('Evrak No', 'Önerge Sahibi Özeti')), (2, ('100', raw))])
    result = review_summaries(sheet, [dict(row=2, document='100')], 1, RECIPIENTS, header=1)
    assert result['suggestions'][0]['after'] == 'bakanın'
    assert result['suggestions'][0]['conditional']


def test_inflected_place_markers_and_personal_titles_protect_names():
    assert not check('yanlız köyüne ulaşım ve unvan sokağında altyapı')
    assert not check('ahmet unvan Bey hakkında')
    assert check('personelin unvan değişikliğine ilişkin')[0]['after'] == 'ünvan'


@pytest.mark.parametrize('before,after', [
    ('kayyum', 'kayyım'), ('Kayyum', 'Kayyım'), ('KAYYUM', 'KAYYIM'),
    ('kayyuma', 'kayyıma'), ('kayyumun', 'kayyımın'), ('kayyumu', 'kayyımı'),
    ('kayyumuna', 'kayyımına'), ('kayyumunun', 'kayyımının'),
    ('kayyumların', 'kayyımların'), ('kayyumları', 'kayyımları'),
    ('kayyumluk', 'kayyımlık'), ('kayyumluğuna', 'kayyımlığına'),
    ('kayyumcu', 'kayyımcı'), ('kayyumsuz', 'kayyımsız'), ('kayyumdu', 'kayyımdı'),
    ('KAYYUMLUĞUNDAN', 'KAYYIMLIĞINDAN')])
def test_tdk_redirect_kayyum_preserves_suffix_harmony_and_case(before, after):
    suggestions = check(f'belediyelerde {before} uygulamasına ilişkin')
    assert [(s['before'], s['after']) for s in suggestions] == [(before, after)]
    assert not suggestions[0]['conditional']


@pytest.mark.parametrize('value', ['kayyım atanmasına ilişkin', 'kayyımların işlemlerine ilişkin',
    'kayyımlığından kaynaklanan sorunlara ilişkin', 'Kayyum köyüne ilişkin',
    'Ahmet Kayyum Bey hakkında', '“kayyum” sözcüğüne ilişkin', 'Kayyumova adına ilişkin'])
def test_correct_kayyim_and_protected_names_are_not_changed(value):
    assert not check(value)


@pytest.mark.parametrize('ending', ['ilişki', 'iliski', 'iliskin', 'ilişkın', 'ilişin', 'ilişkinn', 'ilişkin.', 'ilişkin,'])
def test_misspelled_or_punctuated_terminal_iliskin(ending):
    from summary_proofreading import check_summary_ending
    value = 'işçi haklarına ' + ending
    result = check_summary_ending(value)
    assert len(result) == 1
    assert result[0]['before'] == ending and result[0]['after'] == 'ilişkin'
    assert result[0]['rule'] == 'summary_ending' and not result[0]['conditional']
    assert value[:result[0]['start']] + result[0]['after'] == 'işçi haklarına ilişkin'


@pytest.mark.parametrize('value', ['işçi haklarına ilişkin', 'İŞÇİ HAKLARINA İLİŞKİN', 'haklarına ilişkin \n'])
def test_correct_ending_does_not_create_a_suggestion(value):
    from summary_proofreading import check_summary_ending
    assert not check_summary_ending(value)


@pytest.mark.parametrize('value', ['personel hakları hakkında', 'personel haklarına', '2026',
                                  'bir düzenlemeye ilişkin açıklama'])
def test_missing_ending_requires_editorial_revision_not_bad_automatic_grammar(value):
    from summary_proofreading import check_summary_ending
    [finding] = check_summary_ending(value)
    assert finding['conditional'] and finding['after'] == '… ilişkin'
    assert finding['before'] == value


@pytest.mark.parametrize('ending', ['ilişki', 'iliski', 'ilişkinn', 'hakkında', ''])
@pytest.mark.parametrize('recipient', ["Adalet Bakanı'ndan", 'Çevre Bakanından',
    'Çevre, Şehircilik Ve İklim Değişikliği Bakanı’ndan',
    "Cumhurbaşkanı Yardımcısı'ndan (Cevdet YILMAZ)", "Milli Eğitim Bakanı'ndan"])
def test_combined_summary_is_extracted_without_depending_on_correct_ending(ending, recipient):
    from summary_proofreading import summary_text
    body = ('bir düzenlemeye ilişkin açıklamada kayyum atanmasına ' + ending).strip()
    value = f"Ankara Milletvekili Ali Yılmaz'ın, {body} {recipient} yazılı soru önergesi (Başkanlığa geliş tarihi: 25-11-2026)"
    assert summary_text(value, True, RECIPIENTS) == body
    sheet = Sheet('KKBS', [(1, ('Evrak No', 'Önerge Sahibi Özeti')), (2, ('100', value))])
    report = review_summaries(sheet, [dict(row=2, document='100')], 1, RECIPIENTS, header=1)
    assert report['checked_count'] == 1 and not report['skipped_documents']
    assert {f['rule'] for f in report['suggestions']} == {'kayyim', 'summary_ending'}
    assert all(f['summary'] == body for f in report['suggestions'])


def test_recipient_mention_in_summary_does_not_cut_the_manual_text():
    from summary_proofreading import summary_text
    body = "Adalet Bakanı'nın bir açıklamasına ve Hazine Ve Maliye Bakanı'nın yanıtına ilişki"
    raw = f"Ankara Milletvekili Ali Yılmaz'ın, {body} Çalışma Ve Sosyal Güvenlik Bakanı'ndan yazılı soru önergesi"
    assert summary_text(raw, True, RECIPIENTS) == body


@pytest.mark.parametrize('value', ['konuyla ilişkili', 'konuyla ilişkisi', '"haklara ilişkin"'])
def test_ending_rewrite_does_not_break_case_suffixes_or_balanced_quotes(value):
    from summary_proofreading import check_summary_ending
    [finding] = check_summary_ending(value)
    assert finding['conditional'] and finding['before'] == value
