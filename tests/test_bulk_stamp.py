"""Keep original positioned stamp evidence independent of body OCR refreshes."""
import asyncio
import base64
from dataclasses import replace

import pymupdf
import pytest

import app
import bulk_review as bulk
from test_bulk_review import reading, record


def positioned(value='50000'):
    return [{'value': value, 'rect': [480, 40, 550, 70]}]


def test_body_ocr_digit_corruption_does_not_discard_original_stamp_or_member_mismatch():
    review, pages = reading()
    pages[0]['ocr'] = pages[0]['ocr'].replace('50000', '50009')
    pages[0]['stamp_ocr'] = positioned()
    result = bulk.compare_proposal(review, pages, [180], [replace(record(), member='Başka Vekil')])
    assert result['number'] == 50000 and result['matched']
    finding = next(i for i in result['issues'] if i['field'] == 'KKBS · Milletvekili')
    assert finding['status'] == 'uyari' and finding['pages'] == [180]
    assert finding['expected'] == 'Başka Vekil' and finding['actual'] == 'Ömer Faruk GERGERLİOĞLU'


def test_wrong_row_owner_does_not_make_a_source_backed_constituency_suspicious():
    review, pages = reading()
    records = [replace(record(), member='Başka Vekil'), record(50001)]
    result = bulk.compare_proposal(review, pages, [180], records)
    assert [i['field'] for i in result['issues']] == ['KKBS · Milletvekili']
    assert result['issues'][0]['status'] == 'uyari'
    # Contradictory rows in the group cannot override the independent directory.
    records.append(replace(record(50002), province='Ankara'))
    result = bulk.compare_proposal(review, pages, [180], records)
    assert [i['field'] for i in result['issues']] == ['KKBS · Milletvekili']


def test_source_choice_does_not_pick_the_ocr_that_agrees_with_model_or_kkbs():
    review, pages = reading()
    # Body OCR agrees with both model and KKBS, but the positioned original
    # stamp disagrees. That must remain unresolved, not silently approved.
    pages[0]['stamp_ocr'] = positioned('50001')
    result = bulk.compare_proposal(review, pages, [180], [record()])
    assert result['number'] is None and not result['matched']
    issue = next(i for i in result['issues'] if i['field'] == 'Esas numarası')
    assert 'özgün PDF metniyle uyuşmuyor' in issue['explanation']
    assert issue['reading_evidence']['stamp_ocr'][0]['value'] == '50001'


def test_multiple_original_stamp_numbers_are_not_resolved_using_kkbs():
    review, pages = reading()
    pages[0]['stamp_ocr'] = positioned() + positioned('50001')
    result = bulk.compare_proposal(review, pages, [1], [record()])
    assert not result['matched']
    assert any('birden fazla numara' in i['explanation'] for i in result['issues'])


@pytest.mark.parametrize('value,quote', [('7/50000', '50000'), ('50000', '5 0 0 0 0'),
                                       ('7 / 50 000', 'Esas No: 50000')])
def test_number_format_differences_preserve_digits_without_inventing_evidence(value, quote):
    review, pages = reading()
    review.pages[0].text = review.pages[0].text.replace('Esas No: 7/50000', quote)
    review.number.value, review.number.quote = value, quote
    pages[0]['stamp_ocr'] = positioned()
    result = bulk.compare_proposal(review, pages, [1], [record()])
    assert result['number'] == 50000 and result['matched']


@pytest.mark.parametrize('value', ['8/50000', '50?00', '50O00', '50001', '50000 50001'])
def test_real_number_differences_and_uncertain_digits_are_not_format_normalization(value):
    assert not bulk.number_in_quote(value, '50000')


def test_visual_uncertainty_or_missing_quote_cannot_be_overridden_by_stamp_ocr():
    review, pages = reading()
    pages[0]['stamp_ocr'] = positioned()
    review.number.uncertain = True
    assert not bulk.compare_proposal(review, pages, [1], [record()])['matched']
    review.number.uncertain = False
    review.number.quote = 'Olmayan alıntı'
    assert not bulk.compare_proposal(review, pages, [1], [record()])['matched']


def test_render_extracts_positioned_stamps_without_left_party_numbers_or_body_numbers():
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((60, 50), 'Sayi: 1980000')
        page.insert_text((480, 50), '50832', fontsize=20)
        page.insert_text((480, 110), '2026')
        page.insert_text((480, 400), '50009')
        data = doc.tobytes()
    pages = bulk.render_pages(data, [1], stamp_details=True)
    assert [x['value'] for x in pages[0]['stamp_ocr']] == ['50832']
    pix = pymupdf.Pixmap(base64.b64decode(pages[0]['stamp_image']))
    assert max(pix.width, pix.height) <= 2200
    assert 'stamp_image' not in bulk.render_pages(data, [1])[0]


def test_stamp_closeup_is_sent_as_image_without_ocr_or_expected_values(monkeypatch):
    import httpx
    from openai import AsyncOpenAI
    review, pages = reading()
    pages[0].update(image='full-image', stamp_image='stamp-image', stamp_ocr=positioned('58888'), ocr='PRIVATE_OCR')
    requests = []
    def respond(request):
        import json
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'id':'resp_test', 'object':'response', 'created_at':0,
            'status':'completed', 'model':'test', 'output':[{'id':'msg_test','type':'message','role':'assistant',
            'status':'completed','content':[{'type':'output_text','text':review.model_dump_json(),'annotations':[]}]}]})
    client = AsyncOpenAI(api_key='test-only', http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(app, 'AsyncOpenAI', lambda **kwargs: client)
    monkeypatch.setattr(app, 'fill_missing_ocr', lambda p: None)
    asyncio.run(app.analyze(pages, credential='test-only', model='test', response_format=bulk.BulkReading))
    content = requests[0]['input'][0]['content']
    assert [c['image_url'] for c in content if c['type']=='input_image'] == [
        'data:image/png;base64,full-image', 'data:image/png;base64,stamp-image']
    assert 'PRIVATE_OCR' not in str(content) and '58888' not in str(content)
