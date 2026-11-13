"""Bulk review input and progress; only failures/uncertainties are listed."""
import hashlib
import json
from html import escape

import streamlit as st

from bulk_jobs import BulkJob
from bulk_replay import MAX_CACHE_MB, load_readings, recheck_readings
from bulk_review import (BULK_VERSION, MAX_BULK_MB, MAX_BULK_PAGES, TableError,
                         coverage_notes, default_kkbs_sheet, inspect_pdf, issue_rows,
                         issues_csv, read_kkbs, select_records)
from incoming_papers import sheet_names

MODE_SAMPLE = 'Küçük örnekle dene'
MODE_FULL = 'Tüm grubu incele'
MODE_REPLAY = 'Kayıtlı okumayı yeniden kontrol et (ücretsiz)'


def pause_bulk_job():
    job = st.session_state.get('bulk_job')
    if job is not None:
        job.stop()


def render_bulk(credential, model, authorize):
    job = st.session_state.get('bulk_job')
    busy = job is not None and job.running
    st.session_state['bulk_controls_running'] = busy
    st.subheader('Toplu son inceleme')
    st.write('Taranmış önergeleri KKBS kayıtlarıyla karşılaştırın. Yalnızca hatalı veya şüpheli '
             'bulgular; esas numarası, fiziksel PDF sayfası ve açıklamasıyla listelenir.')
    st.caption('Kontroller: mevcut altı şekil koşulu; KKBS ile milletvekili adı, seçim çevresi, '
               'muhatap bakanlık ve bakan adı. Tarih ve özet karşılaştırılmaz. PDF üzerine işaret konulmaz.')
    st.caption(f'Bir grupta en fazla 200 önerge; PDF en fazla {MAX_BULK_MB} MB / {MAX_BULK_PAGES} sayfa, Excel en fazla 12 MB. '
               'Sayfa görüntüleri analiz sırasında OpenAI’a gönderilir ve API kullanımı ücretlidir.')
    modes = [MODE_SAMPLE, MODE_FULL, MODE_REPLAY]
    committed = st.session_state.get('bulk_job_inputs', {})
    run_mode = st.radio('Çalışma biçimi', modes, index=modes.index(committed.get('mode', MODE_SAMPLE)),
                        key='bulk_run_mode', disabled=busy)
    pdf = st.file_uploader('Toplu önerge taraması (.pdf)', type=['pdf'], key='bulk_pdf',
                           max_upload_size=MAX_BULK_MB, disabled=busy)
    excel = st.file_uploader('Karşılaştırılacak KKBS raporu (.xlsx)', type=['xlsx'], key='bulk_excel',
                             max_upload_size=12, disabled=busy)
    st.caption('Esas numarasıyla eşleştirme yapılır; evrak numarası gerekmez. Bakanlık başlıkları altında '
               '“Esas No / Sahibi ve Özeti” bulunan listeler de desteklenir.')
    if not credential and run_mode != MODE_REPLAY:
        st.error('Analiz bağlantısı henüz yapılandırılmadı.')
    if busy:
        # Running work uses immutable submitted inputs, never transient widget
        # defaults after Streamlit disables or recreates a form.
        render_active_job(job, credential, authorize)
        return
    if pdf is None or excel is None:
        if job is not None and not busy:
            st.session_state.pop('bulk_job', None)
            st.session_state.pop('bulk_job_inputs', None)
        st.info('Toplu PDF’yi ve KKBS Excel’ini birlikte yükleyin.')
        return
    pdf_data, excel_data = pdf.getvalue(), excel.getvalue()
    pdf_hash, excel_hash = hashlib.sha256(pdf_data).hexdigest(), hashlib.sha256(excel_data).hexdigest()
    input_signature = [pdf_hash, excel_hash, run_mode, model, BULK_VERSION]
    if job is not None and run_mode != MODE_REPLAY:
        if committed.get('signature') == input_signature and job.version == BULK_VERSION:
            render_active_job(job, credential, authorize)
            return
        job.stop()
        st.session_state.pop('bulk_job', None)
        st.session_state.pop('bulk_job_inputs', None)
        job = None
    try:
        if st.session_state.get('bulk_pdf_hash') != pdf_hash:
            count = inspect_pdf(pdf_data)
            st.session_state['bulk_pdf_count'] = count
            st.session_state['bulk_pdf_hash'] = pdf_hash
            st.session_state.pop('bulk_test_first', None)
            st.session_state.pop('bulk_test_last', None)
        if st.session_state.get('bulk_excel_hash') != excel_hash:
            names = sheet_names(excel_data)
            st.session_state['bulk_sheets'] = names
            st.session_state['bulk_sheet'] = default_kkbs_sheet(excel_data, names)
            st.session_state['bulk_excel_hash'] = excel_hash
        sheet = st.selectbox('KKBS çalışma sayfası', st.session_state['bulk_sheets'], key='bulk_sheet', disabled=busy)
        table_key = (excel_hash, sheet, BULK_VERSION)
        if st.session_state.get('bulk_table_key') != table_key or 'bulk_records' not in st.session_state:
            with st.spinner('KKBS kayıtları okunuyor…'):
                records, invalid = read_kkbs(excel_data, sheet)
                st.session_state['bulk_records'] = records
                st.session_state['bulk_invalid'] = invalid
                st.session_state['bulk_table_key'] = table_key
        records = st.session_state['bulk_records']
        st.caption(f"{st.session_state['bulk_pdf_count']} PDF sayfası · {len(records):,} KKBS satırı")
        st.markdown('**İncelenecek KKBS grubu**')
        st.caption('Excel yalnızca bu grubu içeriyorsa boş bırakabilirsiniz. Tam KKBS raporunda grubun '
                   'başlangıç ve bitiş numarasını girin; bu aralıkta PDF’de bulunmayan kayıtlar da bildirilir.')
        left, right = st.columns(2)
        first = left.number_input('Grubun başlangıç esas numarası', value=None, min_value=1, max_value=999999999,
                                   step=1, key='bulk_first', disabled=busy)
        last = right.number_input('Grubun bitiş esas numarası', value=None, min_value=1, max_value=999999999,
                                   step=1, key='bulk_last', disabled=busy)
        selected = select_records(records, first, last)
        st.caption(f'KKBS esas numaraları: 7/{min(r.number for r in selected)} – 7/{max(r.number for r in selected)}')
        for note in coverage_notes(selected):
            st.info(note)
        invalid = st.session_state['bulk_invalid']
        if invalid:
            st.error(f'{len(invalid)} KKBS satırının esas numarası okunamadı. Bu satırların hangi gruba ait olduğu '
                     'belirlenemediği için inceleme başlatılmadı. Dosyayı düzelterek tekrar yükleyin.')
            st.caption('Kaynak satırları: ' + ', '.join(map(str, invalid[:30])))
            return
    except (TableError, ValueError) as exc:
        if not busy:
            st.session_state.pop('bulk_job', None)
            st.session_state.pop('bulk_job_inputs', None)
        st.error(str(exc))
        return
    if run_mode == MODE_REPLAY:
        if job is not None:
            job.stop()
            if job.running:
                st.warning('Devam eden ücretli istek tamamlanınca kayıtlı okumayı kontrol edebilirsiniz.')
                return
        render_replay(pdf_data, st.session_state['bulk_pdf_count'], selected, (pdf_hash, table_key, first, last))
        return
    test_pages, single_proposal, sample_submit = None, False, False
    if run_mode == MODE_SAMPLE:
        st.info('Deneme yalnız seçtiğiniz PDF sayfalarını okur. En fazla 10 sayfa; tüm paket incelenmez.')
        count = st.session_state['bulk_pdf_count']
        with st.form('bulk_sample_form', enter_to_submit=False):
            left, right = st.columns(2)
            page_first = left.number_input('İlk PDF sayfası', min_value=1, max_value=count, value=1,
                                            step=1, key='bulk_test_first', disabled=busy)
            page_last = right.number_input('Son PDF sayfası', min_value=1, max_value=count, value=min(2, count),
                                            step=1, key='bulk_test_last', disabled=busy)
            single_proposal = st.radio('Deneme türü', ['Seçilen sayfalar tek önergeye ait', 'Sayfa ayırmayı da dene'],
                                       key='bulk_test_kind', disabled=busy) == 'Seçilen sayfalar tek önergeye ait'
            st.caption('Tek önerge: ilk sayfadan son devam sayfasına kadar yalnız bir önerge seçin; '
                       'sayfa ayırma atlanır ve 1 ücretli API isteği yapılır. '
                       'Sayfa ayırmayı da dene: en fazla 10 sayfada ayırma ve okuma için en fazla 13 API isteği.')
            sample_submit = st.form_submit_button('Denemeyi başlat (ücretli)', type='primary', disabled=busy or not credential)
        if page_last < page_first or page_last-page_first+1 > 10:
            st.error('Başlangıç ve bitişi doğru sırada, en fazla 10 PDF sayfası olacak şekilde seçin.')
            return
        test_pages = list(range(page_first, page_last+1))
        st.caption('İstek sayısı tutar değildir; ücret sayfa içeriği, yanıt uzunluğu ve modele bağlıdır. '
                   'Denemede PDF’de bulunmayan diğer KKBS kayıtları eksik sayılmaz.')
    else:
        st.warning(f"Tüm grupta {st.session_state['bulk_pdf_count']} PDF sayfası ücretli olarak okunacak. "
                   'Esas numarası aralığı Excel kayıtlarını süzer; PDF sayfalarını azaltmaz. Önce küçük örnekle deneyin.')
    source_id = hashlib.sha256(json.dumps([pdf_hash, table_key, first, last, model, test_pages, single_proposal]).encode()).hexdigest()
    st.caption(f'{len({r.number for r in selected})} KKBS kaydı eşleştirmeye kaynak olacak. Silik esas numarası '
               'sadece sıra bilgisiyle onaylanmaz; şüpheli eşleşme olarak gösterilir.')
    st.caption('İnceleme sırasında bu sayfayı açık tutun. Duraklatıp aynı oturumda devam edebilirsiniz; '
               'tamamlanan kayıtlar yeniden analiz edilmez. Sayfayı yenilemek/sunucunun yeniden başlaması oturumu '
               'kaybettirebilir. Dosya/ayar değiştirmeden önce “Okumayı kaydet” dosyasını indirin; '
               'sonraki ücretsiz testler için bu kayıt gerekir.')
    if job is None:
        start_requested = sample_submit if test_pages is not None else st.button('Toplu incelemeyi başlat', type='primary', disabled=not credential)
        if start_requested:
            job = BulkJob(pdf_data, st.session_state['bulk_pdf_count'], selected, model, source_id,
                          test_pages=test_pages, single_proposal=single_proposal)
            st.session_state['bulk_job'] = job
            st.session_state['bulk_job_inputs'] = {'signature': input_signature, 'mode': run_mode}
            try:
                job.start(credential)
            except TableError as exc:
                st.error(str(exc))
            else:
                st.rerun()
    if job is not None:
        render_active_job(job, credential, authorize)


