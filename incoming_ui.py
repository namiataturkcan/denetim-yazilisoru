"""Streamlit view for incoming papers. All input stays in this user's session."""
import hashlib
from html import escape
import json

import streamlit as st

from incoming_papers import (TableError, STATUS_LABELS, WORKFLOW_STAGES, REPORT_VERSION, build_report, read_excel,
                             read_paste, report_csv, report_text, sheet_names, add_batch, combined_batch_ranges)


def _clear_table():
    for name in ('incoming_records', 'incoming_source', 'incoming_result', 'incoming_parse_error',
                 'incoming_selection'):
        st.session_state.pop(name, None)


def render_incoming(recipients):
    _render_query(recipients)
    # Keep saved groups accessible even when the next upload is empty or invalid.
    render_batch_list(st.session_state['incoming_stage'])


def _render_query(recipients):
    reference_version = hashlib.sha256(json.dumps(list(recipients), ensure_ascii=False).encode()).hexdigest()[:12]
    st.caption('Excel’den veya yapıştırdığınız tablodan işlem yapılır. Bu bölüm API kullanmaz.')
    st.subheader('1. Esas numarası aralığı')
    left, right = st.columns(2)
    first = left.number_input('Başlangıç esas numarası', min_value=1, max_value=999999999,
                              value=None, step=1, placeholder='Örn. 45424', key='incoming_first')
    last = right.number_input('Bitiş esas numarası', min_value=1, max_value=999999999,
                             value=None, step=1, placeholder='Örn. 45530', key='incoming_last')
    st.caption('İncelenecek aralığı elle girin. Başlangıç ve bitiş numaraları işleme dahildir.')
    st.subheader('2. İşlem aşaması')
    stage = st.selectbox('İşlem aşamasını seçin', list(WORKFLOW_STAGES), key='incoming_stage',
                         format_func=lambda value: WORKFLOW_STAGES[value]['label'])
    if stage == 'prepare':
        st.info('Memur işlemi: süresi dolmuş pakette hâlâ “15 Günlük Cevaplanma Süresi Devam Ediyor” '
                'durumundaki önergeler ilan listesine alınır. Önceden ilan edilmiş önergeler bu listeye eklenmez.')
    else:
        st.info('Uzman kontrolü: yalnızca “Cevaplanmadığı Gelen Kağıtlarda İlan Edildi” '
                'durumundaki önergeler listelenir. Süresi devam ediyor görünenler bu listeye eklenmez.')
    st.caption('Paketin süre takibi sizdedir; burada tarih veya 15 günlük süre hesabı yapılmaz.')
    st.subheader('3. Veriyi ekleyin')
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
            # Keep an action visible even before the text area's first blur event.
            st.button('Yapıştırılan tabloyu oku')
            if not text.strip():
                _clear_table()
                st.info('Excel’den satırları sütunlarıyla birlikte kopyalayıp bu alana yapıştırın.')
                return
            source = (mode, hashlib.sha256(text.encode()).hexdigest(), REPORT_VERSION, reference_version)
            loader = lambda: read_paste(text)
            source_label = 'Yapıştırılan tablo'
        loaded = ('incoming_records' in st.session_state
                  or bool(st.session_state.get('incoming_parse_error')))
        if st.session_state.get('incoming_source') != source or not loaded:
            _clear_table()
            with st.spinner('Tablo okunuyor… Büyük KKBS raporları birkaç saniye sürebilir.'):
                try:
                    st.session_state['incoming_records'] = loader()
                except TableError as exc:
                    st.session_state['incoming_parse_error'] = str(exc)
                # Commit the source only after reading finishes. Streamlit can
                # interrupt at any widget/session access and rerun the script.
                st.session_state['incoming_source'] = source
        if st.session_state.get('incoming_parse_error'):
            st.error(st.session_state['incoming_parse_error'])
            st.button('Tabloyu yeniden oku', on_click=_clear_table)
            return
    except TableError as exc:
        _clear_table()
        st.error(str(exc))
        return
    records = st.session_state['incoming_records']
    selection = (source, first, last, stage)
    if st.session_state.get('incoming_selection') != selection:
        st.session_state.pop('incoming_result', None)
    st.session_state['incoming_selection'] = selection
    st.caption(f'{len(records):,} kaynak satırı okundu.')
    numbers = [record.number for record in records if record.number is not None]
    if numbers:
        st.caption(f'Dosyada görülen esas numaraları: {min(numbers)}-{max(numbers)}.')
    with st.expander('Tablodan okunan ilk kayıtları kontrol et'):
        st.dataframe([{'Esas No': row.number, 'Durum': row.status, 'Muhatap': row.recipient}
                      for row in records[:5]], hide_index=True, width='stretch')
    missing_bounds = first is None or last is None
    reversed_bounds = not missing_bounds and first > last
    if missing_bounds:
        st.info('En üstteki başlangıç ve bitiş esas numaralarını girin.')
    elif reversed_bounds:
        st.error('Başlangıç esas numarası bitiş numarasından büyük olamaz.')
    if st.button('Listeyi oluştur', type='primary', disabled=missing_bounds or reversed_bounds):
        try:
            result = build_report(records, first, last, None, recipients, stage=stage)
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
    workflow = WORKFLOW_STAGES[result['stage']]
    st.markdown('**' + workflow['label'] + '**')
    st.caption(f"İncelenen aralık: {result['first']}-{result['last']} · Kaynak: {result.get('source', 'Tablo')}")
    counts = result['counts']
    for col, label, count in zip(st.columns(4),
        ('Aralıktaki kayıt', workflow['count_label'], 'Cevaplanan', 'Geri alınan'),
        (result['total'], result['selected_count'], counts.get('answered', 0), counts.get('withdrawn', 0))):
        col.metric(label, count)
    st.caption('Cevaplanan sayısına süresi geçtikten sonra cevaplananlar da dahildir. Geri alınanlar cevaplanmamış listesine eklenmez.')
    if not result['total']:
        bounds = (f" Kaynakta görülen numaralar: {result['source_first']}-{result['source_last']}."
                  if result['source_first'] is not None else '')
        st.error('Seçtiğiniz aralıkta kaynak kaydı bulunamadı. Başlangıç/bitiş numaralarını ve '
                 'çalışma sayfasını kontrol edin.' + bounds + ' Bakanlıklar değerlendirilemedi.')
    elif not result['assessment_complete']:
        st.warning('Veri veya işlem aşaması için kontrol gerekiyor. Aşağıdaki uyarıları gidermeden sonucu tam liste olarak kullanmayın.')
    if result['workflow_warning']:
        st.warning(result['workflow_warning'])
    if result['stage'] == 'prepare' and counts.get('announced'):
        st.caption(f"{counts['announced']} önerge önceden ilan edilmiş; yeni ilan listesine tekrar eklenmedi.")
    if result['absent_count']:
        st.warning(f"Seçilen aralıktaki {result['absent_count']} numara dosyada yok; cevaplanmamış kabul edilmedi.")
        with st.expander('Dosyada bulunmayan esas numaraları'):
            st.code('\n'.join(result['absent_ranges']), language=None)
    if result['invalid_rows']:
        st.warning(f"{len(result['invalid_rows'])} satırın esas numarası okunamadı; sonuçlara eklenmedi. Ayrıntılar indirilen raporda bulunur.")
    if counts.get('conflict') or counts.get('unknown'):
        st.warning(f"{counts.get('conflict', 0)} çelişkili, {counts.get('unknown', 0)} durumu tanınmayan kayıt var. Bu kayıtlar cevaplanmamış sayısına dahil edilmedi.")
    if result['unrecognized_statuses']:
        st.dataframe([{'Tanınmayan durum': status or '(boş)', 'Kayıt': count}
                      for status, count in list(result['unrecognized_statuses'].items())[:20]], hide_index=True)
    if result['duplicate_count']:
        st.caption(f"{result['duplicate_count']} yinelenen satır tekilleştirildi; aynı önerge bir kez sayıldı.")
    st.markdown('**' + workflow['ranges_label'] + '**')
    if result['ranges']:
        st.caption('Noktalı virgülle ayrılmış tek satır · sağ üstteki simgeden kopyalayabilirsiniz.')
        st.code(result['ranges_text'], language=None, wrap_lines=True)
        st.caption('Alt alta liste')
        st.code('\n'.join(result['ranges']), language=None)
        if st.button('Birleşik listeye ekle'):
            stages = st.session_state.get('incoming_batches', {})
            try:
                batches = add_batch(stages.get(result['stage'], []), result)
                st.session_state['incoming_batches'] = {**stages, result['stage']: batches}
                st.success('Sorgu birleşik listeye kaydedildi. Aynı aralık yeniden eklenirse önceki sonuç güncellenir.')
            except TableError as exc:
                st.error(str(exc))
    else:
        if result['total'] and counts.get('answered', 0) + counts.get('withdrawn', 0) == result['total']:
            st.info('Bulunan kayıtların tamamı cevaplanmış veya geri alınmış. Bu kayıtlardan ilan listesi oluşturulmaz.')
        elif result['total']:
            st.info('Seçilen aşama için doğrulanabilen kayıt yok. İşlem aşamasını ve aşağıdaki durum dağılımını kontrol edin.')
    with st.expander('Aralıktaki kayıtların durum dağılımı'):
        st.dataframe([{'Durum': label, 'Önerge': counts.get(group, 0)} for group, label in STATUS_LABELS.items()],
                      hide_index=True, width='stretch')
    if result['selected_count']:
        render_recipients(result)
    if result['other_recipients']:
        st.warning('Aşağıdaki muhatap adları referans listesiyle eşleşmedi. Önerge numaraları sayıldı; muhatap listesi için bu adları kontrol edin.')
        st.dataframe([{'Muhatap': name, 'Önerge': result['recipient_counts'][name]}
                      for name in result['other_recipients']], hide_index=True)
    with st.expander('Kayıtlar ve işlem grupları'):
        if len(result['rows']) > 500:
            st.caption('İlk 500 kayıt gösteriliyor. Kayıtların tamamını CSV veya JSON olarak indirebilirsiniz.')
        st.dataframe([{'Esas No': row['number'], 'İşlem grubu': STATUS_LABELS[row['group']],
                       'Kaynak durum': row['status'], 'Muhatap': row['recipient'],
                       'Kaynak satırları': ', '.join(map(str, row['source_rows']))} for row in result['rows'][:500]],
                      hide_index=True, width='stretch')
    text = report_text(result)
    with st.expander('Kopyalanabilir sonuç metni'):
        st.code(text, language=None)
    first, second, third = st.columns(3)
    filename = f"gelen-kagit-{'memur' if result['stage'] == 'prepare' else 'uzman'}-{result['first']}-{result['last']}"
    first.download_button('Sonuç metnini indir', text.encode('utf-8-sig'), filename + '.txt', 'text/plain', on_click='ignore')
    second.download_button('Kayıtları indir (CSV)', report_csv(result), filename + '.csv', 'text/csv', on_click='ignore')
    third.download_button('Raporu indir (JSON)', json.dumps(result, ensure_ascii=False, indent=2), filename + '.json', 'application/json', on_click='ignore')


