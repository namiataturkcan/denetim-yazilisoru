"""Session-owned, resumable bulk work. Background threads never call Streamlit."""
import asyncio
from collections import defaultdict
from copy import deepcopy
from threading import Event, Lock, RLock, Thread
from time import monotonic

from fastapi import HTTPException
from openai import APIConnectionError, APIStatusError, APITimeoutError

from bulk_review import (BULK_VERSION, INDEX_WINDOW, MAX_PROPOSALS, TableError, coverage_notes, index_pages, issue,
                         make_units, reconciliation, render_pages, review_unit)

# Bound RAM and API load across users; each proposal also shares the single-review API gate.
_bulk_gate = Lock()


def failure_message(exc):
    if isinstance(exc, APIStatusError):
        return {401: 'API anahtarı kabul edilmedi.', 403: 'API erişimine izin verilmedi.',
                429: 'API kullanım sınırına ulaşıldı; bakiye veya kotayı kontrol edip devam edin.',
                404: 'Seçilen model kullanılamıyor.'}.get(exc.status_code, 'Analiz servisi isteği tamamlayamadı.')
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return 'Analiz servisine ulaşılamadı veya süre doldu. Tamamlanan sonuçlar korundu.'
    if isinstance(exc, (TableError, HTTPException)):
        return str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
    return 'Bu bölümün analizi tamamlanamadı. Tamamlanan sonuçlar korundu; yeniden deneyebilirsiniz.'


def matching_coverage(records, results, unassigned):
    """A complete comparison needs one unambiguous document per KKBS record."""
    expected = {r.number for r in records}
    grouped = defaultdict(list)
    for result in results:
        grouped[result['number']].append(result)
    verified = set()
    for number, documents in grouped.items():
        if number not in expected or len(documents) != 1:
            continue
        result = documents[0]
        if (result['matched'] and not result['failed']
                and not any(i['field'] in ('Sayfa eşleştirme', 'Esas numarası') for i in result['issues'])):
            verified.add(number)
    unmatched = len(results) - len(verified)
    return {'matched': len(verified), 'expected_count': len(expected),
            'unmatched_documents': unmatched,
            'unmatched_records': sorted(expected - verified),
            'matching_complete': bool(expected) and verified == expected and not unmatched and not unassigned}


class BulkJob:
    def __init__(self, data, page_count, records, model, source_id):
        self.data = data
        self.page_count = page_count
        self.records = list(records)
        self.model = model
        self.source_id = source_id
        self.version = BULK_VERSION
        self._lock = RLock()
        self._stop = Event()
        self._thread = None
        self.last_seen = monotonic()
        self.state = 'ready'
        self.phase = 'Sayfa sınırları'
        self.message = ''
        self.index = []
        self.units = None
        self.unassigned = []
        self.results = {}

    @property
    def running(self):
        with self._lock:
            return self.state in ('running', 'stopping')

    def stop(self):
        with self._lock:
            self._stop.set()
            if self.state == 'running':
                self.state = 'stopping'
                self.message = 'Devam eden istek tamamlandıktan sonra duraklatılacak.'

    def _should_stop(self):
        with self._lock:
            return self._stop.is_set() or monotonic() - self.last_seen > 90

    def start(self, credential, *, retry_failed=False):
        with self._lock:
            if self.running:
                return
            if not credential:
                raise TableError('Analiz bağlantısı henüz yapılandırılmadı.')
            if self.version != BULK_VERSION:
                raise TableError('İnceleme kodu değişti; dosyalarla yeni bir toplu inceleme başlatın.')
            if not _bulk_gate.acquire(blocking=False):
                raise TableError('Başka bir toplu inceleme sürüyor. Tamamlandıktan sonra tekrar deneyin.')
            if retry_failed:
                self.results = {k: v for k, v in self.results.items() if not v['failed']}
            self.state, self.message = 'running', ''
            self.last_seen = monotonic()
            self._stop.clear()
            self._thread = Thread(target=self._run, args=(credential,), daemon=True)
            try:
                self._thread.start()
            except BaseException:
                self.state = 'paused'
                _bulk_gate.release()
                raise

    def _run(self, credential):
        try:
            asyncio.run(self._work(credential))
        except Exception as exc:
            with self._lock:
                self.state, self.message = 'paused', failure_message(exc)
        finally:
            with self._lock:
                if self.state in ('running', 'stopping'):
                    self.state = 'paused'
                    self.message = 'İnceleme duraklatıldı. Tamamlanan kayıtlar korunuyor.'
            _bulk_gate.release()

    async def _work(self, credential):
        while len(self.index) < self.page_count:
            if self._should_stop():
                return
            start = len(self.index) + 1
            numbers = list(range(start, min(start + INDEX_WINDOW, self.page_count + 1)))
            pages = render_pages(self.data, numbers)
            result = await index_pages(pages, numbers, credential=credential, model=self.model)
            del pages
            with self._lock:
                self.index.extend(result)
        with self._lock:
            if self.units is None:
                self.units, self.unassigned = make_units(self.index)
            if len(self.units) > MAX_PROPOSALS:
                raise TableError('PDF’de 200’den fazla önerge başlangıcı bulundu; taramayı daha küçük gruplara ayırın.')
            self.phase = 'Şekil ve KKBS karşılaştırması'
        expected = sorted({r.number for r in self.records})
        for index, unit in enumerate(self.units):
            if index in self.results:
                continue
            if self._should_stop():
                return
            # Sequence is only a labelled candidate for unreadable stamps, never a verified match.
            hint = expected[index] if len(expected) == len(self.units) else None
            try:
                result = await review_unit(self.data, unit, self.records, credential=credential, model=self.model, hint=hint)
            except (APIStatusError, APIConnectionError, APITimeoutError) as exc:
                raise exc  # Pause instead of burning credits on every remaining proposal.
            except HTTPException as exc:
                if exc.status_code == 429:
                    raise
                result = self._failed(unit, hint, exc)
            except Exception as exc:
                result = self._failed(unit, hint, exc)
            with self._lock:
                self.results[index] = result
        with self._lock:
            self.state, self.message = 'complete', ''

    @staticmethod
    def _failed(unit, hint, exc):
        return {'number': None, 'pages': list(unit['pages']), 'matched': False, 'failed': True,
                'issues': [issue(hint, unit['pages'], 'belirsiz', 'Analiz tamamlanamadı',
                                 failure_message(exc), inferred=hint is not None)]}

    def snapshot(self, *, touch=True):
        with self._lock:
            if touch:
                self.last_seen = monotonic()
            results = list(self.results.values())
            coverage = matching_coverage(self.records, results, self.unassigned)
            processing_complete = self.state == 'complete' and not any(r['failed'] for r in results)
            return {'version': self.version, 'source_id': self.source_id, 'state': self.state,
                    'phase': self.phase, 'message': self.message,
                    'page_count': self.page_count, 'indexed_pages': len(self.index),
                    'proposal_count': len(self.units) if self.units is not None else None,
                    'processed': len(results), 'failed': sum(r['failed'] for r in results),
                    **coverage, 'processing_complete': processing_complete,
                    'complete': processing_complete and coverage['matching_complete'],
                    'coverage_notes': coverage_notes(self.records),
                    'issues': deepcopy(reconciliation(self.records, results, self.unassigned, self.state == 'complete'))}
