import hashlib
import json

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

import app as service


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch):
    monkeypatch.delenv("ONERGE_DIRECT_API_KEY", raising=False)
    monkeypatch.delenv("ONERGE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def client():
    with TestClient(service.app) as c:
        yield c


def pdf(count=1):
    with pymupdf.open() as doc:
        for _ in range(count):
            doc.new_page().insert_text((72, 72), "Reference text 10")
        return doc.tobytes()


def report():
    return service.Review(
        pages=[service.PageReading(page=1, text="Görüntü metni", uncertainties=[])],
        checks=[service.Check(kind=k, status="uygun", page=1, quote="Görüntü metni", explanation="Dayanak kontrolü")
                for k in ("hitap", "milletvekili", "secim_cevresi", "muhatap", "talep", "harf")],
        summary="Kamu personeli alımlarına ilişkin")


def post(client, data):
    return client.post("/api/review", content=data, headers={"Content-Type": "application/pdf"})


def test_health_and_ui_without_key(client):
    h = client.get("/api/health")
    assert h.status_code == 200
    assert h.json()["api_configured"] is False
    assert "no-store" in h.headers["cache-control"]
    assert "Yazılı Soru Önergesi İncelemesi" in client.get("/").text
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/rules.json").status_code == 404
    assert post(client, pdf()).status_code == 503


def test_direct_binding_takes_priority_without_exposing_values(client, monkeypatch):
    monkeypatch.setenv("ONERGE_DIRECT_API_KEY", "direct-test-only")
    monkeypatch.setenv("ONERGE_API_KEY", "network-test-only")
    assert service.api_key() == "direct-test-only"
    h = client.get("/api/health")
    assert h.json()["api_key_source"] == "ONERGE_DIRECT_API_KEY"
    assert "direct-test-only" not in h.text
    assert "network-test-only" not in h.text


def test_empty_direct_binding_preserves_existing_network_binding(client, monkeypatch):
    monkeypatch.setenv("ONERGE_DIRECT_API_KEY", "")
    monkeypatch.setenv("ONERGE_API_KEY", "network-test-only")
    assert service.api_key() == "network-test-only"
    assert client.get("/api/health").json()["api_key_source"] == "ONERGE_API_KEY"


@pytest.mark.parametrize("data,status", [(b"not a PDF",400),(b"%PDF-broken",400),(b"a"*(service.MAX_BYTES+1),413)])
def test_invalid_inputs(client, monkeypatch, data, status):
    monkeypatch.setenv("ONERGE_API_KEY", "test-only")
    assert post(client, data).status_code == status


def test_too_many_pages(client, monkeypatch):
    monkeypatch.setenv("ONERGE_API_KEY", "test-only")
    assert post(client, pdf(11)).status_code == 400


def test_cross_origin_and_bad_host_rejected(client):
    assert client.post("/api/review", headers={"Origin":"https://unrelated.example"}).status_code == 403
    assert client.get("/api/health", headers={"Host":"unrelated.example"}).status_code == 400


def test_rendering_and_independent_text():
    pages = service.prepare_pdf(pdf())
    assert "Reference text 10" in pages[0]["ocr"]
    assert len(pages[0]["image"]) > 100


def test_preview_without_key(client):
    response=client.post("/api/preview",content=pdf(),headers={"Content-Type":"application/pdf"})
    assert response.status_code == 200
    assert len(response.json()["images"]) == 1
    assert response.json()["images"][0].startswith("iVBOR")


def test_encrypted_pdf_rejected(client, monkeypatch):
    monkeypatch.setenv("ONERGE_API_KEY", "test-only")
    with pymupdf.open() as d:
        d.new_page()
        data=d.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="reader")
    assert post(client,data).status_code == 400


def test_uncertainty_invalid_evidence_and_summary():
    r=report()
    r.pages[0].uncertainties=["Ad okunamadı"]
    r.summary="Geçersiz özet"
    result=service.finalize(r,[{"ocr":"different"}])
    assert result["review"]["summary"] == ""
    assert all(c["status"] == "belirsiz" for c in result["review"]["checks"])
    assert result["comparisons"][0]["state"] == "belirsiz"
    r=report();r.checks[0].quote="Uydurma alıntı"
    assert service.finalize(r,[{"ocr":""}])["review"]["checks"][0]["status"] == "belirsiz"


@pytest.mark.parametrize("ocr,state", [("Görüntü metni","uyumlu"),("Görüntü  metni\n","uyumlu"),("","ocr_yok"),("Başka metin","uyusmazlik")])
def test_comparison_states(ocr,state):
    result=service.finalize(report(),[{"ocr":ocr}])
    assert result["comparisons"][0]["state"] == state


def test_incomplete_report_rejected():
    r=report();r.pages=[]
    with pytest.raises(service.HTTPException) as e:
        service.finalize(r,[{"ocr":""}])
    assert e.value.status_code == 502


@pytest.mark.parametrize("key_name", ["ONERGE_API_KEY", "ONERGE_DIRECT_API_KEY"])
def test_full_http_pipeline_with_mocked_openai(client, monkeypatch, key_name):
    monkeypatch.setenv("ONERGE_API_KEY", "network-decoy")
    monkeypatch.setenv(key_name, "test-only")
    captured=[]
    def respond(request):
        assert request.headers["Authorization"] == "Bearer test-only"
        body=json.loads(request.content);captured.append(body)
        return httpx.Response(200,json={"id":"resp_test","object":"response","created_at":0,
            "model":"gpt-4.1","status":"completed","error":None,"incomplete_details":None,
            "output":[{"id":"msg_test","type":"message","role":"assistant","status":"completed",
                       "content":[{"type":"output_text","text":report().model_dump_json(),"annotations":[]}]}]})
    def fake_client(**kwargs):
        return AsyncOpenAI(**kwargs,http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(service,"AsyncOpenAI",fake_client)
    data=pdf();response=post(client,data)
    assert response.status_code == 200,response.text
    assert response.json()["document_sha256"] == hashlib.sha256(data).hexdigest()
    assert response.json()["comparisons"][0]["state"] == "uyusmazlik"
    assert response.json()["internal_rules"] == "tanımlanmadı"
    assert "Mustafa ÇİFTÇİ" not in captured[0]["instructions"]
    assert "Akın GÜRLEK" not in captured[0]["instructions"]
    assert captured[0]["store"] is False
    assert captured[0]["text"]["format"]["strict"] is True
    assert "Reference text 10" not in json.dumps(captured[0])
    assert captured[0]["input"][0]["content"][1]["type"] == "input_image"


def test_upstream_failure_is_safe(client,monkeypatch):
    monkeypatch.setenv("ONERGE_API_KEY","test-only")
    def fake_client(**kwargs):
        def reject(request):
            return httpx.Response(401,json={"error":{"message":"sensitive-upstream-text"}})
        return AsyncOpenAI(**kwargs,http_client=httpx.AsyncClient(transport=httpx.MockTransport(reject)))
    monkeypatch.setattr(service,"AsyncOpenAI",fake_client)
    result=post(client,pdf())
    assert result.status_code == 502
    assert "kimliğini doğrulayamadı" in result.text
    assert "sensitive-upstream-text" not in result.text
