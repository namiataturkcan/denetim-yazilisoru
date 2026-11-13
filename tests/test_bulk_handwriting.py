from dataclasses import replace

import pytest

import app
import bulk_review as bulk
from bulk_jobs import matching_coverage
from test_bulk_review import reading, record
from test_bulk_stamp import positioned


def words(parts, *, x=480, y=40, block=0, line=0, gap=6):
    result = []
    for i, value in enumerate(parts):
        width = len(value)*7
        result.append((x, y, x+width, y+15, value, block, line, i))
        x += width+gap
    return result


@pytest.mark.parametrize('parts', [('52', '3', '42'), ('5', '2', '3', '4', '2'), ('5234', '2')])
def test_close_isolated_numeric_fragments_retain_original_quote_and_position(parts):
    result = bulk.positioned_number_candidates(words(parts), 600, 850)
    assert len(result) == 1
    assert result[0]['value'] == ' '.join(parts)
    assert result[0]['rect'][0:2] == [480, 40]
    assert bulk.stamp_number(result[0]['value']) == 52342


@pytest.mark.parametrize('source', [
    words(['52', '3', '42'], x=60),  # Party's left-hand reference number.
    words(['52', '3', '42'], y=400),  # Body numbers.
    words(['52', '3', '42'], gap=40),  # Unrelated columns.
    words(['2025', '2026']),  # Do not concatenate two years.
    words(['52', '?', '42']),
    words(['52', 'O', '42']),
    words(['52', 've', '42']),
    words(['52', '3'], line=0) + words(['42'], line=1, y=60),
])
def test_unrelated_numbers_and_uncertain_digits_are_not_joined(source):
    assert bulk.positioned_number_candidates(source, 600, 850) == []


def test_two_complete_numbers_remain_two_conflicting_candidates():
    result = bulk.positioned_number_candidates(words(['52342', '52343']), 600, 850)
    assert [r['value'] for r in result] == ['52342', '52343']


def two_page_reading(handwritten='52342', *, ocr='w'):
    raw, pages = reading('52342')
    pages[0]['stamp_ocr'] = positioned('52 3 42')
    pages[0]['ocr'] = pages[0]['ocr'].replace('52342', '52 3 42')
    raw.pages.append(app.PageReading(page=2, text=handwritten+'\nSoruların devamı', uncertainties=[]))
    pages.append({'ocr': ocr+'\nSoruların devamı', 'image': 'unused'})
    raw.continuation_numbers = [bulk.ObservedField(value=handwritten, quote=handwritten, page=2, uncertain=False)]
    return raw, pages


def test_same_handwritten_repeat_and_split_stamp_do_not_hide_real_member_error():
    raw, pages = two_page_reading()
    # A refreshed OCR can even get the printed digit wrong. Original positioned
    # fragments and the independently read printed stamp still agree.
    pages[0]['ocr'] = pages[0]['ocr'].replace('52 3 42', '52347')
    records = [replace(record(52342), member='Başka Vekil'), record(52343)]
    result = bulk.compare_proposal(raw, pages, [90, 91], records)
    assert result['number'] == 52342 and result['matched']
    assert [(i['field'], i['status']) for i in result['issues']] == [('KKBS · Milletvekili', 'uyari')]
    assert matching_coverage([records[0]], [result], [])['matching_complete']


def test_meaningful_numeric_handwriting_ocr_conflict_still_requires_review():
    raw, pages = two_page_reading(ocr='52347')
    pages[1]['stamp_ocr'] = positioned('52347')
    result = bulk.compare_proposal(raw, pages, [1, 2], [record(52342)])
    assert result['matched'] and result['number'] == 52342
    assert len(result['issues']) == 1
    assert result['issues'][0]['pages'] == [2]
    assert 'özgün PDF metniyle uyuşmuyor' in result['issues'][0]['explanation']


def test_different_handwritten_number_flags_only_its_page_without_reassigning_kkbs():
    raw, pages = two_page_reading('52343')
    records = [record(52342), replace(record(52343), member='Başka Vekil')]
    result = bulk.compare_proposal(raw, pages, [90, 91], records)
    assert result['number'] == 52342 and result['matched']
    assert len(result['issues']) == 1
    finding = result['issues'][0]
    assert finding['field'] == 'Sayfa eşleştirme' and finding['status'] == 'belirsiz'
    assert finding['number'] == 52342 and finding['pages'] == [91]
    assert finding['expected'] == '52342' and finding['actual'] == '52343'
    assert not matching_coverage([records[0]], [result], [])['matching_complete']


@pytest.mark.parametrize('problem', ['uncertain', 'invalid_digits', 'missing_quote', 'empty_value', 'missing_mark', 'duplicate', 'invalid_page'])
def test_unreadable_or_unsubstantiated_continuation_marks_never_pass_silently(problem):
    raw, pages = two_page_reading()
    mark = raw.continuation_numbers[0]
    if problem == 'uncertain': mark.uncertain = True
    if problem == 'invalid_digits':
        mark.value = mark.quote = '52?42'
        raw.pages[1].text = mark.quote
    if problem == 'missing_quote': mark.quote = 'Alıntı yok'
    if problem == 'empty_value': mark.value = ''
    if problem == 'missing_mark': raw.continuation_numbers = []
    if problem == 'duplicate': raw.continuation_numbers.append(mark.model_copy())
    if problem == 'invalid_page': mark.page = 3
    result = bulk.compare_proposal(raw, pages, [90, 91], [record(52342)])
    assert result['number'] == 52342 and result['matched']
    assert any(i['field']=='Sayfa eşleştirme' and i['status']=='belirsiz' for i in result['issues'])
    assert not matching_coverage([record(52342)], [result], [])['matching_complete']


def test_missing_handwriting_does_not_itself_start_a_new_proposal_or_hide_a_missing_reading():
    raw, pages = two_page_reading('')
    result = bulk.compare_proposal(raw, pages, [90, 91], [record(52342)])
    assert result['matched'] and not result['issues']
    pages[1]['stamp_ocr'] = positioned('52343')
    result = bulk.compare_proposal(raw, pages, [90, 91], [record(52342)])
    assert any(i['field']=='Sayfa eşleştirme' for i in result['issues'])


def test_handwritten_number_cannot_replace_an_unverified_first_page_stamp():
    raw, pages = two_page_reading()
    raw.number = raw.continuation_numbers[0].model_copy()
    result = bulk.compare_proposal(raw, pages, [90, 91], [record(52342)])
    assert result['number'] is None and not result['matched']
    assert any('ilk sayfadaki numaratör' in i['explanation'] for i in result['issues'])
