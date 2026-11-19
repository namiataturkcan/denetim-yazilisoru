"""Session-local, API-free comparison of two sheets in one uploaded workbook."""
import hashlib
import json

import streamlit as st
from openpyxl.utils import get_column_letter

from entry_comparison import (VERSION, compare_records, issue_rows, read_sheets,
                              records, report_csv, suggest_columns, suggest_header, text)
from incoming_papers import MAX_TABLE_BYTES, TableError, key, sheet_names


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def clear_results():
    for name in ('entry_result', 'entry_result_key'):
        st.session_state.pop(name, None)


def reset_source(source):
    if st.session_state.get('entry_source') != source:
        for name in list(st.session_state):
            if name.startswith('entry_') and name != 'entry_upload':
                st.session_state.pop(name, None)
        st.session_state['entry_source'] = source


def column_controls(sheet, side, source_key):
    st.markdown(f'**{side} sütunları**')
    prefix = f'entry_{side}_{source_key}'
    header = int(st.number_input(f'{side} başlık satırı', min_value=1, max_value=30,
                                value=suggest_header(sheet), step=1, key=prefix+'_header'))
    headers = sheet.headers(header)
    guessed = suggest_columns(headers)
    options = [None, *range(len(headers))]
    mapping = {}
    labels = {'document': 'Ortak evrak numarası', 'member': 'Milletvekili adı / sahibi',
              'ministry': 'Bakanlık / muhatap', 'case': 'Esas numarası (isteğe bağlı)'}
    for field, label in labels.items():
        mapping[field] = st.selectbox(f'{side} · {label}', options,
            index=options.index(guessed[field]), key=f'{prefix}_{header}_{field}',
            format_func=lambda i: 'Seçilmedi' if i is None else f'{get_column_letter(i+1)} · {text(headers[i]) or "Başlıksız"}')
    if not headers:
        st.warning('Bu başlık satırı boş. Excel’de sütun adlarının bulunduğu satırı seçin.')
    preview = []
    for number, values in sheet.rows:
        if number > header:
            preview.append({'Excel satırı': str(number), **{
                labels[field]: text(values[index]) if index is not None and index < len(values) else ''
                for field, index in mapping.items()}})
        if len(preview) == 3:
            break
    if preview:
        st.caption('Seçilen sütunlardan ilk üç kayıt')
        st.dataframe(preview, hide_index=True, width='stretch')
    return header, mapping


def show_table(items):
    st.dataframe(issue_rows(items[:500]), hide_index=True, width='stretch')
    if len(items) > 500:
        st.caption('İlk 500 bulgu gösteriliyor; indirilen rapor bütün bulguları içerir.')


def render_result(report):
    st.subheader('Giriş Karşılaştırma Sonucu')
    values = (('Eşleşen evrak', report['matched'], 'neutral'),
              ('Uyumlu', report['clean']+report['spelling'], 'uygun'),
              ('Uyuşmayan evrak', report['different'], 'uyari'),
              ('Kontrol bulgusu', sum(i['status'] == 'belirsiz' for i in report['issues']), 'belirsiz'))
    for col, (label, count, tone) in zip(st.columns(4), values):
        col.markdown(f'<div class="status-card {tone if count else "neutral"}"><div>{label}</div>'
                     f'<div class="status-count">{count}</div></div>', unsafe_allow_html=True)
    st.caption(f"KKBS: {report['kkbs_count']} kayıt · EBYS: {report['ebys_count']} kayıt. "
               'Bir evrakta birden fazla kontrol bulgusu olabilir. Açıklaması boş kayıtlar da kapsama dahildir.')
    red = [i for i in report['issues'] if i['status'] == 'uyari']
    yellow = [i for i in report['issues'] if i['status'] == 'belirsiz']
    if not report['matched']:
        st.error('Ortak evrak numarasıyla birebir eşleşen kayıt bulunamadı. Sayfaları, evrak numarası sütunlarını ve rapor kapsamını kontrol edin.')
    elif not report['complete']:
        st.warning(f"Karşılaştırma tam olarak doğrulanamadı. Eşleşmeyen KKBS satırı: {report['unmatched_kkbs']}; "
                   f"EBYS satırı: {report['unmatched_ebys']}. Kontrol listesindeki kayıtları inceleyin.")
    if red:
        st.error(f"{report['different']} evrakta milletvekili veya bakanlık uyuşmazlığı bulundu. Hangi girişin doğru olduğunu önergenin aslından kontrol edin.")
        show_table(red)
    elif report['complete']:
        st.success('Eşleşen bütün kayıtlarda milletvekili ve bakanlık bilgileri uyumlu.')
    elif report['matched']:
        st.info('Belirgin uyuşmazlık bulunmadı; kontrol listesindeki kayıtlar henüz doğrulanmış sayılmaz.')
    if yellow:
        with st.expander(f'Kontrol gerekli · {len(yellow)} bulgu'):
            st.caption('Eksik, birden fazla eşleşen veya ayrıştırılamayan bilgiler burada gösterilir.')
            show_table(yellow)
    if report['variants']:
        with st.expander(f'Uyumlu sayılan küçük yazım farkları · {len(report["variants"])} bulgu'):
            show_table(report['variants'])
    st.caption('Bu karşılaştırma iki kaydın tutarlılığını kontrol eder; her iki kayıtta aynı yanlış bilgi bulunabilir.')
    left, right = st.columns(2)
    left.download_button('Karşılaştırmayı indir (CSV)', report_csv(report),
        file_name='ebys-kkbs-karsilastirma.csv', mime='text/csv', on_click='ignore')
    right.download_button('Ayrıntılı raporu indir (JSON)', json.dumps(report, ensure_ascii=False, indent=2),
        file_name='ebys-kkbs-karsilastirma.json', mime='application/json', on_click='ignore')