def render_active_job(job, credential, authorize):
    st.caption(f"Bu işlem: PDF {job.page_numbers[0]}–{job.page_numbers[-1]} · {job.page_count} sayfa. "
               'İşlem kapsamı başlatırken seçtiğiniz değerlerle sabittir.')
    render_progress(job, credential, authorize)
    if not job.running:
        st.caption('Dosya veya ayar değiştirmeden önce okumayı kaydedin; ücretsiz tekrar kontrol için bu kayıt gerekir.')
        if st.button('Yeni deneme / inceleme ayarları', key='bulk_new_settings'):
            job.stop()
            st.session_state.pop('bulk_job', None)
            st.session_state.pop('bulk_job_inputs', None)
            st.rerun()


def render_replay(pdf_data, page_count, records, source):
    st.info('API çağrısı yapılmaz; kredi tüketmez. Kayıtlı görsel okuma güncel kurallar ve yüklediğiniz Excel ile '
            'yeniden karşılaştırılır. Görüntü yeniden okunmadığı için eski bir okuma hatası burada düzelmez.')
    saved = st.file_uploader('Kaydedilmiş okuma (.json)', type=['json'], max_upload_size=MAX_CACHE_MB, key='bulk_reading_upload')
    if saved is None:
        st.caption('Önce bir deneme yapıp “Okumayı kaydet” dosyasını indirin. Eski sonuç raporları ham okumayı içermez.')
        return
    data = saved.getvalue()
    cache_key = hashlib.sha256(json.dumps([source, hashlib.sha256(data).hexdigest(), BULK_VERSION]).encode()).hexdigest()
    if st.session_state.get('bulk_replay_key') != cache_key:
        st.session_state.pop('bulk_replay_result', None)
        st.session_state['bulk_replay_key'] = cache_key
    if st.button('Ücretsiz yeniden kontrol et', type='primary'):
        try:
            bundle = load_readings(data, pdf_data, page_count)
            result = recheck_readings(bundle, records)
            st.session_state['bulk_replay_result'] = result
        except TableError as exc:
            st.error(str(exc))
    if result := st.session_state.get('bulk_replay_result'):
        render_findings(result)


