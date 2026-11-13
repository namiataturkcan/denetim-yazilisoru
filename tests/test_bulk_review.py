import asyncio
import io
import json
from dataclasses import replace

import httpx
import pymupdf
import pytest
from fastapi import HTTPException
from openai import AsyncOpenAI

import app
import bulk_review as bulk
from test_app import pdf
from test_incoming_papers import workbook


HEADER = ['Esas No', 'Soru Sahibi', 'Soru Sahibi İli', 'Muhatap Unvanı', 'Soru Muhatabı', 'Donem Adı', 'Özet', 'Genel Evrak Tarihi']
ROW = ['7/50000', 'Test Vekil', 'Kocaeli', 'Adalet Bakanı', 'Akın GÜRLEK', '28', 'Bu alan karşılaştırılmaz', '01.01.2020']


def record(number=50000):
    return bulk.KKBSRecord(number, 'Test Vekil', 'Kocaeli', 'Adalet Bakanı', 'Akın GÜRLEK', '28. Dönem', 2)


def reading(number='7/50000', page=1):
    text = f'''Türkiye Büyük Millet Meclisi Başkanlığına
Esas No: {number}
Sorularımın Adalet Bakanı Akın GÜRLEK tarafından yazılı olarak cevaplandırılmasını arz ederim.
Kamu personeli alımları hakkında sorular.
Test Vekil
Kocaeli Milletvekili'''
    quote = 'Test Vekil\nKocaeli Milletvekili'
    fields = dict(page=1, uncertain=False)
    review = bulk.BulkReading(
        pages=[app.PageReading(page=1, text=text, uncertainties=[])],
        checks=[app.Check(kind=k, status='uygun', page=1, quote=q, explanation='Uygun') for k, q in zip(app.CHECK_ORDER,
            ['Türkiye Büyük Millet Meclisi Başkanlığına', 'Test Vekil', quote,
             'Adalet Bakanı Akın GÜRLEK', 'arz ederim', 'Kamu personeli alımları hakkında sorular.'])],
        summary='', signatories=[app.Signatory(page=1, name='Test Vekil', constituency='Kocaeli', evidence=quote)],
        number=bulk.ObservedField(value=number, quote=f'Esas No: {number}', **fields),
        recipient_title=bulk.ObservedField(value='Adalet Bakanı', quote='Adalet Bakanı Akın GÜRLEK', **fields),
        recipient_name=bulk.ObservedField(value='Akın GÜRLEK', quote='Adalet Bakanı Akın GÜRLEK', **fields))
    return review, [{'ocr': text, 'image': 'unused'}]


def test_kkbs_reads_only_requested_fields_and_preserves_number_and_source():
    records, invalid = bulk.read_kkbs(workbook([HEADER, ROW]), 'Rapor')
    assert records == [record()]
    assert not invalid
    assert not hasattr(records[0], 'summary') and not hasattr(records[0], 'date')
    assert '01.01.2020' not in repr(records)


def test_kkbs_header_errors_invalid_numbers_and_scope_guards():
    with pytest.raises(bulk.TableError, match='Soru Muhatabı'):
        bulk.read_kkbs(workbook([HEADER[:4], ROW[:4]]), 'Rapor')
    records, invalid = bulk.read_kkbs(workbook([HEADER, ROW, ['???', *ROW[1:]]]), 'Rapor')
    assert invalid == [3]
    assert bulk.select_records(records * 2) == records
    conflict = replace(records[0], province='İstanbul', source_row=3)
    assert len(bulk.select_records([*records, conflict])) == 2
    with pytest.raises(bulk.TableError, match='farklı dönem'):
        bulk.select_records([record(), replace(record(50001), term='27. Dönem')])
    many = [record(i) for i in range(1, 202)]
    with pytest.raises(bulk.TableError, match='200'):
        bulk.select_records(many)
    assert len(bulk.select_records(many, 1, 200)) == 200
    for first, last in [(1, None), (5, 1), (300, 400)]:
        with pytest.raises(bulk.TableError):
            bulk.select_records(many, first, last)


