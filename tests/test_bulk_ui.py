from unittest.mock import patch

import pytest

from streamlit.testing.v1 import AppTest

from bulk_jobs import BulkJob
from bulk_review import issue
from test_app import pdf
from test_bulk_review import HEADER, ROW, record
from test_incoming_papers import workbook
from test_incoming_ui import click, login
from test_streamlit import configured


class Upload:
    def __init__(self, data, name): self.data, self.name = data, name
    def getvalue(self): return self.data


def test_bulk_mode_is_separate_and_accepts_large_pdf_uploads_without_marking(monkeypatch):
    at=login(configured(monkeypatch))
    at.radio(key='review_mode').set_value('Toplu inceleme').run()
    assert not at.exception
    assert [u.label for u in at.get('file_uploader')] == ['Toplu önerge taraması (.pdf)', 'Karşılaştırılacak KKBS raporu (.xlsx)']
    assert at.get('file_uploader')[0].proto.max_upload_size_mb == 100
    assert not at.get('download_button')
    assert any('Tarih ve özet karşılaştırılmaz' in c.value for c in at.caption)
    at.radio(key='review_mode').set_value('Tekli inceleme').run()
    assert at.get('file_uploader')[0].label == 'Önerge PDF’sini yükle'


def test_only_error_and_suspect_rows_and_partial_progress_are_rendered():
    snapshot={'state':'paused','processed':1,'failed':0,'issues':[issue(50001,[8],'uyari','KKBS · Milletvekili','Ad farklı','Beklenen','Belgedeki')]}
    at=AppTest.from_string('from bulk_ui import render_findings\nrender_findings('+repr(snapshot)+')').run()
    assert not at.exception
    assert at.dataframe[0].value['Esas No'].tolist() == ['7/50001']
    assert at.dataframe[0].value['PDF sayfası'].tolist() == ['8']
    assert at.info and 'ara rapordur' in at.info[0].value
    assert len(at.get('download_button')) == 2
    assert not any('İşaretli PDF' in d.label for d in at.get('download_button'))
    complete={**snapshot,'state':'complete','issues':[], 'complete':True, 'matched':1,'expected_count':1}
    at=AppTest.from_string('from bulk_ui import render_findings\nrender_findings('+repr(complete)+')').run()
    assert at.success and not at.dataframe


def test_bulk_upload_creates_session_job_and_changed_file_invalidates_results(monkeypatch):
    from bulk_review import IndexedPage
    data=pdf(12)
    excel=workbook([HEADER,ROW])
    def upload(label, **kwargs):
        return Upload(data,'group.pdf') if 'taraması' in label else Upload(excel,'kkbs.xlsx')
    def finish(self,credential,**kwargs):
        self.index=[IndexedPage(page=i,kind='start',explanation='') for i in range(1,13)]
        self.units=[{'pages':[1],'boundary_warnings':[]}]
        self.results={0:{'number':50000,'pages':[1],'matched':True,'issues':[],'failed':False}}
        self.state='complete'
    at=login(configured(monkeypatch))
    with patch('streamlit.file_uploader',side_effect=upload), patch.object(BulkJob,'start',finish), \
         patch('app.annotate_pdf',create=True,side_effect=AssertionError('No marking')):
        at.radio(key='review_mode').set_value('Toplu inceleme').run()
        at.radio(key='bulk_run_mode').set_value('Tüm grubu incele').run()
        assert not at.exception
        click(at,'Toplu incelemeyi başlat')
        assert at.session_state['bulk_job'].snapshot()['state'] == 'complete'
        assert at.success
        data=pdf(13)
        at.run()
        assert not at.exception and 'bulk_job' not in at.session_state
        assert not at.get('download_button')


def test_logout_pauses_only_that_users_bulk_work(monkeypatch):
    at=login(configured(monkeypatch))
    job=BulkJob(b'test',1,[record()],'test','test')
    job.state='running'
    at.session_state['bulk_job']=job
    other=BulkJob(b'test',1,[record()],'test','other')
    click(at,'Çıkış yap')
    assert job._stop.is_set() and not other._stop.is_set()
    assert 'bulk_job' not in at.session_state


def test_packet_automatically_selects_veri_and_discloses_unavailable_minister_names(monkeypatch):
    from test_bulk_packet import packet
    def upload(label, **kwargs):
        return Upload(pdf(3), 'scan.pdf') if 'taraması' in label else Upload(packet(), 'packet.xlsx')
    at = login(configured(monkeypatch))
    with patch('streamlit.file_uploader', side_effect=upload):
        at.radio(key='review_mode').set_value('Toplu inceleme').run()
        at.radio(key='bulk_run_mode').set_value('Tüm grubu incele').run()
    assert not at.exception and not at.error
    assert at.selectbox(key='bulk_sheet').value == 'Veri'
    assert any('1 kayıtta Excel yalnızca muhatap' in i.value for i in at.info)
    assert any('7/50000' in c.value for c in at.caption)
    assert any(b.label == 'Toplu incelemeyi başlat' and not b.disabled for b in at.button)


