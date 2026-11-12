from unittest.mock import patch

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
    complete={**snapshot,'state':'complete','issues':[]}
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
    assert not at.exception and not at.error
    assert at.selectbox(key='bulk_sheet').value == 'Veri'
    assert any('1 kayıtta Excel yalnızca muhatap' in i.value for i in at.info)
    assert any('7/50000' in c.value for c in at.caption)
    assert any(b.label == 'Toplu incelemeyi başlat' and not b.disabled for b in at.button)
