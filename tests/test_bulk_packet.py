"""The numbered, macro-free packet template supplied for bulk checking."""
import io
from dataclasses import replace

import openpyxl
import pytest

import bulk_review as bulk
from incoming_papers import sheet_names
from test_bulk_review import HEADER, ROW, reading, record
from test_incoming_papers import workbook


PACKET_HEADER = ['Paket Adı', None, 'Genel Evrak No', 'Önerge Sahibi Özeti', 'Açıklama', 'Kullanici', None, None]


def packet(number='7/50000', text=None):
    if text is None:
        text = "Kocaeli Milletvekili Test Vekil'in, kamu personeli alımlarına ilişkin Adalet Bakanı'ndan yazılı soru önergesi (Başkanlığa geliş tarihi: 01-01-2026)"
    book = openpyxl.Workbook()
    book.active.title = 'Sayfa1'
    book.active.append(['Adalet Bakanı', 'ADALET BAKANLIĞI'])
    ws = book.create_sheet('Veri')
    ws.append(PACKET_HEADER)
    ws.append(['Grup 1', number, 1980000, text, None, 'Kaydı Giren Kullanıcı', 'Eski formül sonucu', 'Yanlış Bakan'])
    ws = book.create_sheet('İlk Çıkış')
    ws.append(['SIRA NO', 'ESAS NO', 'EVRAK KAYIT NO', 'SAHİBİ VE ÖZETİ'])
    ws.append([1, number, 1980000, 'Yazdırma görünümü'])
    data = io.BytesIO()
    book.save(data)
    return data.getvalue()


def test_selects_data_sheet_and_uses_explicit_number_and_metadata_only():
    data = packet()
    assert bulk.default_kkbs_sheet(data, sheet_names(data)) == 'Veri'
    records, invalid = bulk.read_kkbs(data, 'Veri')
    assert not invalid and len(records) == 1
    assert records[0] == replace(record(), minister='', term='', minister_in_source=False)
    assert 'Kullanıcı' not in repr(records) and 'Yanlış Bakan' not in repr(records)
    assert '1980000' not in repr(records)
    assert 'kişi adı yok' in bulk.coverage_notes(records)[0]


@pytest.mark.parametrize('province,member', [('Dersim', 'Örnek Vekil'), ('Hakkari', 'Başka Bir Vekil'), ('İstanbul', 'Örnek Soyad')])
def test_packet_preserves_source_names_and_constituencies(province, member):
    text = f"{province} Milletvekili {member}’in, İzmir ve başka kişilere ilişkin iddialara ilişkin Cumhurbaşkanı Yardımcısı’ndan (Cevdet YILMAZ) yazılı soru önergesi"
    result = bulk.packet_fields(text)
    assert result == dict(member=member, province=province, title='Cumhurbaşkanı Yardımcısı',
                          minister='Cevdet YILMAZ', minister_in_source=True)


def test_missing_or_malformed_metadata_is_not_inferred_from_summary():
    data = packet(text="Ankara hakkında bir konu ve Test Vekil ile Adalet Bakanı'ndan bahseden bozuk kayıt")
    records, _ = bulk.read_kkbs(data, 'Veri')
    assert not records[0].member and not records[0].province and not records[0].title
    review, pages = reading()
    result = bulk.compare_proposal(review, pages, [7], records)
    assert any(i['field'] == 'KKBS · Milletvekili' and i['status'] == 'belirsiz' for i in result['issues'])


@pytest.mark.parametrize('value', ['1980000', None, '8/50000', '???'])
def test_unlabeled_number_never_becomes_evrak_number_or_sequential_guess(value):
    data = packet(value)
    with pytest.raises(bulk.TableError, match='kaydı bulunamadı'):
        bulk.read_kkbs(data, 'Veri')


def test_packet_header_requires_exact_layout_or_explicit_number_column():
    data = workbook([['Paket Adı', 'Genel Evrak No', 'Önerge Sahibi Özeti'], ['Grup', 1980000, 'Metin']])
    with pytest.raises(bulk.TableError, match='Genel Evrak No esas numarası değildir'):
        bulk.read_kkbs(data, 'Rapor')
    data = workbook([['Esas No', 'Önerge Sahibi Özeti'], ['7/50000', "Kocaeli Milletvekili Test Vekil'in, hizmetlere ilişkin Adalet Bakanı'ndan yazılı soru önergesi"]])
    assert bulk.read_kkbs(data, 'Rapor')[0][0].number == 50000


def test_unavailable_personal_name_is_disclosed_without_repeating_false_suspicions():
    records, _ = bulk.read_kkbs(packet(), 'Veri')
    review, pages = reading()
    assert not bulk.compare_proposal(review, pages, [20], records)['issues']
    review = bulk.BulkReading.model_validate_json(review.model_dump_json().replace('Akın GÜRLEK', 'Yılmaz TUNÇ'))
    pages[0]['ocr'] = review.pages[0].text
    result = bulk.compare_proposal(review, pages, [20], records)
    assert any(i['field'] == 'Şekil · Muhatap' and i['status'] == 'uyari' for i in result['issues'])


def test_blank_named_minister_column_still_requires_attention():
    row = [*ROW]
    row[4] = ''
    records, _ = bulk.read_kkbs(workbook([HEADER, row]), 'Rapor')
    review, pages = reading()
    result = bulk.compare_proposal(review, pages, [20], records)
    assert any(i['field'] == 'KKBS · Muhatap bakan' and i['status'] == 'belirsiz' for i in result['issues'])


def test_same_number_with_conflicting_packet_metadata_is_not_deduplicated():
    r = replace(record(), minister='', minister_in_source=False)
    records = bulk.select_records([r, r, replace(r, province='İstanbul')])
    assert len(records) == 2
    review, pages = reading()
    result = bulk.compare_proposal(review, pages, [20], records)
    assert not result['matched']
    assert any('çelişkili' in i['explanation'] for i in result['issues'])
