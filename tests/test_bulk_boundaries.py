import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI

import app
import bulk_review as bulk
import bulk_jobs as jobs
from test_bulk_jobs import wait
from test_bulk_review import reading, record


def page(number, kind):
    return bulk.IndexedPage(page=number, kind=kind, explanation='Görüntüdeki açılış/devam bloğu')


def test_one_three_and_six_page_proposals_remain_intact_across_windows_and_resume(monkeypatch):
    calls, reviewed = [], []
    kinds = ['start', 'start', 'continuation', 'continuation', 'start',
             'continuation', 'continuation', 'continuation', 'continuation', 'continuation']
    monkeypatch.setattr(jobs, 'render_pages', lambda data, numbers: [{'physical': n} for n in numbers])
    job = jobs.BulkJob(b'pdf', 10, [record(n) for n in range(50000, 50003)], 'test', 'digest')

    async def index(pages, numbers, **kw):
        calls.append((numbers, [n for n, _ in kw['context']]))
        assert [p['physical'] for p in pages] == numbers
        assert all(n == p['physical'] and n < numbers[0] for n, p in kw['context'])
        if numbers[0] == 5:
            job.stop()  # Resume must reconstruct the same long-document context.
        return [page(n, kinds[n-1]) for n in numbers]

    async def review(data, unit, records, **kw):
        reviewed.append(unit['pages'])
        return {'number': 49999+len(reviewed), 'pages': unit['pages'], 'issues': [], 'matched': True, 'failed': False}

    monkeypatch.setattr(jobs, 'index_pages', index)
    monkeypatch.setattr(jobs, 'review_unit', review)
    job.start('test-only'); wait(job)
    assert job.snapshot()['state'] == 'paused' and not reviewed
    job.start('test-only'); wait(job)
    assert calls == [([1, 2, 3, 4], []), ([5, 6, 7, 8], [2, 4]), ([9, 10], [5, 8])]
    assert reviewed == [[1], [2, 3, 4], [5, 6, 7, 8, 9, 10]]
    assert job.snapshot()['complete']


def test_unknown_boundary_stops_old_opening_being_used_as_context():
    assert bulk.index_context_numbers([page(1, 'start'), page(2, 'uncertain'), page(3, 'continuation')]) == [3]
    assert bulk.index_context_numbers([page(1, 'start')]) == [1]


def test_index_reads_context_without_reclassifying_it_or_sending_ocr(monkeypatch):
    captured = []
    returned = [page(73, 'continuation'), page(74, 'continuation'), page(75, 'continuation'), page(76, 'start')]

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={'id': 'resp_test', 'object': 'response', 'created_at': 0,
            'model': 'gpt-4.1', 'status': 'completed', 'output': [{'id': 'msg_test', 'type': 'message',
            'role': 'assistant', 'status': 'completed', 'content': [{'type': 'output_text',
            'text': bulk.PageIndex(pages=returned).model_dump_json(), 'annotations': []}]}]})

    monkeypatch.setattr(bulk, 'AsyncOpenAI', lambda **kw: AsyncOpenAI(**kw,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    kwargs = dict(credential='test-only', model='gpt-4.1',
                  context=[(72, {'image': 'opening-image', 'ocr': 'PRIVATE_CONTEXT_OCR'})])
    result = asyncio.run(bulk.index_pages([{'image': f'page-{n}', 'ocr': 'PRIVATE_OCR'} for n in range(73, 77)],
                                         [73, 74, 75, 76], **kwargs))
    assert [p.kind for p in result] == ['continuation'] * 3 + ['start']
    content = captured[0]['input'][0]['content']
    assert len([c for c in content if c['type'] == 'input_image']) == 5
    assert 'Yalnız bağlam' in content[0]['text'] and '72' in content[0]['text']
    assert 'PRIVATE' not in json.dumps(captured)
    returned.insert(0, page(72, 'start'))
    with pytest.raises(bulk.TableError, match='eksik'):
        asyncio.run(bulk.index_pages([{'image': 'x'}] * 4, [73, 74, 75, 76], **kwargs))
    assert not app.analysis_gate.locked()


@pytest.mark.parametrize('stamp,should_warn', [('50000', False), ('50001', True), ('', False)])
def test_missed_start_with_different_stamp_cannot_be_approved_as_one_proposal(monkeypatch, stamp, should_warn):
    raw, pages = reading('50000')
    raw.pages.append(app.PageReading(page=2, text=stamp + '\nSoruların devamı', uncertainties=[]))
    raw.continuation_numbers = [bulk.ObservedField(value=stamp, page=2, quote=stamp, uncertain=False)]
    pages[0]['stamp_ocr'] = [{'value': '50000'}]
    pages.append({'ocr': 'Soruların devamı', 'image': 'unused',
                  'stamp_ocr': [{'value': stamp}] if stamp else []})
    monkeypatch.setattr(bulk, 'render_pages', lambda *a, **kw: pages)
    async def analyze(*a, **kw): return raw
    monkeypatch.setattr(app, 'analyze', analyze)
    result = asyncio.run(bulk.review_unit(b'pdf', {'pages': [72, 73], 'boundary_warnings': []},
                                         [record()], credential='test-only', model='test'))
    warnings = [i for i in result['issues'] if i['field'] == 'Sayfa eşleştirme']
    assert bool(warnings) == should_warn
    assert jobs.matching_coverage([record()], [result], [])['matching_complete'] != should_warn