@st.fragment(run_every='2s')
def render_progress(job, credential, authorize):
    if not authorize():
        job.stop()
        st.rerun()
    snapshot = job.snapshot()
    running = snapshot['state'] in ('running', 'stopping')
    if st.session_state.get('bulk_controls_running') != running:
        st.rerun()
    if snapshot['proposal_count'] is None:
        fraction = snapshot['indexed_pages'] / snapshot['page_count']
        st.progress(fraction, text=f"Sayfa sınırları: {snapshot['indexed_pages']} / {snapshot['page_count']}")
    else:
        fraction = snapshot['processed'] / max(1, snapshot['proposal_count'])
        st.progress(fraction, text=f"Önerge incelemesi: {snapshot['processed']} / {snapshot['proposal_count']}")
    if snapshot['message']:
        st.warning(snapshot['message'])
    if running:
        if st.button('İncelemeyi duraklat', disabled=snapshot['state'] == 'stopping'):
            job.stop()
            st.rerun()
    elif snapshot['state'] != 'complete':
        if st.button('Kaldığı yerden devam et', disabled=not credential):
            try:
                job.start(credential)
                st.rerun()
            except TableError as exc:
                st.error(str(exc))
    elif snapshot['failed']:
        if st.button('Tamamlanamayan incelemeleri yeniden dene', disabled=not credential):
            try:
                job.start(credential, retry_failed=True)
                st.rerun()
            except TableError as exc:
                st.error(str(exc))
    render_findings(snapshot)
    if saved := job.reading_cache():
        st.download_button('Okumayı kaydet (ücretsiz tekrar test için)', saved,
                           'onerge-okuma-kaydi.json', 'application/json', on_click='ignore')
        st.caption('Bu dosya belge metnini içerir. PDF ve API anahtarı içermez. İndirip aynı PDF ve Excel ile '
                   '“Kayıtlı okumayı yeniden kontrol et” seçeneğinde kullanabilirsiniz.')


