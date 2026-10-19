# Önerge İnceleme

Yazılı soru önergesi PDF'lerini görüntüden okuyup mevcut PDF metin katmanıyla karşılaştıran, kullanıcı kurallarına göre şekil incelemesi yapan özel geliştirme uygulaması.

## Streamlit ile özel kullanım

Streamlit Community Cloud için giriş dosyası `streamlit_app.py`, dal `codex/onerge-inceleme`, Python sürümü **3.12**. Bağımlılıklar `uv.lock` ve ondan üretilen `requirements.txt` ile sabitlenmiştir.

1. https://share.streamlit.io adresinde GitHub hesabınızı bağlayın, **Create app** seçin.
2. Depo: `namiataturkcan/denetim-yazilisoru`; dal: `codex/onerge-inceleme`; giriş dosyası: `streamlit_app.py`.
3. **Advanced settings** içinde Python 3.12 seçin. **Secrets** alanına aşağıdaki iki adı kendi değerlerinizle ekleyin. Örnek metinleri gerçek değer olarak kullanmayın.

```toml
ONERGE_DIRECT_API_KEY = "OPENAI_ANAHTARINIZ"
APP_PASSWORD = "UZUN_VE_BENZERSIZ_ERISIM_PAROLANIZ"
```

4. **Deploy** ile yayımlayın. Uygulamanın paylaşım ayarlarında erişimi özel tutun ve yalnızca kendi hesabınıza izin verin. Streamlit'in verdiği adres uygulama bağlantınızdır.
5. Uygulamada `APP_PASSWORD` ile giriş yapıp bir örnek PDF yükleyin. API anahtarını giriş parolası olarak kullanmayın.

API anahtarı Codex'ten Streamlit'e otomatik taşınmaz; yalnızca Streamlit Secrets alanına girilir. Secrets dosyası Git'e eklenmez. Parola tanımlanmadan uygulama belge yüklemeyi açmaz; çıkışta oturumdaki belge ve rapor temizlenir. Yeni dosya seçilince önceki rapor kaldırılır. Yeniden analiz yalnızca düğmeye basıldığında ücretli API isteği yapar. Belgeler ve raporlar uygulama tarafından diske veya ortak önbelleğe yazılmaz; oturum belleğinde tutulur.

Yerel Streamlit çalıştırma (ortam değişkenleri veya gitignore kapsamındaki `.streamlit/secrets.toml` ile):

```sh
uv run --frozen streamlit run streamlit_app.py --server.address 127.0.0.1
```

Streamlit dağıtımı henüz kullanıcının hesabında yapılmadı; kod hazırlığı bir site yayını değildir.

## FastAPI geliştirme sunucusunu çalıştırma

Python 3.12+ ve `uv` gerekir. Depo klasöründe:

```sh
export UV_CACHE_DIR=/tmp/uv-cache
uv sync --frozen
uv run --frozen uvicorn app:app --host 127.0.0.1 --port 8000
```

Sunucu iki yapılandırma yolunu destekler: doğrudan **Ortam değişkenleri** bölümünde `ONERGE_DIRECT_API_KEY`, veya **Ağ gizli anahtarları** bölümünde `ONERGE_API_KEY` (hedef `api.openai.com`). Doğrudan değişkenin değeri sunucu sürecine verilir; ağ gizli anahtarında gerçek değer HTTPS proxy tarafından uygulanır. Bu iki tür için aynı değişken adını kullanmayın. Var olan `OPENAI_API_KEY` de desteklenir.

Öncelik sırası: `ONERGE_DIRECT_API_KEY`, `ONERGE_API_KEY`, `OPENAI_API_KEY`. Seçilen bağlantı reddedilirse başka anahtara otomatik geçilmez. `/api/health` yalnızca seçilen değişkenin adını bildirir, değerini göstermez. Doğrudan değişken seçeneği, ağ anahtarı aktarımıyla ilgili sorunu ayırmak için kullanılabilir; bu yol canlı API isteği ve örnek PDF analiziyle doğrulanmıştır.

`.env.example` açıklama içindir; `.env` otomatik yüklenmez. Değeri yalnızca özel çalışma ortamının ayarlarından girin; doğrudan değişken programlar tarafından okunabilir. Anahtarı Git'e, sohbet mesajına veya uygulamanın kullanıcı arayüzüne koymayın. `ONERGE_MODEL` varsayılan olarak `gpt-4.1` kullanır; görsel girdi ve yapılandırılmış çıktı destekleyen erişilebilir bir modelle değiştirilebilir. API kullanımı ayrıca ücretlendirilir.

