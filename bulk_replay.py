"""Revalidate saved visual readings locally; this module never calls the API."""
import hashlib
import json
from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bulk_jobs import matching_coverage
from bulk_review import (BULK_VERSION, MAX_BULK_PAGES, MAX_PROPOSALS, BulkReading, TableError,
                         compare_proposal, coverage_notes, reconciliation, stamp_number)

MAX_CACHE_MB = 32


class SavedPage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ocr: str = Field(max_length=80000)
    ocr_source: str = Field(default='none', max_length=40)
    ocr_original: str = Field(default='', max_length=80000)
    stamp_ocr: list[dict] = Field(default_factory=list, max_length=50)


class SavedReading(BaseModel):
    model_config = ConfigDict(extra='forbid')
    physical_pages: list[int] = Field(min_length=1, max_length=10)
    pages: list[SavedPage] = Field(min_length=1, max_length=10)
    review: BulkReading
    boundary_warnings: list[str] = Field(default_factory=list, max_length=20)


class SavedReadings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    format: Literal['onerge-readings-v1']
    version: str = Field(max_length=150)
    model: str = Field(max_length=150)
    pdf_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    original_page_count: int = Field(ge=1, le=MAX_BULK_PAGES)
    entries: list[SavedReading] = Field(min_length=1, max_length=MAX_PROPOSALS)


def load_readings(data, pdf_data, page_count):
    if len(data) > MAX_CACHE_MB * 1024 * 1024:
        raise TableError('Okuma kaydı en fazla 32 MB olabilir.')
    try:
        value = json.loads(data)
        if not isinstance(value, dict) or value.get('format') != 'onerge-readings-v1':
            raise TableError('Bu dosya bir okuma kaydı değil. Eski sonuç raporları ham okumayı içermez; '
                             'yeni bir denemeden sonra “Okumayı kaydet” dosyasını indirin.')
        bundle = SavedReadings.model_validate(value)
        used = set()
        for entry in bundle.entries:
            physical = entry.physical_pages
            local = set(range(1, len(physical)+1))
            if (physical != sorted(set(physical)) or used.intersection(physical)
                    or min(physical) < 1 or max(physical) > page_count
                    or len(entry.pages) != len(physical) or len(entry.review.pages) != len(physical)
                    or {p.page for p in entry.review.pages} != local
                    or any(len(p.text) > 80000 for p in entry.review.pages)):
                raise ValueError('Invalid page coverage')
            used.update(physical)
            for page in entry.pages:
                for stamp in page.stamp_ocr:
                    stamp_number(stamp['value'])
    except TableError:
        raise
    except (ValidationError, ValueError, KeyError, TypeError, RecursionError):
        raise TableError('Okuma kaydı geçersiz veya eksik; özgün kayıt dosyasını yükleyin.') from None
    if bundle.pdf_sha256 != hashlib.sha256(pdf_data).hexdigest() or bundle.original_page_count != page_count:
        raise TableError('Okuma kaydı bu PDF’ye ait değil. Kaydın oluşturulduğu PDF’nin aynısını yükleyin.')
    return bundle


def recheck_readings(bundle, records):
    results = []
    try:
        for entry in bundle.entries:
            results.append(compare_proposal(entry.review, [p.model_dump() for p in entry.pages],
                                            entry.physical_pages, records, entry.boundary_warnings))
    except Exception:
        raise TableError('Kayıtlı okuma güncel kontroller için eksik veya geçersiz. '
                         'İlgili önergeyi küçük örnek modunda yeniden okuyun; ücretli istek otomatik başlatılmadı.') from None
    physical = sorted(p for entry in bundle.entries for p in entry.physical_pages)
    source_id = hashlib.sha256(json.dumps([bundle.pdf_sha256, [asdict(r) for r in records], BULK_VERSION],
                                         sort_keys=True).encode()).hexdigest()
    return {'version': BULK_VERSION, 'reading_version': bundle.version, 'reading_model': bundle.model,
            'source_id': source_id, 'reading_pdf_sha256': bundle.pdf_sha256,
            'state': 'complete', 'phase': 'Kayıtlı okumayı yeniden kontrol',
            'message': '', 'is_test': True, 'is_replay': True, 'api_requests': 0,
            'tested_pages': physical, 'original_page_count': bundle.original_page_count,
            'page_count': len(physical), 'indexed_pages': len(physical), 'proposal_count': len(results),
            'processed': len(results), 'failed': 0, **matching_coverage(records, results, []),
            'processing_complete': True, 'complete': False, 'coverage_notes': coverage_notes(records),
            'issues': reconciliation(records, results, [], False)}
