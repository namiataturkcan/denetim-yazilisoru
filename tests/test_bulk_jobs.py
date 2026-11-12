import threading

import pytest

import bulk_jobs as jobs
from bulk_review import IndexedPage, TableError
from test_bulk_review import record


def patch_pipeline(monkeypatch):
    calls = {'index': [], 'review': []}
    monkeypatch.setattr(jobs, 'render_pages', lambda data, numbers: numbers)
    async def index(pages, numbers, **kw):
        calls['index'].append(numbers)
        return [IndexedPage(page=n,kind='start',explanation='') for n in numbers]
    async def review(data, unit, records, **kw):
        calls['review'].append(unit['pages'])
        return {'number':50000+unit['pages'][0]-1,'pages':unit['pages'],'matched':True,'issues':[],'failed':False}
    monkeypatch.setattr(jobs, 'index_pages', index)
    monkeypatch.setattr(jobs, 'review_unit', review)
    return calls, review


def wait(job):
    job._thread.join(timeout=5)
    assert not job._thread.is_alive()


def test_completed_work_survives_pause_and_resume_without_repeated_api_calls(monkeypatch):
    calls, original = patch_pipeline(monkeypatch)
    job = jobs.BulkJob(b'pdf', 3, [record(i) for i in range(50000,50003)], 'test', 'digest')
    async def review(*args, **kw):
        result = await original(*args, **kw)
        if len(calls['review']) == 1:
            job.stop()
        return result
    monkeypatch.setattr(jobs, 'review_unit', review)
    job.start('test-only'); wait(job)
    assert job.snapshot()['state'] == 'paused' and job.snapshot()['processed'] == 1
    job.start('test-only'); wait(job)
    assert calls['index'] == [[1,2,3]]
    assert calls['review'] == [[1],[2],[3]]
    assert job.snapshot()['state'] == 'complete' and not job.snapshot()['issues']


def test_failed_proposal_remains_suspicious_and_only_failed_proposal_is_retried(monkeypatch):
    calls, original = patch_pipeline(monkeypatch)
    async def review(data, unit, records, **kw):
        if unit['pages'] == [2]:
            raise ValueError('sensitive upstream error should not leak')
        return await original(data, unit, records, **kw)
    monkeypatch.setattr(jobs, 'review_unit', review)
    job=jobs.BulkJob(b'pdf',2,[record(),record(50001)],'test','digest')
    job.start('test'); wait(job)
    assert job.snapshot()['failed'] == 1
    assert 'sensitive' not in str(job.snapshot())
    monkeypatch.setattr(jobs, 'review_unit', original)
    job.start('test',retry_failed=True); wait(job)
    assert calls['review'] == [[1],[2]]
    assert not job.snapshot()['issues']


def test_index_failure_resumes_only_remaining_windows(monkeypatch):
    calls, original = patch_pipeline(monkeypatch)
    index_fn = jobs.index_pages
    async def index(pages,numbers,**kw):
        if numbers[0] == 5:
            raise TableError('Okuma kesildi')
        return await index_fn(pages,numbers,**kw)
    monkeypatch.setattr(jobs,'index_pages',index)
    job=jobs.BulkJob(b'pdf',5,[record(i) for i in range(50000,50005)],'test','digest')
    job.start('test'); wait(job)
    assert job.snapshot()['indexed_pages'] == 4 and job.snapshot()['processed'] == 0
    monkeypatch.setattr(jobs,'index_pages',index_fn)
    job.start('test'); wait(job)
    assert calls['index'] == [[1,2,3,4],[5]]
    assert job.snapshot()['processed'] == 5


def test_parallel_users_are_bounded_and_snapshots_are_isolated(monkeypatch):
    patch_pipeline(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    async def blocking(pages,numbers,**kw):
        entered.set()
        assert release.wait(timeout=5)
        return [IndexedPage(page=1,kind='start',explanation='')]
    monkeypatch.setattr(jobs,'index_pages',blocking)
    first=jobs.BulkJob(b'one',1,[record()],'test','one')
    second=jobs.BulkJob(b'two',1,[record(50001)],'test','two')
    first.start('test')
    try:
        assert entered.wait(timeout=3)
        with pytest.raises(TableError, match='Başka bir toplu'):
            second.start('test')
        assert second.snapshot()['processed'] == 0
        first.stop()
    finally:
        release.set(); wait(first)
    assert not jobs._bulk_gate.locked()
    assert first.snapshot()['source_id'] != second.snapshot()['source_id']


def test_abandoned_session_pauses_before_spending_more_api_credits(monkeypatch):
    calls, _ = patch_pipeline(monkeypatch)
    job=jobs.BulkJob(b'pdf',1,[record()],'test','digest')
    job.last_seen = -1000
    import asyncio
    asyncio.run(job._work('test'))
    assert not calls['index'] and not calls['review']


def test_two_hundred_proposals_are_processed_once_in_bounded_windows(monkeypatch):
    calls, _ = patch_pipeline(monkeypatch)
    job=jobs.BulkJob(b'pdf',200,[record(i) for i in range(50000,50200)],'test','digest')
    job.start('test'); wait(job)
    snapshot=job.snapshot()
    assert snapshot['state'] == 'complete' and snapshot['processed'] == 200
    assert len(calls['index']) == 50 and all(len(window) == 4 for window in calls['index'])
    assert len(calls['review']) == 200 and not snapshot['issues']


def test_authentication_failure_pauses_batch_and_never_marks_remaining_proposals_as_passed(monkeypatch):
    import httpx
    from openai import AuthenticationError
    patch_pipeline(monkeypatch)
    async def rejected(*args, **kwargs):
        raise AuthenticationError('secret error body', response=httpx.Response(401, request=httpx.Request('POST','https://api.openai.com/v1/responses')), body=None)
    monkeypatch.setattr(jobs, 'review_unit', rejected)
    job=jobs.BulkJob(b'pdf',2,[record(),record(50001)],'test','digest')
    job.start('test'); wait(job)
    snapshot=job.snapshot()
    assert snapshot['state'] == 'paused' and snapshot['processed'] == 0
    assert snapshot['message'] == 'API anahtarı kabul edilmedi.'
    assert 'secret' not in str(snapshot)