FastAPI geliştirme sunucusu yalnızca loopback adresine bağlanır ve kullanıcı girişi içermez. Web yayını için yukarıdaki parola korumalı Streamlit girişini kullanın. GitHub deposu uygulama sunucusu değildir. Ortamı yayımlamak da otomatik olarak bir web sitesi yayımlamaz. Dış erişim açmadan önce kimlik doğrulamalı barındırma kurulmalıdır; `--host 0.0.0.0` ile korumasız açmayın.

## İşleyiş ve sınırlar

- En fazla 12 MB / 10 sayfa PDF kabul edilir. Şifreli ve bozuk dosyalar reddedilir.
- Sayfalar bellekte PNG olarak hazırlanır (uzun kenar en fazla 2200 piksel). Orijinal görüntü arayüzde gösterilir. Bu ölçek küçültme çok küçük yazılarda doğruluğu sınırlayabilir.
- Modele yalnızca görüntüler gönderilir. PDF metin katmanı, görsel okumayı etkilememesi için gönderilmez; sonradan metin karşılaştırması yapılır. Metin katmanı bulunmaması OCR uyumu olarak gösterilmez. Metin katmanı olmayan sayfalarda Tesseract ile bağımsız OCR denenir; bu okuma modele gönderilmez. OCR elde edilemezse karşılaştırma yokluğu açıkça gösterilir.
- Özgün metin, belirsizlikler, iki okumanın farkı ve sayfa/alıntı içeren altı şekil kontrolü gösterilir. Uyum hatasızlık garantisi değildir. Belirsizlik yalnızca ilgili kontrol alanını etkiler; başka yerdeki okunamayan kaşe veya imza tüm sonuçları belirsiz yapmaz. İlgili alandaki anlamlı sözcük farkları insan kontrolüne bırakılır; boşluk, noktalama ve OCR kaynaklı basit aksan farkları buna dahil değildir.
- Özet, kullanıcının Excel’indeki üsluba göre çoğunlukla 6–14 kelimelik nötr bir konu tamlamasıdır ve “ilişkin” ile biter. Excel’deki en uzun örnek esas alınarak üst sınır 31 kelimedir. İddialar olguya dönüştürülmez; gereksiz yer/tarih/kurum bilgileri eklenmez.
- `rules.json` içindeki 18 kişilik muhatap listesi kullanıcının listesidir; dışarıdan güncellenmez. İçtüzük 67/96/97 uygulama kuralları ve kesin iade ibareleri henüz eklenmemiştir. Özet üslup örnekleri `summary_style.json` içindedir.
- Belge ve rapor sunucuda kalıcı olarak saklanmaz; istek bellekte işlenir. Kullanıcı raporu JSON olarak indirebilir. `store:false` kullanılır; bu ayar ZDR değildir ve API hizmetinin diğer saklama koşullarını kaldırmaz.
- Aynı anda bir inceleme yapılır. Eksik anahtar, kota, erişim ve ağ hataları arayüzde açıkça gösterilir.

## Doğrulama

```sh
export UV_CACHE_DIR=/tmp/uv-cache
uv run --frozen pytest -q
node --check static/app.js
curl --fail http://127.0.0.1:8000/api/health
```

Testler PDF işleme, boyut/sayfa sınırları, belirsizlik, kaynak alıntısı, rapor doğrulama ve HTTP üzerinden gerçek SDK'nın sahte API yanıtıyla çalışmasını kontrol eder. Gerçek modele yapılan doğruluk veya bağlantı testi değildir. Canlı doğrulamada hassas olmayan bir örnek PDF ile analiz tamamlanmalı; rapor belgenin görüntüsüyle karşılaştırılmalıdır. Sağlık yanıtındaki `api_configured` yalnızca değişken varlığını gösterir, anahtarın kabul edildiğini göstermez.

## Belge üzerindeki işaretler

Streamlit arayüzünde ✓ yeşil uygunluk, ✕ kırmızı şekil bulgusu, ? sarı belirsizlik kartları kullanılır. Kesin olmayan okumalar hata olarak boyanmaz. Belge ve Metin sekmeleri aynı rapordaki hata alıntılarını kırmızı gösterir. Özgün PDF değiştirilmez; işaretli ayrı kopya indirilebilir.

Belge koordinatları PDF metin katmanındaki alıntı eşleşmesinden bulunur; bulunamazsa Tesseract OCR denenir. `packages.txt`, Streamlit Cloud'a Türkçe/İngilizce OCR paketlerini kurdurur. Yerel OCR paketleri yoksa işaret konumu bulunamadığı açıkça gösterilir; uygulama tahmini koordinat çizmez. OCR konum bulma ve bağımsız okuma karşılaştırması içindir; modele gönderilmez. Boş/eksik bir alan belgede mevcut olmadığından konumla işaretlenemez; açıklama kartında gösterilir. Yinelenen alıntının tüm eşleşmeleri işaretlenebilir. İşaretler otomatik bulgudur, insan incelemesi gerekir.