def render_findings(snapshot):
    findings = snapshot['issues']
    errors = [f for f in findings if f['status'] == 'uyari']
    suspects = [f for f in findings if f['status'] != 'uyari']
    st.subheader('Toplu inceleme sonucu')
    is_test = snapshot.get('is_test', False)
    if is_test:
        physical = snapshot.get('tested_pages', [])
        label = ', '.join(map(str, physical[:20])) + (' …' if len(physical) > 20 else '')
        st.info(f'Deneme raporu · PDF sayfaları: {label}. Bu sonuç tüm grubun son kontrolü değildir.')
        if snapshot.get('is_replay'):
            st.caption(f"0 API isteği · Kayıtlı okuma sürümü: {snapshot.get('reading_version', '')}. "
                       'Güncel kontroller eski okuma üzerinde çalıştırıldı; PDF yeniden okunmadı.')
    for note in snapshot.get('coverage_notes', []):
        st.info(note)
    a, b, c, d = st.columns(4)
    a.metric('İşlenen belge', snapshot['processed'] - snapshot['failed'])
    b.metric('Eşleşen deneme belgesi' if is_test else 'KKBS ile eşleşen',
             f"{snapshot.get('matched', 0)} / {snapshot['processed'] if is_test else snapshot.get('expected_count', 0)}")
    c.metric('Hatalı bulgu', len(errors))
    d.metric('Şüpheli bulgu', len(suspects))
    if (not is_test and snapshot.get('proposal_count') is not None and snapshot.get('expected_count') is not None
            and snapshot['proposal_count'] != snapshot['expected_count']):
        st.warning(f"PDF’de {snapshot['proposal_count']} belge başlangıcı, Excel’de {snapshot['expected_count']} önerge var. "
                   'Belge sınırları veya yüklenen grubun kapsamı kontrol edilmeli.')
    if snapshot['state'] != 'complete':
        st.info('Bu ara rapordur. Bekleyen önergeler uygun kabul edilmez; tüm grup henüz incelenmedi.')
    elif is_test:
        st.info('Deneme tamamlandı. Hata veya şüpheli bulgu saptanmadı.' if not findings
                else 'Deneme tamamlandı. Hatalar ve şüpheler aşağıda ayrı gösteriliyor.')
    elif not snapshot.get('complete', False):
        st.error(f"KKBS karşılaştırması tamamlanamadı: {snapshot.get('matched', 0)} / {snapshot.get('expected_count', 0)} kayıt eşleşti. "
                 'Bazı belgelerin eşleşmesi veya sayfa aidiyeti doğrulanamadı; '
                 'bu rapor grubun son kontrolü olarak kullanılamaz.')
    elif not findings:
        st.success('Seçilen grubun şekil ve KKBS karşılaştırmasında hatalı veya şüpheli bulgu saptanmadı.')
    st.caption('PDF sayfaları dosyanın başından itibaren 1’den sayılır. Uygun önergeler listelenmez.')
    st.subheader('Hatalı bulgular')
    if errors:
        render_finding_table(errors)
        with st.expander('Hata açıklamalarını tam metin göster'):
            render_finding_details(errors, 'bulk_error_detail')
    elif suspects:
        st.info('Kesin hata saptanmadı. Şüpheli bulgular aşağıdaki ayrı bölümde; bu sonuç tüm önergelerin uygun olduğu anlamına gelmez.')
    else:
        st.caption('Şu ana kadar listelenecek hata yok.' if snapshot['state'] != 'complete' else 'Hatalı bulgu yok.')
    if suspects:
        with st.expander(f'Şüpheli bulguları incele ({len(suspects)})', expanded=False):
            st.caption('Okunamayan alanlar, OCR uyuşmazlıkları ve doğrulanamayan eşleşmeler. Bunlar kesin hata olarak değerlendirilmez.')
            render_finding_table(suspects)
            render_finding_details(suspects, 'bulk_suspect_detail')
    export = {**snapshot, 'scope': list(('Şekil', 'Milletvekili', 'Seçim çevresi', 'Muhatap bakanlık', 'Muhatap bakan')),
              'excluded': ['Tarih', 'Özet'], 'complete': bool(snapshot.get('complete', False))}
    suffix = 'deneme' if is_test else 'sonuc' if export['complete'] else 'eksik-karsilastirma' if snapshot['state'] == 'complete' else 'ara-rapor'
    left, right = st.columns(2)
    left.download_button('Hata ve şüphe listesini indir (CSV)', issues_csv(findings),
                         f'toplu-inceleme-{suffix}.csv', 'text/csv', on_click='ignore')
    right.download_button('İnceleme raporunu indir (JSON)', json.dumps(export, ensure_ascii=False, indent=2),
                          f'toplu-inceleme-{suffix}.json', 'application/json', on_click='ignore')


def render_finding_table(findings):
    st.dataframe(issue_rows(findings), hide_index=True, width='stretch',
                 column_config={'Açıklama': st.column_config.TextColumn(width='large')})


def render_finding_details(findings, widget_key):
    rows = issue_rows(findings)
    choices = list(dict.fromkeys((row['Esas No'], row['PDF sayfası']) for row in rows))
    choice = st.selectbox('Bulgu ayrıntısı', choices, key=widget_key,
                          format_func=lambda x: f'{x[0]} · PDF sayfası {x[1]}')
    for row in rows:
        if (row['Esas No'], row['PDF sayfası']) != choice:
            continue
        tone = 'uyari' if row['Sonuç'] == 'Hatalı' else 'belirsiz'
        values = ''.join(f'<p><strong>{label}:</strong> {escape(row[label])}</p>'
                         for label in ('KKBS', 'Belge') if row[label])
        st.markdown(f'<div class="check-card {tone}"><div class="check-heading">'
                    f'{escape(row["Kontrol"])} · {escape(row["Sonuç"])}</div>'
                    f'<p>{escape(row["Açıklama"])}</p>{values}</div>', unsafe_allow_html=True)