def test_bulk_pdf_accepts_large_page_count_but_renders_only_requested_pages():
    data = pdf(201)
    assert bulk.inspect_pdf(data) == 201
    pages = bulk.render_pages(data, [1, 201])
    assert len(pages) == 2 and 'Reference text' in pages[1]['ocr']
    with pytest.raises(bulk.TableError):
        bulk.inspect_pdf(b'bad file')
    with pytest.raises(bulk.TableError):
        bulk.render_pages(data, [0])
    with pymupdf.open() as doc:
        doc.new_page()
        locked = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='secret')
    with pytest.raises(bulk.TableError, match='Şifreli'):
        bulk.inspect_pdf(locked)


def test_multpage_boundaries_across_windows_and_uncertain_pages_never_disappear():
    kinds = ['start', 'continuation', 'blank', 'continuation', 'continuation', 'start', 'uncertain', 'continuation', 'start']
    index = [bulk.IndexedPage(page=i, kind=kind, explanation='Sınır belirsiz') for i, kind in enumerate(kinds, 1)]
    units, unknown = bulk.make_units(index)
    assert [u['pages'] for u in units] == [[1, 2, 4, 5], [6], [9]]
    assert [f['pages'] for f in unknown] == [[7], [8]]
    assert units[1]['boundary_warnings']


def test_all_matching_has_no_checklist_rows_and_never_compares_summary_or_date():
    review, pages = reading()
    result = bulk.compare_proposal(review, pages, [23], [record()])
    assert result['matched'] and not result['issues']
    assert result['pages'] == [23]
    assert 'summary' not in result
    assert bulk.reconciliation([record()], [result], [], True) == []


@pytest.mark.parametrize('failure,fragment', [
    ('uncertain', 'belirsiz olarak'), ('quote', 'sayfa metninde'),
    ('value', 'dayanak alıntıda'), ('ocr', 'PDF/OCR metni uyuşmuyor')])
def test_number_rejection_preserves_actual_reading_and_specific_cause(failure, fragment):
    review, pages = reading()
    if failure == 'uncertain':
        review.number.uncertain = True
    elif failure == 'quote':
        review.number.quote = 'Kaynak metinde olmayan alıntı'
    elif failure == 'value':
        review.number.value = '7/50001'
    else:
        pages[0]['ocr'] = pages[0]['ocr'].replace('50000', '50001')
    result = bulk.compare_proposal(review, pages, [180, 181][:len(pages)], [record()])
    finding = next(i for i in result['issues'] if i['field'] == 'Esas numarası')
    assert not result['matched'] and result['number'] is None
    assert fragment in finding['explanation']
    assert 'karşılaştırılmadı' in finding['explanation']
    assert finding['actual'] == review.number.value
    assert finding['reading_evidence']['quote'] == review.number.quote
    assert finding['reading_evidence']['value'] == review.number.value
    assert finding['reading_evidence']['rejection_reason']
    assert not any(i['field'] == 'KKBS · Milletvekili' for i in result['issues'])


@pytest.mark.parametrize('field,value,label', [('member','Başka Vekil','Milletvekili'),
    ('province','İstanbul','Seçim çevresi'), ('title','Sağlık Bakanı','Muhatap bakanlık'),
    ('minister','Başka Bakan','Muhatap bakan')])
def test_kkbs_mismatches_are_errors_with_absolute_pdf_page_and_both_values(field, value, label):
    review, pages = reading()
    result = bulk.compare_proposal(review, pages, [17], [replace(record(), **{field: value})])
    found = next(i for i in result['issues'] if i['field'] == 'KKBS · ' + label)
    assert found['status'] == 'uyari' and found['pages'] == [17]
    assert found['expected'] == value and found['actual']


def test_current_minister_rules_still_apply_even_when_kkbs_and_pdf_agree_on_old_name():
    review, pages = reading()
    text = review.model_dump_json().replace('Akın GÜRLEK', 'Yılmaz TUNÇ')
    review = bulk.BulkReading.model_validate_json(text)
    pages[0]['ocr'] = review.pages[0].text
    result = bulk.compare_proposal(review, pages, [1], [replace(record(), minister='Yılmaz TUNÇ')])
    assert any(i['field'] == 'Şekil · Muhatap' and i['status'] == 'uyari' for i in result['issues'])


