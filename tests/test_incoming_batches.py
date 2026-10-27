import pytest

from app import RULES
from incoming_papers import (TableError, add_batch, build_report, combined_batch_ranges,
                             number_ranges, read_records, report_text)
from test_incoming_papers import PENDING, ANNOUNCED


def query(first, last, selected, *, stage='prepare', term=''):
    status = PENDING if stage == 'prepare' else ANNOUNCED
    rows = [[n, status if n in selected else 'Cevaplandı', 'Adalet Bakanı']
            for n in range(first, last + 1)]
    report = build_report(read_records(rows), first, last, '', RULES['recipients'], stage=stage)
    report['term'] = term
    return report


def test_exact_kkbs_example_and_export_repeat_singletons_with_ascii_hyphens():
    expected = ('44613-44613;44616-44700;44703-44703;44705-44705;44707-44709;'
                '44712-44712;44714-44714;44717-44717;44719-44741;44743-44758;44760-44778')
    numbers = {n for part in expected.split(';')
               for a, b in [map(int, part.split('-'))] for n in range(a, b + 1)}
    result = query(44613, 44778, numbers)
    assert result['ranges_text'] == expected
    assert expected in report_text(result).splitlines()
    assert result['ranges'] == expected.split(';')
    assert expected.isascii()
    assert number_ranges([]) == []
    assert number_ranges([999999999]) == ['999999999-999999999']


def test_batches_keep_each_query_intact_including_overlapping_numbers():
    batches = add_batch([], query(1, 4, {1, 3, 4}))
    batches = add_batch(batches, query(3, 7, {3, 4, 5, 7}))
    batches = add_batch(batches, query(10, 11, {10}))
    assert combined_batch_ranges(batches) == ['1-1', '3-4', '3-5', '7-7', '10-10']
    assert len({n for b in batches for n in b['numbers']}) == 6


def test_adjacent_packets_keep_user_example_boundary_in_both_outputs():
    first = query(50000, 50100, set(range(50000, 50101)) - {50014, 50059})
    second = query(50101, 50200, set(range(50101, 50201)))
    batches = add_batch(add_batch([], first), second)
    ranges = combined_batch_ranges(batches)
    assert ';'.join(ranges) == '50000-50013;50015-50058;50060-50100;50101-50200'
    assert '\n'.join(ranges) == '50000-50013\n50015-50058\n50060-50100\n50101-50200'


def test_snapshot_keeps_insertion_order_and_is_independent_of_later_query_changes():
    high = query(11, 12, {11, 12})
    batches = add_batch([], high)
    high['ranges'].clear()
    batches = add_batch(batches, query(9, 10, {9, 10}))
    assert combined_batch_ranges(batches) == ['11-12', '9-10']
    updated = add_batch(batches, query(11, 12, {12}))
    assert combined_batch_ranges(updated) == ['12-12', '9-10']
    assert combined_batch_ranges(batches) == ['11-12', '9-10']


def test_readding_same_query_updates_snapshot_instead_of_duplicating_it():
    first = query(1, 3, {1, 2})
    batches = add_batch([], first)
    assert add_batch(batches, first) == batches
    updated = add_batch(batches, query(1, 3, {3}))
    assert len(updated) == 1
    assert combined_batch_ranges(updated) == ['3-3']
    assert combined_batch_ranges(batches) == ['1-2']  # Input is not mutated.


def test_conflicting_overlap_is_rejected_without_keeping_stale_selected_numbers():
    batches = add_batch([], query(1, 4, {1, 3, 4}))
    with pytest.raises(TableError, match='farklı sonuç'):
        add_batch(batches, query(3, 5, {3, 5}))
    assert combined_batch_ranges(batches) == ['1-1', '3-4']


@pytest.mark.parametrize('stage,term', [('verify', ''), ('prepare', '28. Dönem')])
def test_stages_and_different_or_missing_period_metadata_cannot_mix(stage, term):
    with pytest.raises(TableError, match='birleştirilemez'):
        add_batch(add_batch([], query(1, 1, {1})), query(2, 2, {2}, stage=stage, term=term))


def test_empty_queries_are_not_added_and_incomplete_source_warning_is_preserved():
    with pytest.raises(TableError, match='eklenecek önerge yok'):
        add_batch([], query(1, 2, set()))
    result = query(1, 2, {1})
    result['assessment_complete'] = False
    batch = add_batch([], result)[0]
    assert batch['assessment_complete'] is False
    assert 'rows' not in batch  # Store only selected numbers, not entire reports.