def test_dispatch_list_upload_needs_no_evrak_number_and_is_ready_to_review(monkeypatch):
    from test_bulk_dispatch import dispatch_rows
    def upload(label, **kwargs):
        return Upload(pdf(4), 'scan.pdf') if 'taraması' in label else Upload(workbook(dispatch_rows()), 'liste.xlsx')
    at = login(configured(monkeypatch))
    with patch('streamlit.file_uploader', side_effect=upload):
        at.radio(key='review_mode').set_value('Toplu inceleme').run()
        at.radio(key='bulk_run_mode').set_value('Tüm grubu incele').run()
    assert not at.exception and not at.error
    assert any('4 PDF sayfası · 4 KKBS satırı' in c.value for c in at.caption)
    assert any('evrak numarası gerekmez' in c.value for c in at.caption)
    assert any('3 kayıtta Excel yalnızca muhatap' in i.value for i in at.info)
    assert any(b.label == 'Toplu incelemeyi başlat' and not b.disabled for b in at.button)


def test_processed_batch_with_two_of_102_matches_is_not_a_completed_review():
    import json
    snapshot = {'state':'complete', 'processed':106, 'failed':0, 'proposal_count':106,
                'expected_count':102, 'matched':2, 'matching_complete':False, 'complete':False,
                'issues':[issue(50832, [], 'belirsiz', 'PDF eşleştirme', 'KKBS kaydı PDF ile eşleşmedi.')]}
    with patch('streamlit.delta_generator.DeltaGenerator.download_button', autospec=True, return_value=False) as download:
        at = AppTest.from_string('from bulk_ui import render_findings\nrender_findings('+repr(snapshot)+')').run()
    assert not at.exception and not at.success
    assert any('2 / 102' in e.value and 'tamamlanamadı' in e.value for e in at.error)
    assert any('106 belge başlangıcı' in w.value for w in at.warning)
    assert any(m.label == 'KKBS ile eşleşen' and m.value == '2 / 102' for m in at.metric)
    assert not any(m.label == 'Tamamlanan inceleme' for m in at.metric)
    assert len(download.call_args_list) == 2
    assert all('eksik-karsilastirma' in call.args[3] for call in download.call_args_list)
    exported = json.loads(download.call_args_list[1].args[2])
    assert not exported['complete'] and not exported['matching_complete']


def test_errors_are_primary_and_suspects_are_collapsed_but_exports_keep_both():
    import json
    errors = [issue(50832, [180], 'uyari', 'KKBS · Milletvekili', 'Ad farklı', 'Cengiz Çiçek', 'Çiçek OTLU')]
    suspects = [issue(50833, [182], 'belirsiz', 'Esas numarası', 'Kaşe silik')]
    snapshot = {'state': 'complete', 'processed': 2, 'failed': 0, 'complete': False,
                'matched': 1, 'expected_count': 2, 'issues': errors + suspects}
    with patch('streamlit.delta_generator.DeltaGenerator.download_button', autospec=True, return_value=False) as download:
        at = AppTest.from_string('from bulk_ui import render_findings\nrender_findings('+repr(snapshot)+')').run()
    assert not at.exception
    assert at.dataframe[0].value['Sonuç'].tolist() == ['Hatalı']
    suspect_section = next(e for e in at.expander if e.label.startswith('Şüpheli bulguları incele'))
    assert not suspect_section.proto.expanded
    assert suspect_section.dataframe[0].value['Sonuç'].tolist() == ['Şüpheli']
    assert len(at.selectbox) == 2
    assert at.selectbox(key='bulk_error_detail').value == ('7/50832', '180')
    assert at.selectbox(key='bulk_suspect_detail').value == ('7/50833', '182')
    assert any('tamamlanamadı' in e.value for e in at.error)
    exported = json.loads(download.call_args_list[1].args[2])
    assert exported['issues'] == errors + suspects
    assert '7/50833' in download.call_args_list[0].args[2].decode('utf-8-sig')


def test_only_suspects_is_not_presented_as_all_clear():
    snapshot = {'state': 'complete', 'processed': 1, 'failed': 0, 'complete': True,
                'matched': 1, 'expected_count': 1,
                'issues': [issue(50832, [180], 'belirsiz', 'Belge okuması', 'İmza okunamadı')]}
    at = AppTest.from_string('from bulk_ui import render_findings\nrender_findings('+repr(snapshot)+')').run()
    assert not at.exception and not at.success
    assert any('uygun olduğu anlamına gelmez' in i.value for i in at.info)
    assert not at.expander[0].proto.expanded


