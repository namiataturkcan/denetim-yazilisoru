"""Session-local, API-free comparison of combined or separate registers."""
import hashlib
import json

import streamlit as st
from openpyxl.utils import get_column_letter

from entry_comparison import (VERSION, compare_records, issue_rows, read_sheets,
                              records, report_csv, suggest_mapping, suggest_header,
                              suggest_sheet, suggest_sheet_pair, sheet_score, text, validate_ebys_source)
from incoming_papers import MAX_TABLE_BYTES, TableError, sheet_names


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
    header = int(st.number_input(f'{side} başlık satırı', min_value=0, max_value=30,
                                value=suggest_header(sheet), step=1, key=prefix+'_header',
                                help='Başlık yoksa 0 seçin; ilk satır da kayıt olarak okunur.'))
    headers = sheet.headers(header)
    guessed = suggest_mapping(sheet, header)
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
    st.write('Okuma sonrası kontrolü için birleşik Excel’i; okuma öncesi kontrolü için ayrı KKBS ve EBYS dosyalarını yükleyin. '
             'Dosya sayısına göre işlem otomatik seçilir. İki durumda da milletvekili ve bakanlık girişleri karşılaştırılır.')
    st.caption('API kullanmaz; kredi tüketmez. Bakanlık kısaltmaları ve küçük yazım farkları dikkate alınır. '
               'Açıklama sütununun dolu olması gerekmez. Dosya başına en fazla 12 MB, sayfa başına 100.000 kayıt.')
    uploads = st.file_uploader('Birleşik Excel’i veya ayrı KKBS ve EBYS dosyalarını yükle (.xlsx)',
                               type=['xlsx'], accept_multiple_files=True, key='entry_upload')
    if not uploads:
        reset_source(None)
        return
    files = [{'name': upload.name, 'data': upload.getvalue()} for upload in uploads]
    for file in files:
        file['sha256'] = hashlib.sha256(file['data']).hexdigest()
    source = digest([(file['name'], file['sha256']) for file in files])
    reset_source(source)
    try:
        if len(files) > 2:
            raise TableError('Bir birleşik Excel veya iki ayrı rapor yükleyin. Fazladan eklenen dosyaları kaldırın.')
        for file in files:
            if len(file['data']) > MAX_TABLE_BYTES:
                raise TableError('Her Excel dosyası en fazla 12 MB olabilir.')
            file['names'] = sheet_names(file['data'])
            if not file['names']:
                raise TableError('Excel dosyasında çalışma sayfası bulunamadı.')
        if len(files) == 2 and files[0]['sha256'] == files[1]['sha256']:
            raise TableError('Aynı dosya iki kez yüklenmiş. Bir KKBS raporu ve bir EBYS raporu seçin.')
        if len(files) == 1 and len(files[0]['names']) < 2:
            clear_results()
            st.info('Tek çalışma sayfalı bir rapor yüklendi. Okuma öncesi kontrolü için diğer Excel dosyasını da aynı alana ekleyin. '
                    'Okuma sonrası kontrolünde KKBS ve EBYS’nin ayrı sayfalarda bulunduğu birleşik dosya kullanılır.')
            return
        workflow = 'after' if len(files) == 1 else 'before'
        st.subheader('Okuma Sonrası Kontrolü' if workflow == 'after' else 'Okuma Öncesi Kontrolü')
        profile_key = digest([source, VERSION])
        if st.session_state.get('entry_profile_key') != profile_key or not st.session_state.get('entry_profiles'):
            clear_results()
            profiles = [read_sheets(file['data'], file['names'], preview=True) for file in files]
            st.session_state['entry_profiles'] = profiles
            st.session_state['entry_profile_key'] = profile_key
        profiles = st.session_state['entry_profiles']
        if workflow == 'after':
            kkbs_file = ebys_file = 0
            default_kkbs, default_ebys = suggest_sheet_pair(profiles[0])
        else:
            default_file = max(range(2), key=lambda i: (
                max(sheet_score(sheet, 'kkbs') for sheet in profiles[i]), 'kkbs' in files[i]['name'].casefold()))
            left, right = st.columns(2)
            file_label = lambda i: f"{i+1} · {files[i]['name']}"
            kkbs_file = left.selectbox('KKBS dosyası', [0, 1], index=default_file, format_func=file_label, key='entry_kkbs_file')
            ebys_file = right.selectbox('EBYS dosyası', [0, 1], index=1-default_file, format_func=file_label, key='entry_ebys_file')
            if kkbs_file == ebys_file:
                raise TableError('KKBS ve EBYS için iki farklı dosya seçin.')
            default_kkbs = suggest_sheet(profiles[kkbs_file], 'kkbs')
            default_ebys = suggest_sheet(profiles[ebys_file], 'ebys')
        kfile, efile = files[kkbs_file], files[ebys_file]
        left, right = st.columns(2)
        kkbs_name = left.selectbox('KKBS çalışma sayfası', kfile['names'], index=kfile['names'].index(default_kkbs),
                                  key='entry_kkbs_sheet_'+kfile['sha256'])
        ebys_name = right.selectbox('EBYS çalışma sayfası', efile['names'], index=efile['names'].index(default_ebys),
                                   key='entry_ebys_sheet_'+efile['sha256'])
        source_key = digest([source, kkbs_file, ebys_file, kkbs_name, ebys_name, VERSION])
        if st.session_state.get('entry_loaded_key') != source_key or not st.session_state.get('entry_sheets'):
            clear_results()
            sheets = (read_sheets(kfile['data'], [kkbs_name, ebys_name]) if workflow == 'after' else
                      [read_sheets(kfile['data'], [kkbs_name])[0], read_sheets(efile['data'], [ebys_name])[0]])
            st.session_state['entry_sheets'] = sheets
            st.session_state['entry_loaded_key'] = source_key  # Mark loaded only after a complete read.
        sheets = st.session_state['entry_sheets']
        guesses = [suggest_mapping(sheet, suggest_header(sheet)) for sheet in sheets]
        missing = any(g[f] is None for g in guesses for f in ('document', 'member', 'ministry'))
        with st.expander('Sayfa ve sütunları kontrol et', expanded=missing):
            st.caption('Evrak numarası iki raporda da aynı kayıt numarası olmalı. Ad ve bakanlık aynı konu/özet sütunundaysa '
                       'o sütunu iki alanda da seçebilirsiniz. Esas numarası varsa yalnızca sonuçlarda gösterilir.')
            left, right = st.columns(2)
            with left:
                kkbs_header, kkbs_mapping = column_controls(sheets[0], 'KKBS', source_key)
            with right:
                ebys_header, ebys_mapping = column_controls(sheets[1], 'EBYS', source_key)
        for side, name, header, mapping in (('KKBS', kkbs_name, kkbs_header, kkbs_mapping),
                                            ('EBYS', ebys_name, ebys_header, ebys_mapping)):
            selected = ' · '.join(label + ': ' + (get_column_letter(mapping[field]+1) if mapping[field] is not None else 'seçilmedi')
                                  for field, label in (('document', 'Evrak'), ('member', 'Milletvekili'), ('ministry', 'Bakanlık')))
            st.caption(f'{side} / {name} · {selected} · ' + ('Başlık yok; ilk satır dahil' if header == 0 else f'Başlık: {header}. satır'))
        validate_ebys_source(sheets[1], ebys_header, ebys_mapping)
        config = {'workflow': workflow, 'version': VERSION,
                  'reference_sha256': digest([recipients, sorted(reference_names)]),
                  'kkbs': {'file_name': kfile['name'], 'document_sha256': kfile['sha256'],
                           'sheet': kkbs_name, 'header_row': kkbs_header, 'columns': kkbs_mapping},
                  'ebys': {'file_name': efile['name'], 'document_sha256': efile['sha256'],
                           'sheet': ebys_name, 'header_row': ebys_header, 'columns': ebys_mapping}}
        if workflow == 'after':
            config['document_sha256'] = kfile['sha256']
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