def _remove_batch(stage, batch_id=None):
    stages = st.session_state.get('incoming_batches', {})
    batches = [batch for batch in stages.get(stage, []) if batch['id'] != batch_id] if batch_id else []
    st.session_state['incoming_batches'] = {**stages, stage: batches}


def render_batch_list(stage):
    st.divider()
    st.subheader('Birleşik giriş listesi')
    st.caption(WORKFLOW_STAGES[stage]['label'] + ' · Her sorgudan sonra “Birleşik listeye ekle” düğmesini kullanın.')
    st.caption('Yeni sorgu veya dosya eklenen grupları silmez. Liste bu oturumda tutulur; '
               'sayfayı yenilemeden veya çıkış yapmadan önce kopyalayın ya da indirin. '
               'Memur ve uzman listeleri ayrıdır.')
    batches = st.session_state.get('incoming_batches', {}).get(stage, [])
    if not batches:
        st.info('Henüz bir sorgu eklenmedi.')
        return
    stale = any(batch['report_version'] != REPORT_VERSION for batch in batches)
    if stale:
        st.warning('Eklenen sorgular arasında eski sürümle hazırlanmış sonuç var. '
                   'Bu grupları yeniden sorgulayıp ekleyin veya listeden çıkarın.')
    else:
        ranges = combined_batch_ranges(batches)
        count = len({number for batch in batches for number in batch['numbers']})
        st.markdown(f'**{len(batches)} sorgu · {count} önerge**')
        if any(not batch['assessment_complete'] for batch in batches):
            st.warning('Kontrol gerektiren sorgular eklendi. Bu liste yalnızca o sorgularda '
                       'seçilebilen numaraları içerir; kaynak uyarılarını gidermeden tam liste olarak kullanmayın.')
        st.caption('Tekrarlanan numaralar bir kez alınır; ardışık numaralar birleştirilir. '
                   'Tek numaralar da 44613-44613 biçimindedir.')
        text = ';'.join(ranges)
        st.code(text, language=None, wrap_lines=True)
        st.caption('Birleşik liste · Alt alta')
        st.code('\n'.join(ranges), language=None)
        label = 'memur' if stage == 'prepare' else 'uzman'
        st.download_button('Birleşik listeyi indir (TXT)', text, f'gelen-kagit-birlesik-{label}.txt',
                           'text/plain', on_click='ignore')
    with st.expander('Eklenen sorguları yönet'):
        for index, batch in enumerate(batches, 1):
            left, right = st.columns([4, 1])
            left.write(f"{index}. {batch['first']}-{batch['last']} · {len(batch['numbers'])} önerge")
            left.caption(batch['source'])
            if not batch['assessment_complete']:
                left.caption('Bu sorgunun veri veya işlem aşaması uyarıları var.')
            if batch['report_version'] != REPORT_VERSION:
                left.caption('Eski sürüm; yeniden sorgulayın.')
            right.button('Çıkar', key=f"remove_batch_{stage}_{batch['id']}",
                         on_click=_remove_batch, args=(stage, batch['id']))
        st.button('Birleşik listeyi temizle', on_click=_remove_batch, args=(stage,))


