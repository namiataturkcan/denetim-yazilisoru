"""Password-protected Streamlit interface; documents stay in session memory."""
import asyncio
import base64
import hashlib
import hmac
import json
import os

import streamlit as st
from fastapi import HTTPException
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app import MAX_BYTES, analyze, finalize, prepare_pdf


def setting(name, default=""):
    try:
        return str(st.secrets.get(name, os.environ.get(name, default)))
    except FileNotFoundError:
        return os.environ.get(name, default)


def main():
    st.set_page_config(page_title="Önerge İnceleme", page_icon="📄", layout="wide")
    st.title("Önerge İnceleme")
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
    if st.sidebar.button("Çıkış yap"):
        st.session_state.clear()
        st.rerun()
    key = setting("ONERGE_DIRECT_API_KEY") or setting("ONERGE_API_KEY") or setting("OPENAI_API_KEY")
    if not key:
        st.error("Analiz bağlantısı henüz yapılandırılmadı.")
        st.stop()
    st.caption("En fazla 12 MB, 10 sayfa PDF. Analiz sırasında sayfa görüntüleri OpenAI'a gönderilir. Sonuçları belgeyle karşılaştırarak kontrol edin.")
    uploaded = st.file_uploader("Önerge PDF’sini yükle", type=["pdf"])
    if uploaded is None:
        for name in ("document", "pages", "result"):
            st.session_state.pop(name, None)
        st.info("Başlamak için bir önerge PDF’si seçin.")
        st.stop()
    data = uploaded.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    if st.session_state.get("document") != digest:
        st.session_state.pop("result", None)
        st.session_state.pop("pages", None)
        st.session_state["document"] = digest
        try:
            if len(data) > MAX_BYTES:
                raise HTTPException(413, "Dosya sınırı 12 MB.")
            st.session_state["pages"] = prepare_pdf(data)
        except HTTPException as exc:
            st.error(exc.detail)
            st.stop()
    pages = st.session_state.get("pages")
    if not pages:
        st.error("PDF okunamadı. Başka bir dosya seçin.")
        st.stop()
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Belge")
        for i, page in enumerate(pages, 1):
            st.image(base64.b64decode(page["image"]), caption=f"Sayfa {i}")
    with right:
        if st.button("İncelemeyi başlat", type="primary"):
            st.session_state.pop("result", None)
            try:
                with st.spinner("Belge okunuyor ve kontroller yapılıyor…"):
                    review = asyncio.run(analyze(pages, credential=key, model=setting("ONERGE_MODEL", "gpt-4.1")))
                    result = finalize(review, pages)
                    result["document_sha256"] = digest
                    st.session_state["result"] = result
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
        if result:
            render_report(result)


def render_report(result):
    review = result["review"]
    st.subheader("İnceleme sonucu")
    st.text(review["summary"] or "Özet doğrulanamadı.")
    st.info("İçtüzük ve kesin iade kuralları henüz tanımlı değil; bu rapor hukuki karar içermez.")
    for warning in result["warnings"]:
        st.warning(warning)
    labels = {"hitap": "Hitap", "milletvekili": "Milletvekili", "secim_cevresi": "Seçim çevresi", "muhatap": "Muhatap", "talep": "Talep", "harf": "Harf / yazım"}
    statuses = {"uygun": "Uygun", "uyari": "Uyarı", "belirsiz": "İnsan kontrolü gerekli"}
    for check in review["checks"]:
        st.write(f"**{labels[check['kind']]} — {statuses[check['status']]}**")
        st.text(f"Sayfa {check['page']}: {check['explanation']}")
        if check["quote"]:
            st.text(check["quote"])
    states = {"uyumlu": "Metinler uyumlu", "uyusmazlik": "Metinler farklı", "ocr_yok": "PDF metin katmanı yok", "belirsiz": "Okuma belirsiz"}
    for comparison in result["comparisons"]:
        with st.expander(f"Sayfa {comparison['page']} — {states[comparison['state']]}"):
            st.text("Görüntüden okunan metin")
            st.text(comparison["vision"])
            st.text("PDF metin katmanı")
            st.text(comparison["ocr"] or "Yok")
            for uncertainty in comparison["uncertainties"]:
                st.text(uncertainty)
            if comparison["diff"]:
                st.code(comparison["diff"], language="diff")
    st.download_button("Raporu indir (JSON)", json.dumps(result, ensure_ascii=False, indent=2),
                       file_name="onerge-raporu.json", mime="application/json")


if __name__ == "__main__":
    main()