def render_entry_comparison(recipients, reference_names):
    st.subheader('EBYS–KKBS karşılaştırması')
    st.write('KKBS ve EBYS raporlarının ayrı çalışma sayfalarında bulunduğu tek Excel dosyasını yükleyin. '
             'Ortak evrak numarası üzerinden milletvekili ve bakanlık girişleri karşılaştırılır.')
    st.caption('API kullanmaz; kredi tüketmez. Bakanlık kısaltmaları ve küçük yazım farkları dikkate alınır. '
               'Açıklama sütununun dolu olması gerekmez. En fazla 12 MB, sayfa başına 100.000 kayıt.')
    upload = st.file_uploader('KKBS ve EBYS raporlarını içeren Excel (.xlsx)', type=['xlsx'], key='entry_upload')
    if upload is None:
        reset_source(None)
        return
    data = upload.getvalue()
    source = hashlib.sha256(data).hexdigest()
    reset_source(source)
    try:
        if len(data) > MAX_TABLE_BYTES:
            raise TableError('Excel dosyası en fazla 12 MB olabilir.')
        names = sheet_names(data)
        if len(names) < 2:
            raise TableError('Dosyada en az iki çalışma sayfası olmalı: biri KKBS, diğeri EBYS / gelen evrak raporu.')
        left, right = st.columns(2)
        default_kkbs = next((n for n in names if 'kkbs' in key(n)), names[0])
        default_ebys = next((n for n in names if n != default_kkbs and any(v in key(n) for v in ('ebys', 'gelenevrak'))),
                            next(n for n in names if n != default_kkbs))
        kkbs_name = left.selectbox('KKBS çalışma sayfası', names, index=names.index(default_kkbs), key='entry_kkbs_sheet')
        ebys_name = right.selectbox('EBYS çalışma sayfası', names, index=names.index(default_ebys), key='entry_ebys_sheet')
        source_key = digest([source, kkbs_name, ebys_name, VERSION])
        if st.session_state.get('entry_loaded_key') != source_key or not st.session_state.get('entry_sheets'):
            clear_results()
            sheets = read_sheets(data, [kkbs_name, ebys_name])
            st.session_state['entry_sheets'] = sheets
            st.session_state['entry_loaded_key'] = source_key  # Mark loaded only after a complete read.
        sheets = st.session_state['entry_sheets']
        guesses = [suggest_columns(sheet.headers(suggest_header(sheet))) for sheet in sheets]
        missing = any(g[f] is None for g in guesses for f in ('document', 'member', 'ministry'))
        with st.expander('Sayfa ve sütunları kontrol et', expanded=missing):
            st.caption('Evrak numarası iki raporda da aynı kayıt numarası olmalı. Ad ve bakanlık aynı konu/özet sütunundaysa '
                       'o sütunu iki alanda da seçebilirsiniz. Esas numarası varsa yalnızca sonuçlarda gösterilir.')
            left, right = st.columns(2)
            with left:
                kkbs_header, kkbs_mapping = column_controls(sheets[0], 'KKBS', source_key)
            with right:
                ebys_header, ebys_mapping = column_controls(sheets[1], 'EBYS', source_key)
        config = {'document_sha256': source, 'version': VERSION,
                  'reference_sha256': digest([recipients, sorted(reference_names)]),
                  'kkbs': {'sheet': kkbs_name, 'header_row': kkbs_header, 'columns': kkbs_mapping},
                  'ebys': {'sheet': ebys_name, 'header_row': ebys_header, 'columns': ebys_mapping}}
        result_key = digest(config)
        if st.session_state.get('entry_result_key') != result_key:
            clear_results()
        ready = all(m[f] is not None for m in (kkbs_mapping, ebys_mapping) for f in ('document', 'member', 'ministry'))
        if not ready:
            st.info('Sütun ayarlarından ortak evrak numarası, milletvekili ve bakanlık sütunlarını seçin.')
        if st.button('Girişleri karşılaştır', type='primary', disabled=not ready):
            clear_results()
            with st.spinner('Kayıtlar karşılaştırılıyor…'):
                kkbs = records(sheets[0], kkbs_header, kkbs_mapping)
                ebys = records(sheets[1], ebys_header, ebys_mapping)
                result = compare_records(kkbs, ebys, recipients, reference_names)
                result['source'] = config
                st.session_state['entry_result'] = result
                st.session_state['entry_result_key'] = result_key
        result = st.session_state.get('entry_result')
        if result:
            render_result(result)
    except TableError as exc:
        clear_results()
        st.error(str(exc))