Önceki konuşmadaki özel işaret listesine erişilemediği için bu üç simge dışında özel işaret anlamı eklenmemiştir. Güncellemeden sonra işaretleri görmek için belgeyi yeniden inceleyin.

## Muhatap eşleşmesinin doğrulanması

Model değerlendirmesinden sonra, açık unvan–isim ifadeleri kullanıcı listesindeki eşleşmeyle kod üzerinden karşılaştırılır. Örneğin listede İçişleri Bakanı Mustafa ÇİFTÇİ iken belgede “İçişleri Bakanı Ali Yerlikaya tarafından…” yazıyorsa model uygun dese bile sonuç uyarı olur; özgün ifade kırmızı işaretleme için korunur. Türkçe büyük/küçük harfler, Sayın, satır sonları ve yaygın kesme işareti ekleri desteklenir. Birden fazla muhatap veya ayrıştırılamayan ifade otomatik uygun kabul edilmez. Okuma belirsizliği insan kontrolüne bırakılır. Bu kontrol görüntüden aktarılan metne dayanır; modelin metni yanlış okumasını bütünüyle önlemez. Kullanıcı listesi esas alınır; internetten güncel görevli bilgisi çekilmez.

## Kullanıcının Excel kaynağı (19.10.2026)

`KKBS_YazılıOnerge_Rapor_19-10-2026 09_27.xlsx` dosyasındaki 50.416 kayıt incelendi; tamamı 28. döneme ait. `Soru Sahibi` ve `Soru Sahibi İli` alanlarından 312 farklı, çelişkisiz eşleşme `member_reference.json` içine alındı. Bu döküm tüm milletvekillerini veya aktif görev durumlarını kapsamaz. Kaynakta bulunmayan isimler tahmin edilmez: gri **Kaynakta kayıt yok** sonucuyla gösterilir ve uygun sayılmaz. Eksik kaynak, OCR belirsizliği olarak adlandırılmaz.

Seçim çevresi kontrolü, imza alanından birebir okunan isim ve ili karşılaştırır. İstanbul yerine Diyarbakır yazılması gereken bir üyede yanlış il kırmızı uyarıdır. Kullanıcının açık talimatı gereği Dersim, Tunceli'nin eş anlamlısı kabul edilmez. Belgede geçen konu/olay yerleri seçim çevresi olarak kullanılmaz. Çok imzalı belgelerde her imza kontrol edilir; tek seçim çevresi kartında bütün sonuçlar açıklanır, ilk kesin hata vurgulanır.

Excel'in tarihsel bakan isimleri muhatap listesine alınmamıştır; bakan kontrolü yalnızca `rules.json` içindeki kullanıcı listesiyle yapılır. Ham Excel ve tüm önerge dökümü depoya eklenmez. Gerekli ad–il eşleşmeleri, kaynak dosyanın SHA-256 değeri, üslup istatistikleri ve 22 temsili özet örneği tutulur. Kaynakları yeniden üretmek için openpyxl kurulu Python ile `python scripts/import_reference_workbook.py DOSYA.xlsx` kullanılabilir; farklı dönem veya çelişkili kayıtlar otomatik olarak güncel kabul edilmez.

Özet analizinde medyan 10, yüzde 90 eşiği 14, maksimum 31 kelime bulundu; 19.766 özet 10 kelimeden uzundu. Örnekler sadece üslup içindir, belgeye dış bilgi eklemek için kullanılmaz. Yeni kaynaklarla güncelleme yapıldığında belgeyi yeniden analiz edin; eski raporlar kendiliğinden yeniden değerlendirilmez.

Bakan adlarını okuma aşaması, doğrulama listesinden ayrıdır: model beklenen bakan isimlerini görmez; görüntüden birebir okuma yapar, sonuç kodda kullanıcı listesiyle karşılaştırılır. PDF/OCR'den ayrıca çıkarılan açık muhatap farklıysa uygun onayı engellenir. Kullanılan listenin kopyası ve iki okuma raporun `recipient_audit` alanında ve arayüzdeki “Bakan kontrolünde kullanılan liste ve okumalar” bölümünde bulunur. Bakan kontrolünün sürümü değiştiğinde ekranda kalmış eski rapor kaldırılır; yeniden analiz gerekir. Kullanıcının yeniden teyit ettiği eşleşmeler İçişleri Mustafa ÇİFTÇİ ve Adalet Akın GÜRLEK'tir.
