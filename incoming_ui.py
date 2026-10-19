"""Streamlit view for incoming papers. All input stays in this user's session."""
import hashlib
from html import escape
import json

import streamlit as st

from incoming_papers import (TableError, STATUS_LABELS, REPORT_VERSION, build_report, read_excel,
                             read_paste, report_csv, report_text, sheet_names)


def _clear_table():
    for name in ('incoming_records', 'incoming_source', 'incoming_result', 'incoming_parse_error',
                 'incoming_selection'):
        st.session_state.pop(name, None)


def render_incoming(recipients):
    reference_version = hashlib.sha256(json.dumps(list(recipients), ensure_ascii=False).encode()).hexdigest()[:12]
    st.caption('Excel’den veya yapıştırdığınız tablodan işlem yapılır. Bu bölüm API kullanmaz.')
    st.subheader('1. Esas numarası aralığı')
    left, right = st.columns(2)
    first = left.number_input('Başlangıç esas numarası', min_value=1, max_value=999999999,
                              value=None, step=1, placeholder='Örn. 45424', key='incoming_first')
    last = right.number_input('Bitiş esas numarası', min_value=1, max_value=999999999,
                             value=None, step=1, placeholder='Örn. 45530', key='incoming_last')
    st.caption('İncelenecek aralığı elle girin. Başlangıç ve bitiş numaraları işleme dahildir.')
    st.subheader('2. Veriyi ekleyin')
    mode = st.radio('Veri girişi', ['Excel yükle', 'Tablo yapıştır'], horizontal=True, key='incoming_mode')
    try:
        if mode == 'Excel yükle':
            uploaded = st.file_uploader('KKBS raporunu yükle (.xlsx)', type=['xlsx'], key='incoming_upload')
            if uploaded is None:
                _clear_table()
                st.info('Esas No, Son Durum ve Muhatap Unvanı sütunlarını içeren Excel dosyasını yükleyin.')
                return
            data = uploaded.getvalue()
            digest = hashlib.sha256(data).hexdigest()
            if st.session_state.get('incoming_book_digest') != digest:
                _clear_table()
                st.session_state.pop('incoming_sheet', None)
                st.session_state['incoming_sheets'] = sheet_names(data)
                st.session_state['incoming_book_digest'] = digest
            sheet = st.selectbox('Çalışma sayfası', st.session_state['incoming_sheets'], key='incoming_sheet')
            source = (mode, digest, sheet, REPORT_VERSION, reference_version)
            loader = lambda: read_excel(data, sheet)
            source_label = f'{uploaded.name} · {sheet}'
        else:
            text = st.text_area('Excel tablosunu buraya yapıştırın', height=200, key='incoming_paste',
                help='Başlıklı tablo veya sırasıyla esas numarası, durum, muhatap içeren başlıksız satırlar kabul edilir.')
            if not text.strip():
                _clear_table()
                st.info('Excel’den satırları sütunlarıyla birlikte kopyalayıp bu alana yapıştırın.')
                return
            source = (mode, hashlib.sha256(text.encode()).hexdigest(), REPORT_VERSION, reference_version)
            loader = lambda: read_paste(text)
            source_label = 'Yapıştırılan tablo'
        if st.session_state.get('incoming_source') != source:
            _clear_table()
            st.session_state['incoming_source'] = source
            with st.spinner('Tablo okunuyor…'):
                try:
                    st.session_state['incoming_records'] = loader()
                except TableError as exc:
                    st.session_state['incoming_parse_error'] = str(exc)
        if st.session_state.get('incoming_parse_error'):
            st.error(st.session_state['incoming_parse_error'])
            return
    except TableError as exc:
        _clear_table()
        st.error(str(exc))
        return
    records = st.session_state['incoming_records']
    selection = (source, first, last)
    if st.session_state.get('incoming_selection') != selection:
        st.session_state.pop('incoming_result', None)
    st.session_state['incoming_selection'] = selection
    st.caption(f'{len(records):,} kaynak satırı okundu.')
    missing_bounds = first is None or last is None
    reversed_bounds = not missing_bounds and first > last
    if missing_bounds:
        st.info('En üstteki başlangıç ve bitiş esas numaralarını girin.')
    elif reversed_bounds:
        st.error('Başlangıç esas numarası bitiş numarasından büyük olamaz.')
    if st.button('Listeyi oluştur', type='primary', disabled=missing_bounds or reversed_bounds):
        try:
            result = build_report(records, first, last, None, recipients)
            result['source'] = source_label
            result['source_sha256'] = source[1]
            st.session_state['incoming_result'] = result
        except (TableError, ValueError) as exc:
            st.error(str(exc))
    result = st.session_state.get('incoming_result')
    if result:
        render_incoming_report(result)


