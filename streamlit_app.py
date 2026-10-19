"""Password-protected Streamlit interface; documents stay in session memory."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import html
from pathlib import Path

from annotations import annotate_pdf, marked_text

import streamlit as st
from fastapi import HTTPException
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app import ANALYSIS_VERSION, RELEASE, MAX_BYTES, RULES, analyze, finalize, prepare_pdf
from incoming_ui import render_incoming


def setting(name, default=""):
    try:
        return str(st.secrets.get(name, os.environ.get(name, default)))
    except FileNotFoundError:
        return os.environ.get(name, default)


def create_markings(data, result):
    st.session_state.pop("markings", None)
    st.session_state.pop("markings_error", None)
    try:
        st.session_state["markings"] = annotate_pdf(data, result["review"]["checks"])
    except Exception:
        # A PDF renderer/OCR failure must not discard a paid, completed analysis.
        st.session_state["markings_error"] = (
            "Analiz tamamlandı; PDF üzerindeki işaretler oluşturulamadı. "
            "Metindeki işaretleri inceleyebilir ve JSON raporunu indirebilirsiniz.")


def main():
    section = st.session_state.get("active_module")
    titles = {"review": "Yazılı Soru Önergesi İncelemesi", "incoming": "Gelen Kağıt İşlemleri"}
    title = titles.get(section, "Yazılı Soru İşlemleri")
    subtitle = {"review": "Belgeyi inceleyin, bulguları kaynağı üzerinde görün, raporu indirin.",
                "incoming": "Cevaplanmamış önergeleri, esas numarası aralıklarını ve muhatapları listeleyin."}.get(section, "Yapmak istediğiniz işlemi seçin.")
    st.set_page_config(page_title=title, page_icon="📄", layout="wide")
    st.markdown("<style>" + Path(__file__).with_name("streamlit_style.css").read_text() + "</style>", unsafe_allow_html=True)
    st.markdown(f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)
    st.caption(f"Sürüm: {RELEASE}")
    password = setting("APP_PASSWORD")
    if not password:
        st.error("Uygulama erişim parolası henüz yapılandırılmadı.")
        st.stop()
    # Store a fingerprint, never the submitted password, and invalidate on rotation.
    fingerprint = hashlib.sha256(password.encode()).hexdigest()
    if st.session_state.get("authenticated") != fingerprint:
        with st.form("login"):
            entered = st.text_input("Erişim parolası", type="password")
            submitted = st.form_submit_button("Giriş yap")
        if submitted:
            if hmac.compare_digest(entered.encode(), password.encode()):
                st.session_state["authenticated"] = fingerprint
                st.rerun()
            else:
                st.error("Parola doğru değil.")
        st.stop()
    if st.button("Çıkış yap", type="tertiary"):
        st.session_state.clear()
        st.rerun()
    if section not in titles:
        render_home()
        return
    if st.button("← İşlem seçimine dön", type="tertiary"):
        st.session_state.pop("active_module", None)
        st.rerun()
    if section == "incoming":
        render_incoming(RULES["recipients"])
        return
    render_review()


def select_module(name):
    st.session_state["active_module"] = name


def render_home():
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown('<div class="module-card"><div class="module-number">01 · BELGE İNCELEMESİ</div><h2>Yazılı Soru Önergesi İncelemesi</h2><p>Önerge PDF’sini yükleyin. Şekil kontrollerini, bakan ve seçim çevresi eşleşmelerini inceleyin; hataları belge üzerinde görün.</p></div>', unsafe_allow_html=True)
        st.button("Önerge incelemesine geç", type="primary", width="stretch", on_click=select_module, args=("review",))
    with right:
        st.markdown('<div class="module-card"><div class="module-number">02 · LİSTE İŞLEMLERİ</div><h2>Gelen Kağıt İşlemleri</h2><p>Excel yükleyin veya tablo yapıştırın. Esas numarası aralığına göre cevaplanmamış önergeleri, bulunan ve eksik muhatapları listeleyin.</p></div>', unsafe_allow_html=True)
        st.button("Gelen kağıt işlemlerine geç", type="primary", width="stretch", on_click=select_module, args=("incoming",))


def render_review():
    key = setting("ONERGE_DIRECT_API_KEY") or setting("ONERGE_API_KEY") or setting("OPENAI_API_KEY")
    if not key:
        st.error("Analiz bağlantısı henüz yapılandırılmadı.")
    st.caption("En fazla 12 MB, 10 sayfa PDF. Analiz sırasında sayfa görüntüleri OpenAI'a gönderilir. Sonuçları belgeyle karşılaştırarak kontrol edin.")
    uploaded = st.file_uploader("Önerge PDF’sini yükle", type=["pdf"])
    if uploaded is None:
        for name in ("document", "pages", "result", "markings", "markings_error", "document_error"):
            st.session_state.pop(name, None)
        st.info("Başlamak için bir önerge PDF’si seçin.")
        st.stop()
    data = uploaded.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    if st.session_state.get("document") != digest:
        for name in ("markings", "markings_error", "result", "pages", "document_error"):
            st.session_state.pop(name, None)
        st.session_state["document"] = digest
        try:
            if len(data) > MAX_BYTES:
                raise HTTPException(413, "Dosya sınırı 12 MB.")
            st.session_state["pages"] = prepare_pdf(data)
        except HTTPException as exc:
            st.session_state["document_error"] = exc.detail
    if st.session_state.get("document_error"):
        st.error(st.session_state["document_error"])
        st.stop()
    pages = st.session_state.get("pages")
    if not pages:
        st.error("PDF okunamadı. Başka bir dosya seçin.")
        st.stop()
    if st.session_state.get("result") and st.session_state["result"].get("analysis_version") != ANALYSIS_VERSION:
        st.session_state.pop("result", None)
        st.session_state.pop("markings", None)
        st.session_state.pop("markings_error", None)
        st.info("Analiz kuralları güncellendi. Bu belge için incelemeyi yeniden başlatın.")
    if st.button("İncelemeyi başlat", type="primary", disabled=not key):
        st.session_state.pop("result", None)
        st.session_state.pop("markings", None)
        st.session_state.pop("markings_error", None)
        try:
            with st.spinner("Belge okunuyor ve kontroller yapılıyor…"):
                review = asyncio.run(analyze(pages, credential=key, model=setting("ONERGE_MODEL", "gpt-4.1")))
                result = finalize(review, pages)
                result["document_sha256"] = digest
                st.session_state["result"] = result
                create_markings(data, result)
        except APIStatusError as exc:
            st.error({401: "API anahtarı kabul edilmedi.", 403: "API erişimine izin verilmedi.",
                      429: "API bakiyesini ve kullanım sınırlarını kontrol edin.",
                      404: "Seçilen model kullanılamıyor."}.get(exc.status_code, "Analiz servisi isteği tamamlayamadı."))
        except (APIConnectionError, APITimeoutError):
            st.error("Analiz servisine ulaşılamadı. Biraz sonra tekrar deneyin.")
        except HTTPException as exc:
            st.error(exc.detail)
        except ValueError:
            st.error("Analiz yanıtı doğrulanamadı. Yeniden deneyin.")
    result = st.session_state.get("result")
    if result and st.session_state.get("markings_error"):
        st.warning(st.session_state["markings_error"])
        if st.button("PDF işaretlerini yeniden oluştur"):
            with st.spinner("PDF işaretleri oluşturuluyor…"):
                create_markings(data, result)
            st.rerun()
    markings = st.session_state.get("markings")
    if result:
        render_status_summary(result["review"]["checks"])
    st.markdown('<div class="legend">✓ Yeşil: Uygun &nbsp; · &nbsp; ✕ Kırmızı: Hatalı &nbsp; · &nbsp; ? Sarı: Kontrol Gerekli</div>', unsafe_allow_html=True)
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.subheader("Belge ve Metin")
        for i, page in enumerate(pages, 1):
            image_tab, text_tab = st.tabs([f"Sayfa {i} · Belge", f"Sayfa {i} · Metin"])
            with image_tab:
                has_marks = markings and any(location["page"] == i for location in markings["locations"])
                st.image(markings["images"][i-1] if markings else base64.b64decode(page["image"]), caption=f"Sayfa {i} · Kırmızı alanlar şekil bulgularını gösterir." if has_marks else f"Sayfa {i}")
            with text_tab:
                if result:
                    reading = next(p for p in result["review"]["pages"] if p["page"] == i)
                    st.markdown(marked_text(reading["text"], result["review"]["checks"], i), unsafe_allow_html=True)
                else:
                    st.info("İncelemeden sonra okunan metin ve işaretler burada görünecek.")
        if markings:
            for missing in markings["missing"]:
                st.warning(f"Kontrol {missing['number']} · Sayfa {missing['page']}: {missing['reason']}. Belgeye konum işareti eklenmedi; sağdaki açıklamayı inceleyin.")
            if markings["locations"]:
                st.download_button("İşaretli PDF’yi indir", markings["pdf"], file_name="onerge-isaretli.pdf", mime="application/pdf")
    with right:
        if result:
            render_report(result)
        else:
            st.subheader("İnceleme Sonucu")
            st.info("Belge hazır. İncelemeyi başlattığınızda bulgular bu alanda gösterilecek.")


def render_status_summary(checks):
    statuses = ("uygun", "uyari", "belirsiz")
    counts = [sum(check["status"] == status for check in checks) for status in statuses]
    for col, label, status, count in zip(st.columns(3), ("✓ Uygun", "✕ Sorunlu", "? Kontrol Gerekli"), statuses, counts):
        tone = status if count else "neutral"
        col.markdown(f'<div class="status-card {tone}"><div>{label}</div><div class="status-count">{count}</div></div>', unsafe_allow_html=True)
    missing_source = sum(c["status"] == "kaynak_yok" for c in checks)
    if missing_source:
        st.caption(f"Kaynakta kayıt yok: {missing_source} kontrol. Bu alanlar gri gösterilir; uygun sayılmaz.")
    if len(checks) == 6 and counts[0] == 6:
        st.success("Şekli bakımdan tüm koşullara uygundur.")


def render_report(result):
    review = result["review"]
    st.subheader("İnceleme Sonucu")
    summary = html.escape(review["summary"] or "Özet doğrulanamadı.")
    st.markdown(f'<div class="summary-card"><div class="summary-title">Önerge Özeti Önerisi</div><p>{summary}</p></div>', unsafe_allow_html=True)
    st.info("İçtüzük ve kesin iade kuralları henüz tanımlı değil; bu rapor hukuki karar içermez.")
    for warning in result["warnings"]:
        st.warning(warning)
    labels = {"hitap": "Hitap", "milletvekili": "Milletvekili", "secim_cevresi": "Seçim çevresi", "muhatap": "Muhatap", "talep": "Talep", "harf": "Harf / yazım"}
    statuses = {"uygun": "Uygun", "uyari": "Hatalı", "belirsiz": "Kontrol Gerekli", "kaynak_yok": "Kaynakta kayıt yok"}
    symbols = {"uygun": "✓", "uyari": "✕", "belirsiz": "?", "kaynak_yok": "—"}
    for number, check in enumerate(review["checks"], 1):
        state = check["status"]
        quote = '<blockquote>' + html.escape(check["quote"]) + '</blockquote>' if check["quote"] else ''
        st.markdown(f'<div class="check-card {state}"><div class="check-heading"><span>{number}. {labels[check["kind"]]}</span><span>{symbols[state]} {statuses[state]}</span></div><p>Sayfa {check["page"]} · {html.escape(check["explanation"])}</p>{quote}</div>', unsafe_allow_html=True)
    audit = result.get("recipient_audit")
    if audit:
        with st.expander("Bakan kontrolünde kullanılan liste ve okumalar"):
            st.caption("Bu raporda yalnızca aşağıdaki kullanıcı listesi kullanıldı. Excel’deki geçmiş bakan isimleri kullanılmaz.")
            for title, name in audit["reference"].items():
                st.text(f"{title} — {name}")
            for label, records in (("Görüntüden okunan muhatap", audit["vision"]), ("PDF/OCR üzerinden okunan muhatap", audit["comparison"])):
                st.write(label)
                for entry in records:
                    st.text(f"Sayfa {entry['page']}: {entry['title']} — {entry['name']}")
                if not records:
                    st.text("Bu okumada açık bir muhatap eşleşmesi bulunamadı.")
            st.caption("Kontrol sürümü: " + result.get("analysis_version", "belirtilmemiş"))
    states = {"uyumlu": "Metinler uyumlu", "uyusmazlik": "Metinler farklı", "ocr_yok": "Karşılaştırma metni yok", "belirsiz": "Okuma belirsiz"}
    for comparison in result["comparisons"]:
        with st.expander(f"Sayfa {comparison['page']} — {states[comparison['state']]}"):
            st.text("Görüntüden okunan metin")
            st.text(comparison["vision"])
            st.text("Bağımsız OCR okuması" if comparison.get("ocr_source") == "tesseract" else "PDF metin katmanı")
            st.text(comparison["ocr"] or "Yok")
            for uncertainty in comparison["uncertainties"]:
                st.text(uncertainty)
            if comparison["diff"]:
                st.code(comparison["diff"], language="diff")
    document_id = result.get("document_sha256", "belge")[:8]
    st.download_button("Raporu indir (JSON)", json.dumps(result, ensure_ascii=False, indent=2),
                       file_name=f"onerge-raporu-{RELEASE}-{document_id}.json", mime="application/json")


if __name__ == "__main__":
    main()
