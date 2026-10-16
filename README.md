# Önerge İnceleme

Yazılı soru önergesi PDF'lerini görüntüden okuyup mevcut PDF metin katmanıyla karşılaştıran, kullanıcı kurallarına göre şekil incelemesi yapan özel geliştirme uygulaması.

## Çalıştırma

Python 3.12+ ve `uv` gerekir. Depo klasöründe:

```sh
export UV_CACHE_DIR=/tmp/uv-cache
uv sync --frozen
uv run --frozen uvicorn app:app --host 127.0.0.1 --port 8000
```

`ONERGE_API_KEY` değerini çalıştırma ortamının gizli ayarlarında tanımlayın. Kod mevcut `OPENAI_API_KEY` değişkenini de kullanabilir. `.env.example` açıklama içindir; `.env` otomatik yüklenmez. Anahtarı Git'e, sohbet mesajına veya tarayıcıya koymayın. `ONERGE_MODEL` varsayılan olarak `gpt-4.1` kullanır; görsel girdi ve yapılandırılmış çıktı destekleyen erişilebilir bir modelle değiştirilebilir. API kullanımı ayrıca ücretlendirilir.

Bu sürüm yalnızca loopback adresine bağlanır; kullanıcı girişi ve yayımlama kurulmamıştır. GitHub deposu uygulama sunucusu değildir. Ortamı yayımlamak da otomatik olarak bir web sitesi yayımlamaz. Dış erişim açmadan önce kimlik doğrulamalı barındırma kurulmalıdır; `--host 0.0.0.0` ile korumasız açmayın.

## İşleyiş ve sınırlar

- En fazla 12 MB / 10 sayfa PDF kabul edilir. Şifreli ve bozuk dosyalar reddedilir.
- Sayfalar bellekte PNG olarak hazırlanır (uzun kenar en fazla 2200 piksel). Orijinal görüntü arayüzde gösterilir. Bu ölçek küçültme çok küçük yazılarda doğruluğu sınırlayabilir.
- Modele yalnızca görüntüler gönderilir. PDF metin katmanı, görsel okumayı etkilememesi için gönderilmez; sonradan metin karşılaştırması yapılır. Metin katmanı bulunmaması OCR uyumu olarak gösterilmez. Ayrı bir OCR motoru henüz yoktur.
- Özgün metin, belirsizlikler, iki okumanın farkı ve sayfa/alıntı içeren altı şekil kontrolü gösterilir. Uyum hatasızlık garantisi değildir. Okuma belirsizliği olan sayfadaki şekil sonuçları insan kontrolüne bırakılır.
- Özet en fazla 10 kelime olmalı ve “ilişkin” ile bitmelidir; kurala uymayan çıktı rapordan çıkarılarak uyarılır.
- `rules.json` içindeki 18 kişilik muhatap listesi kullanıcının listesidir; dışarıdan güncellenmez. İçtüzük 67/96/97 uygulama kuralları, kesin iade ibareleri ve Excel üslup örnekleri henüz eklenmemiştir.
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