def render_incoming_report(result):
    st.subheader('Gelen Kağıt İşlem Sonucu')
    counts = result['counts']
    for col, label, count in zip(st.columns(4),
        ('Aralıktaki kayıt', 'Cevaplanmamış', 'Cevaplanan', 'Geri alınan'),
        (result['total'], result['selected_count'], counts.get('answered', 0), counts.get('withdrawn', 0))):
        col.metric(label, count)
    st.caption('Cevaplanan sayısına süresi geçtikten sonra cevaplananlar da dahildir. Geri alınanlar cevaplanmamış listesine eklenmez.')
    if result['absent_count']:
        st.warning(f"Seçilen aralıktaki {result['absent_count']} numara dosyada yok; cevaplanmamış kabul edilmedi.")
        with st.expander('Dosyada bulunmayan esas numaraları'):
            st.code('\n'.join(result['absent_ranges']), language=None)
    if result['invalid_rows']:
        st.warning(f"{len(result['invalid_rows'])} satırın esas numarası okunamadı; sonuçlara eklenmedi. Ayrıntılar indirilen raporda bulunur.")
    if counts.get('conflict') or counts.get('unknown'):
        st.warning(f"{counts.get('conflict', 0)} çelişkili, {counts.get('unknown', 0)} durumu tanınmayan kayıt var. Bu kayıtlar cevaplanmamış sayısına dahil edilmedi.")
    if result['duplicate_count']:
        st.caption(f"{result['duplicate_count']} yinelenen satır tekilleştirildi; aynı önerge bir kez sayıldı.")
    st.markdown('**Cevaplanmamış / cevap süresi devam eden esas numarası aralıkları**')
    if result['ranges']:
        st.caption('Noktalı virgülle ayrılmış tek satır · sağ üstteki simgeden kopyalayabilirsiniz.')
        st.code(result['ranges_text'], language=None, wrap_lines=True)
        with st.expander('Aralıkları alt alta göster'):
            st.code('\n'.join(result['ranges']), language=None)
    else:
        st.info('Bu aralıkta listeye alınacak cevaplanmamış kayıt bulunamadı.')
    for group in ('announced', 'pending'):
        with st.expander(f'{STATUS_LABELS[group]} · {counts.get(group, 0)} önerge'):
            st.code('\n'.join(result['ranges_by_status'][group]) or 'Yok', language=None)
    left, right = st.columns([2, 1])
    with left:
        names = ''.join(f'<li>{escape(name)}</li>' for name in result['present_recipients'])
        st.markdown('<section class="incoming-recipients found">'
                    '<h3>Bulunan bakanlıklar ve muhataplar</h3>'
                    f'<div class="recipient-count">{len(result["present_recipients"])}</div>'
                    + (f'<ul>{names}</ul>' if names else '<p>Bu aralıkta bulunan muhatap yok.</p>')
                    + '</section>', unsafe_allow_html=True)
    with right:
        names = ''.join(f'<li>{escape(name)}</li>' for name in result['missing_recipients'])
        st.markdown('<section class="incoming-recipients missing">'
                    f'<h3>Bulunmayanlar · {len(result["missing_recipients"])}</h3>'
                    + (f'<ul>{names}</ul>' if names else '<p>Referans listesindeki tüm muhataplar bulunuyor.</p>')
                    + '</section>', unsafe_allow_html=True)
    st.caption('Muhatap listeleri yalnızca cevaplanmamış / cevap süresi devam eden sonuçlara göre hesaplanır.')
    if result['other_recipients']:
        st.warning('Bazı muhataplar 18 muhataplık referans listesinde yok; önerge sayısına dahil edildi, aşağıda ayrıca gösteriliyor.')
        st.dataframe([{'Muhatap': name, 'Önerge': result['recipient_counts'][name]}
                      for name in result['other_recipients']], hide_index=True)
    with st.expander('Tüm kayıtlar ve işlem grupları'):
        st.dataframe([{'Esas No': row['number'], 'İşlem grubu': STATUS_LABELS[row['group']],
                       'Kaynak durum': row['status'], 'Muhatap': row['recipient'],
                       'Kaynak satırları': ', '.join(map(str, row['source_rows']))} for row in result['rows']],
                      hide_index=True, width='stretch')
    text = report_text(result)
    with st.expander('Kopyalanabilir sonuç metni'):
        st.code(text, language=None)
    first, second, third = st.columns(3)
    filename = f"gelen-kagit-{result['first']}-{result['last']}"
    first.download_button('Sonuç metnini indir', text.encode('utf-8-sig'), filename + '.txt', 'text/plain')
    second.download_button('Kayıtları indir (CSV)', report_csv(result), filename + '.csv', 'text/csv')
    third.download_button('Raporu indir (JSON)', json.dumps(result, ensure_ascii=False, indent=2), filename + '.json', 'application/json')