def render_recipients(result):
    left, right = st.columns([2, 1])
    with left:
        names = ''.join(f'<li>{escape(name)}</li>' for name in result['present_recipients'])
        st.markdown('<section class="incoming-recipients found">'
                    '<h3>Bulunan bakanlıklar ve muhataplar</h3>'
                    f'<div class="recipient-count">{len(result["present_recipients"])}</div>'
                    + (f'<ul>{names}</ul>' if names else '<p>Bu aralıkta bulunan muhatap yok.</p>')
                    + '</section>', unsafe_allow_html=True)
    with right:
        if not result['present_recipients'] and not result['assessment_complete']:
            st.info('Muhatap adları doğrulanamadığı için bulunmayan bakanlıklar listesi çıkarılmadı.')
        else:
            names = ''.join(f'<li>{escape(name)}</li>' for name in result['missing_recipients'])
            st.markdown('<section class="incoming-recipients missing">'
                        f'<h3>Bulunmayanlar · {len(result["missing_recipients"])}</h3>'
                        + (f'<ul>{names}</ul>' if names else '<p>Referans listesindeki tüm muhataplar bulunuyor.</p>')
                        + '</section>', unsafe_allow_html=True)
            if not result['assessment_complete']:
                st.caption('Bu adlar yalnızca doğrulanabilen sonuçlarda görülmedi; veri eksikleri giderilmeden yoklukları kesinleştirilemez.')
    st.caption('Muhatap listeleri yalnızca seçtiğiniz işlem aşamasına alınan önergelerden hesaplanır.')