def test_unreadable_number_uses_sequence_as_candidate_only_not_as_verified_kkbs_match():
    review, pages = reading()
    review.number.uncertain = True
    result = bulk.compare_proposal(review, pages, [9], [record()], hint=50000)
    assert result['number'] is None and not result['matched']
    assert result['issues'][0]['inferred'] and result['issues'][0]['status'] == 'belirsiz'
    assert not any(f['field'].startswith('KKBS ·') for f in result['issues'])
    exported = bulk.issue_rows(result['issues'])
    assert exported[0]['Esas No'] == '7/50000 (sıra adayı)'


def test_number_ocr_conflict_and_invented_field_evidence_are_not_approved():
    review, pages = reading()
    pages[0]['ocr'] = pages[0]['ocr'].replace('7/50000', '7/50001')
    assert not bulk.compare_proposal(review, pages, [1], [record()])['matched']
    review, pages = reading()
    review.recipient_name.quote = 'Metinde bulunmayan alıntı'
    result = bulk.compare_proposal(review, pages, [5], [record()])
    assert any(i['field'] == 'KKBS · Muhatap bakan' and i['status'] == 'belirsiz' for i in result['issues'])


def test_conflicting_duplicates_blank_fields_out_of_scope_and_missing_scan():
    review, pages = reading()
    result = bulk.compare_proposal(review, pages, [1], [record(), replace(record(), province='İstanbul')])
    assert not result['matched'] and result['issues'][0]['status'] == 'belirsiz'
    result = bulk.compare_proposal(review, pages, [1], [replace(record(), minister='')])
    assert any(i['field'] == 'KKBS · Muhatap bakan' and i['status'] == 'belirsiz' for i in result['issues'])
    result = bulk.compare_proposal(review, pages, [1], [record(50001)])
    assert result['issues'][0]['status'] == 'uyari'
    duplicate = {**result, 'pages': [3]}
    completed = bulk.reconciliation([record(50001)], [result, duplicate], [], True)
    assert any(f['field'] == 'Yinelenen önerge' and f['pages'] == [1, 3] for f in completed)
    assert any(f['number'] == 50001 and f['field'] == 'PDF eşleştirme' for f in completed)
    assert not any(f['field'] == 'PDF eşleştirme' for f in bulk.reconciliation([record(50001)], [result], [], False))


def test_csv_protects_formulas_and_includes_only_issue_rows():
    finding = bulk.issue(50000, [10, 11], 'uyari', 'KKBS', 'Fark', '=formula', '@value')
    text = bulk.issues_csv([finding]).decode('utf-8-sig')
    assert "'=formula" in text and "'@value" in text and '10, 11' in text
    assert len(text.splitlines()) == 2


def test_reversed_number_reading_is_suspicious_even_if_both_records_exist():
    results = [{'number': n, 'pages': [p], 'issues': [], 'matched': True, 'failed': False}
               for n, p in [(50001, 1), (50000, 2)]]
    findings = bulk.reconciliation([record(), record(50001)], results, [], True)
    assert len(findings) == 1
    assert findings[0]['field'] == 'Esas numarası sırası' and findings[0]['pages'] == [2]


def test_index_api_requires_exact_page_coverage_and_keeps_documents_untrusted(monkeypatch):
    captured = []
    def respond(request):
        body = json.loads(request.content)
        captured.append(body)
        return httpx.Response(200, json={'id':'resp_test','object':'response','created_at':0,
            'model':'gpt-4.1','status':'completed','output':[{'id':'msg_test','type':'message','role':'assistant','status':'completed',
            'content':[{'type':'output_text','text':bulk.PageIndex(pages=[bulk.IndexedPage(page=7,kind='start',explanation='')]).model_dump_json(),'annotations':[]}]}]})
    monkeypatch.setattr(bulk, 'AsyncOpenAI', lambda **kw: AsyncOpenAI(**kw, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    result = asyncio.run(bulk.index_pages([{'image':'image-only','ocr':'SECRET_OCR'}], [7], credential='test-only', model='gpt-4.1'))
    assert result[0].page == 7 and captured[0]['store'] is False
    assert 'SECRET_OCR' not in json.dumps(captured)
    with pytest.raises(bulk.TableError, match='eksik'):
        asyncio.run(bulk.index_pages([{'image':'test'}], [8], credential='test-only', model='gpt-4.1'))
    assert not app.analysis_gate.locked()