def test_sample_is_default_and_selected_physical_pages_are_passed_to_job(monkeypatch):
    data = pdf(221)
    excel = workbook([HEADER, ROW])
    def upload(label, **kwargs):
        return Upload(data, 'scan.pdf') if 'taraması' in label else Upload(excel, 'kkbs.xlsx')
    at = login(configured(monkeypatch))
    with patch('streamlit.file_uploader', side_effect=upload), patch.object(BulkJob, 'start') as start:
        at.radio(key='review_mode').set_value('Toplu inceleme').run()
        assert at.radio(key='bulk_run_mode').value == 'Küçük örnekle dene'
        at.number_input(key='bulk_test_first').set_value(180)
        at.number_input(key='bulk_test_last').set_value(181)
        assert start.call_count == 0
        assert any('1 ücretli API isteği' in c.value for c in at.caption)
        click(at, 'Denemeyi başlat (ücretli)')
        job = at.session_state['bulk_job']
        assert job.page_numbers == [180, 181] and job.page_count == 2
        assert job.original_page_count == 221 and job.is_test
        assert start.call_count == 1
        at.run()
        assert start.call_count == 1  # UI reruns never start another charge.
        assert not at.exception


def test_replay_ui_works_without_api_key_and_clears_results_when_excel_changes(monkeypatch):
    from test_bulk_replay import saved_cache
    data, cache = saved_cache()
    excel = workbook([HEADER, ['7/52342', *ROW[1:]]])
    at = login(configured(monkeypatch))
    monkeypatch.delenv('ONERGE_DIRECT_API_KEY', raising=False)
    monkeypatch.delenv('ONERGE_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    def upload(label, **kwargs):
        return Upload(cache, 'reading.json') if 'Kaydedilmiş' in label else Upload(data, 'scan.pdf') if 'taraması' in label else Upload(excel, 'kkbs.xlsx')
    with patch('streamlit.file_uploader', side_effect=upload), \
         patch.object(BulkJob, 'start', side_effect=AssertionError('No paid job')), \
         patch('app.analyze', side_effect=AssertionError('No API')):
        at.radio(key='review_mode').set_value('Toplu inceleme').run()
        at.radio(key='bulk_run_mode').set_value('Kayıtlı okumayı yeniden kontrol et (ücretsiz)').run()
        assert not at.error and not at.exception
        click(at, 'Ücretsiz yeniden kontrol et')
        assert at.session_state['bulk_replay_result']['api_requests'] == 0
        assert not at.success  # A cached test never certifies a full new scan.
        assert any('0 API isteği' in c.value for c in at.caption)
        excel = workbook([HEADER, ['7/52342', 'Başka Vekil', *ROW[2:]]])
        at.run()
        assert 'bulk_replay_result' not in at.session_state
        click(at, 'Ücretsiz yeniden kontrol et')
        assert any(i['field']=='KKBS · Milletvekili' for i in at.session_state['bulk_replay_result']['issues'])
        assert not at.exception


@pytest.mark.parametrize('mode', ['Küçük örnekle dene', 'Tüm grubu incele'])
def test_running_and_finished_jobs_keep_submitted_scope_when_widget_values_are_cleaned_up(monkeypatch, mode):
    data, excel = pdf(221), workbook([HEADER, ROW])
    def upload(label, **kwargs):
        return Upload(data, 'scan.pdf') if 'taraması' in label else Upload(excel, 'kkbs.xlsx')
    def start(self, credential): self.state = 'running'
    at = login(configured(monkeypatch))
    with patch('streamlit.file_uploader', side_effect=upload), patch.object(BulkJob, 'start', start):
        at.radio(key='review_mode').set_value('Toplu inceleme').run()
        at.radio(key='bulk_run_mode').set_value(mode).run()
        if mode == 'Küçük örnekle dene':
            at.number_input(key='bulk_test_first').set_value(180)
            at.number_input(key='bulk_test_last').set_value(181)
            click(at, 'Denemeyi başlat (ücretli)')
            expected = [180, 181]
        else:
            click(at, 'Toplu incelemeyi başlat')
            expected = list(range(1, 222))
        job = at.session_state['bulk_job']
        at.run()
        assert not at.exception and job.running and not job._stop.is_set()
        assert job.page_numbers == expected
        assert at.radio(key='bulk_run_mode').value == mode
        assert not any('duraklatılıyor' in x.value for x in at.warning)
        job.state = 'complete'
        at.run()
        assert not at.exception and at.session_state['bulk_job'] is job
        assert job.page_numbers == expected
        assert any(b.label == 'Yeni deneme / inceleme ayarları' for b in at.button)
