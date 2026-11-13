import asyncio
import json
from dataclasses import replace
from unittest.mock import patch

import pytest

import app
import bulk_jobs as jobs
import bulk_review as bulk
from bulk_replay import load_readings, recheck_readings
from test_app import pdf
from test_bulk_handwriting import two_page_reading
from test_bulk_jobs import patch_pipeline, wait
from test_bulk_review import record


def saved_cache():
    data = pdf(2)
    raw, pages = two_page_reading()
    job = jobs.BulkJob(data, 2, [record(52342)], 'test-model', 'source', test_pages=[1, 2], single_proposal=True)
    job.readings[0] = {'physical_pages': [1, 2], 'review': raw.model_dump(),
                       'pages': [{k: p[k] for k in ('ocr', 'stamp_ocr') if k in p} for p in pages],
                       'boundary_warnings': []}
    return data, job.reading_cache()


def test_single_proposal_sample_uses_one_call_and_keeps_original_pdf_pages(monkeypatch):
    calls, _ = patch_pipeline(monkeypatch)
    job = jobs.BulkJob(b'pdf', 221, [record(n) for n in range(50000, 50102)], 'test', 'source',
                       test_pages=[180, 181], single_proposal=True)
    job.start('test-only'); wait(job)
    assert calls == {'index': [], 'review': [[180, 181]]}
    result = job.snapshot()
    assert result['page_count'] == 2 and result['original_page_count'] == 221
    assert result['is_test'] and not result['complete']
    assert not any(i['field'] == 'PDF eşleştirme' for i in result['issues'])


def test_automatic_boundary_sample_never_renders_or_sends_unselected_pages(monkeypatch):
    calls, _ = patch_pipeline(monkeypatch)
    rendered = []
    def render(data, numbers):
        rendered.extend(numbers)
        return numbers
    monkeypatch.setattr(jobs, 'render_pages', render)
    job = jobs.BulkJob(b'pdf', 221, [record()], 'test', 'source', test_pages=list(range(177, 183)))
    job.start('test-only'); wait(job)
    assert calls['index'] == [[177, 178, 179, 180], [181, 182]]
    assert set(rendered) == set(range(177, 183))
    assert all(177 <= p <= 182 for unit in calls['review'] for p in unit)


@pytest.mark.parametrize('pages', [[], [0], [222], [2, 1], [1, 1], [1, 3], list(range(1, 12)), [True]])
def test_sample_limits_are_enforced_before_any_api_call(pages):
    with pytest.raises(bulk.TableError):
        jobs.BulkJob(b'pdf', 221, [record()], 'test', 'source', test_pages=pages)
    with pytest.raises(bulk.TableError):
        jobs.BulkJob(b'pdf', 221, [record()], 'test', 'source', single_proposal=True)


def test_export_keeps_paid_reading_even_if_later_validation_fails(monkeypatch):
    raw, pages = two_page_reading()
    monkeypatch.setattr(bulk, 'render_pages', lambda *a, **kw: pages)
    async def analyze(*a, **kw): return raw
    monkeypatch.setattr(app, 'analyze', analyze)
    monkeypatch.setattr(bulk, 'compare_proposal', lambda *a, **kw: (_ for _ in ()).throw(ValueError('bad validation')))
    job = jobs.BulkJob(pdf(2), 2, [record(52342)], 'test', 'source', test_pages=[1, 2], single_proposal=True)
    job.start('test-api-key-do-not-export'); wait(job)
    assert job.snapshot()['failed'] == 1
    saved = job.reading_cache()
    assert b'test-api-key-do-not-export' not in saved and b'"image"' not in saved
    value = json.loads(saved)
    assert value['entries'][0]['review']['number']['value'] == '52342'
    assert value['entries'][0]['physical_pages'] == [1, 2]


def test_saved_reading_rechecks_changed_kkbs_for_free_without_mutating_reading():
    data, cache = saved_cache()
    bundle = load_readings(cache, data, 2)
    before = bundle.model_dump()
    with patch('app.analyze', side_effect=AssertionError('No API')), \
         patch('bulk_review.render_pages', side_effect=AssertionError('No image reread')):
        result = recheck_readings(bundle, [record(52342)])
        mismatch = recheck_readings(bundle, [replace(record(52342), member='Başka Vekil'), record(52343)])
    assert result['api_requests'] == 0 and result['is_replay'] and result['is_test']
    assert not result['complete'] and result['matched'] == 1 and not result['issues']
    assert mismatch['source_id'] != result['source_id']
    assert any(i['field'] == 'KKBS · Milletvekili' and i['status'] == 'uyari' for i in mismatch['issues'])
    assert bundle.model_dump() == before


def test_cache_is_tied_to_exact_pdf_but_not_to_old_kkbs_or_rule_version():
    data, cache = saved_cache()
    with pytest.raises(bulk.TableError, match='bu PDF’ye ait değil'):
        load_readings(cache, pdf(3), 3)
    value = json.loads(cache)
    value['version'] = 'older-validation-version'
    bundle = load_readings(json.dumps(value).encode(), data, 2)
    result = recheck_readings(bundle, [record(52342)])
    assert result['reading_version'] == 'older-validation-version'
    assert result['version'] == bulk.BULK_VERSION and result['api_requests'] == 0


@pytest.mark.parametrize('damage', ['format', 'duplicate', 'physical', 'local_page', 'pages', 'stamp', 'too_many', 'image'])
def test_malformed_or_unrelated_saved_readings_are_rejected_without_api(damage):
    data, cache = saved_cache()
    value = json.loads(cache)
    entry = value['entries'][0]
    if damage == 'format': value = {'issues': []}
    if damage == 'duplicate': value['entries'].append(entry)
    if damage == 'physical': entry['physical_pages'] = [1, 3]
    if damage == 'local_page': entry['review']['pages'][1]['page'] = 3
    if damage == 'pages': entry['pages'].pop()
    if damage == 'stamp': entry['pages'][0]['stamp_ocr'][0]['value'] = '52?42'
    if damage == 'too_many': value['entries'] = [entry] * 201
    if damage == 'image': entry['pages'][0]['image'] = 'must-not-be-in-cache'
    with pytest.raises(bulk.TableError):
        load_readings(json.dumps(value).encode(), data, 2)


def test_old_summary_report_does_not_trigger_paid_reread_or_pretend_to_contain_raw_fields():
    with pytest.raises(bulk.TableError, match='Eski sonuç raporları'):
        load_readings(b'{"issues": [], "complete": true}', pdf(1), 1)
