"""Bulk review input and progress; only failures/uncertainties are listed."""
import hashlib
import json
from html import escape

import streamlit as st

from bulk_jobs import BulkJob
from bulk_review import (BULK_VERSION, MAX_BULK_MB, MAX_BULK_PAGES, TableError,
                         coverage_notes, default_kkbs_sheet, inspect_pdf, issue_rows,
                         issues_csv, read_kkbs, select_records)
from incoming_papers import sheet_names


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
    pdf = st.file_uploader('Toplu önerge taraması (.pdf)', type=['pdf'], key='bulk_pdf',
                           max_upload_size=MAX_BULK_MB, disabled=busy)
    excel = st.file_uploader('Karşılaştırılacak KKBS raporu (.xlsx)', type=['xlsx'], key='bulk_excel',
                             max_upload_size=12, disabled=busy)
    st.caption('Esas numarasıyla eşleştirme yapılır; evrak numarası gerekmez. Bakanlık başlıkları altında '
               '“Esas No / Sahibi ve Özeti” bulunan listeler de desteklenir.')
    if not credential:
        st.error('Analiz bağlantısı henüz yapılandırılmadı.')
    if pdf is None or excel is None:
        if job is not None and not busy:
            st.session_state.pop('bulk_job', None)
        st.info('Toplu PDF’yi ve KKBS Excel’ini birlikte yükleyin.')
        return
    pdf_data, excel_data = pdf.getvalue(), excel.getvalue()
    pdf_hash, excel_hash = hashlib.sha256(pdf_data).hexdigest(), hashlib.sha256(excel_data).hexdigest()
    try:
        if st.session_state.get('bulk_pdf_hash') != pdf_hash:
            count = inspect_pdf(pdf_data)
            st.session_state['bulk_pdf_count'] = count
            st.session_state['bulk_pdf_hash'] = pdf_hash
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
        st.error(str(exc))
        return
    source_id = hashlib.sha256(json.dumps([pdf_hash, table_key, first, last, model]).encode()).hexdigest()
    if job is not None and (job.source_id != source_id or job.version != BULK_VERSION):
        job.stop()
        if job.running:
            st.warning('Önceki işlem duraklatılıyor. Tamamlandığında yeni dosyaları başlatabilirsiniz.')
            return
        st.session_state.pop('bulk_job', None)
        job = None
    st.caption(f'{len({r.number for r in selected})} önerge kaydı karşılaştırılacak. Silik esas numarası '
               'sadece sıra bilgisiyle onaylanmaz; şüpheli eşleşme olarak gösterilir.')
    st.caption('İnceleme sırasında bu sayfayı açık tutun. Duraklatıp aynı oturumda devam edebilirsiniz; '
               'tamamlanan kayıtlar yeniden analiz edilmez. Sayfayı yenilemek/sunucunun yeniden başlaması oturumu '
               'kaybettirebilir; ara raporu indirebilirsiniz.')
    if job is None:
        if st.button('Toplu incelemeyi başlat', type='primary', disabled=not credential):
            job = BulkJob(pdf_data, st.session_state['bulk_pdf_count'], selected, model, source_id)
            st.session_state['bulk_job'] = job
            try:
                job.start(credential)
            except TableError as exc:
                st.error(str(exc))
            else:
                st.rerun()
    if job is not None:
        render_progress(job, credential, authorize)


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


def render_findings(snapshot):
    findings = snapshot['issues']
    st.subheader('Toplu inceleme sonucu')
    for note in snapshot.get('coverage_notes', []):
        st.info(note)
    a, b, c = st.columns(3)
    a.metric('Tamamlanan inceleme', snapshot['processed'] - snapshot['failed'])
    b.metric('Hatalı bulgu', sum(f['status'] == 'uyari' for f in findings))
    c.metric('Şüpheli bulgu', sum(f['status'] == 'belirsiz' for f in findings))
    if snapshot['state'] != 'complete':
        st.info('Bu ara rapordur. Bekleyen önergeler uygun kabul edilmez; tüm grup henüz incelenmedi.')
    elif findings:
        st.warning('Aşağıda yalnızca hatalı veya şüpheli bulgular var. PDF sayfaları, dosyanın başından itibaren 1’den sayılır.')
    else:
        st.success('Seçilen grubun şekil ve KKBS karşılaştırmasında hatalı veya şüpheli bulgu saptanmadı.')
    if findings:
        rows = issue_rows(findings)
        st.dataframe(rows, hide_index=True, width='stretch',
                     column_config={'Açıklama': st.column_config.TextColumn(width='large')})
        with st.expander('Açıklamaları tam metin göster'):
            choices = list(dict.fromkeys((row['Esas No'], row['PDF sayfası']) for row in rows))
            choice = st.selectbox('Bulgu ayrıntısı', choices, format_func=lambda x: f'{x[0]} · PDF sayfası {x[1]}')
            for row in rows:
                if (row['Esas No'], row['PDF sayfası']) != choice:
                    continue
                tone = 'uyari' if row['Sonuç'] == 'Hatalı' else 'belirsiz'
                values = ''.join(f'<p><strong>{label}:</strong> {escape(row[label])}</p>'
                                 for label in ('KKBS', 'Belge') if row[label])
                st.markdown(f'<div class="check-card {tone}"><div class="check-heading">'
                            f'{escape(row["Kontrol"])} · {escape(row["Sonuç"])}</div>'
                            f'<p>{escape(row["Açıklama"])}</p>{values}</div>', unsafe_allow_html=True)
    else:
        st.caption('Şu ana kadar listelenecek hata/şüphe yok.' if snapshot['state'] != 'complete' else 'Uygun önergeler ayrı ayrı listelenmez.')
    export = {**snapshot, 'scope': list(('Şekil', 'Milletvekili', 'Seçim çevresi', 'Muhatap bakanlık', 'Muhatap bakan')),
              'excluded': ['Tarih', 'Özet'], 'complete': snapshot['state'] == 'complete' and not snapshot['failed']}
    suffix = 'sonuc' if export['complete'] else 'ara-rapor'
    left, right = st.columns(2)
    left.download_button('Hata ve şüphe listesini indir (CSV)', issues_csv(findings),
                         f'toplu-inceleme-{suffix}.csv', 'text/csv', on_click='ignore')
    right.download_button('İnceleme raporunu indir (JSON)', json.dumps(export, ensure_ascii=False, indent=2),
                          f'toplu-inceleme-{suffix}.json', 'application/json', on_click='ignore')
