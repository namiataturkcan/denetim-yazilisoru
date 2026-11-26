# Yazılı Soru İşlemleri

Parola korumalı Streamlit uygulaması, girişten sonra üç işlem sunar: **Yazılı Soru Önergesi İncelemesi**, **Gelen Kağıt İşlemleri** ve **İkinci Okuyucu İşlemleri**. Önerge incelemesinde tekli/toplu PDF kontrolü; ikinci okuyucu bölümünde EBYS–KKBS giriş karşılaştırması bulunur. Gelen Kağıt İşlemleri, Excel veya yapıştırılan tablo üzerinden cevaplanmamış önerge aralıklarını ve muhatapları hesaplar.

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

Mevcut uygulama: https://denetim-yazilisoru.streamlit.app/. GitHub dalına gönderilen güncellemenin Streamlit tarafından alınması gerekir. Açılış ekranındaki sürüm bilgisi yeni yayını ayırt etmek içindir; gerektiğinde Streamlit yönetiminden Reboot yapılır.

### Arayüz sürümü ve görünüm

Arayüz sürümü `ui_theme.py` içindeki `UI_RELEASE` ile gösterilir. Analiz/karşılaştırma sürümlerinden ayrıdır: yalnız görsel bir güncelleme tamamlanmış incelemeyi geçersiz kılmaz ve yeniden ücretli analiz istemez. Kural veya kaynak değişikliklerinin mevcut doğrulama mekanizması devam eder.

Giriş, ana menü ve üç işlem alanı aynı renk, yazı, düğme, yükleme ve sonuç kutusu düzenini kullanır. Yeşil/kırmızı/sarı/gri anlamları korunur; sayı ve açıklamalar renge ek olarak gösterilir. Küçük ekranlarda menü kartları alt alta, sonuç sayaçları ikili düzende görünür; tablolar kendi yatay kaydırma alanını kullanır. Klavye odağı belirgindir ve azaltılmış hareket tercihi desteklenir.

Görsel katman harici yazı tipi, ikon servisi veya ek JavaScript bağımlılığı yüklemez. Statik CSS dosyası değişiklik zamanına göre küçük bir önbellekten okunur; bu önbellekte belge veya kullanıcı verisi tutulmaz. Yükleme alanlarının sınırları, işlem düğmeleri, rapor içerikleri ve oturumdaki sorgu listeleri görsel katmandan bağımsızdır.

## İkinci Okuyucu İşlemleri · EBYS–KKBS giriş karşılaştırması

Ana menüden **İkinci Okuyucu İşlemleri** seçilir. Aynı yükleme alanı dosya sayısına göre iki akışı destekler; ayrıca işlem türü seçmek gerekmez. API anahtarı gerekmez ve API kredisi tüketilmez. Her dosyanın sınırı 12 MB, sayfa başına kayıt sınırı 100.000'dir.

Uyuşmazlıklar PC tarayıcısı için iki sütunda gösterilir: **Evrak No** ve **Açıklama**. Açıklamaya tıklanınca tam KKBS ve EBYS metinleri yan yana iki kutuda açılır; farklı sözcükler kırmızı zeminle vurgulanır. Metinler kesilmez ve kutularda yatay/iç kaydırma gerekmez. Aynı evrağın bulguları tek satırda toplanır. Esas no, sonuç ve Excel satır numaraları bu görünümde yer almaz. Kontrol gerekli bulgular ayrı kapalı bölümde kalır; uyuşmazlık raporlarının bulguları korunur.

- **Okuma Sonrası Kontrolü:** KKBS ve EBYS raporlarının ayrı sayfalarda bulunduğu **tek birleşik .xlsx** dosyası yüklenir.
- **Okuma Öncesi Kontrolü:** KKBS ve EBYS'den alınan **iki ayrı ham .xlsx** dosyası aynı alana eklenir. Dosyaların yükleme sırası ve sayfa adlarının aynı olması sonucu değiştirmez. Kaynak dosyalar ve sayfalar otomatik önerilir; gerekirse değiştirilebilir. İlk ham dosya tek başına yüklendiğinde diğer dosya beklenir. Aynı dosyanın iki kez yüklenmesi, iki kaynağa aynı dosyanın atanması veya ikiden fazla dosya seçilmesi karşılaştırmayı başlatmaz.
- Ham EBYS raporunda **Barkod No**, KKBS'deki **Genel Evrak No** ile eşleştirilir; EBYS'deki farklı bir yazışma numarası içerebilen **Sayı** alanından önce tercih edilir. Milletvekili ve muhatap EBYS'nin **Konu**, KKBS'nin **Önerge Sahibi Özeti** alanından okunabilir. İki akış aynı karşılaştırma kurallarını kullanır. KKBS'de karşılığı bulunmayan EBYS evrakları silinmez; rapor kapsamı farkı olarak ayrı kontrol listesinde kalır.

- KKBS ve EBYS sayfaları seçilebilir. Başlık satırı ve ortak evrak numarası, milletvekili, bakanlık sütunları otomatik tanınır; **Sayfa ve sütunları kontrol et** bölümünde değiştirilebilir. İlk üç kaynak kayıt önizlenir. Aynı konu/özet sütununda hem vekil hem bakanlık varsa iki alan da o sütuna bağlanabilir. Örneğin `İstanbul Milletvekili Çiçek Otlu'nun, ... ilişkin Çevre Bakanı'ndan yazılı soru önergesi` ayrıştırılır. Esas numarası isteğe bağlıdır ve indirilen raporda korunur.
- Başlıksız EBYS dökümlerinde **başlık satırı 0** seçilir ve ilk kayıt atlanmaz. `Yazılı Soru … Mv./MV/Milletvekili …` biçimindeki asıl gelen evrak metni tanınır; yanındaki KKBS özet kopyası kaynak olarak kullanılmaz. Yardımcı esas/evrak listesi yerine EBYS metnini içeren sayfa önerilir. Aynı evrak numarası birden fazla sütunda tekrarlanıyorsa eşdeğer sütunlardan ilki seçilir; farklı numaralar varsa sütun seçimi istenir. Seçilen kaynak sütunları sonuç öncesinde görünür; algılanan asıl EBYS metni yerine kopya özet seçilmesi ve ilk kaydın başlık olarak atlanması engellenir.
- Kayıtlar yalnızca **ortak evrak numarasıyla** birebir eşleştirilir. Satır sırası veya kişi adına göre tahmini eşleştirme yapılmaz. Yıl/ön ek korunur: `2026/123` ile `123` birleştirilmez. Tekrarlanan, eksik veya diğer sayfada bulunmayan numaralar ayrı kontrol bulgusudur. Açıklaması boş kayıtlar da karşılaştırılır.
- Türkçe büyük/küçük harf ve aksan farkları normalleştirilir. **Çiçek Otlu / Cengiz Çiçek** farklı kişidir. Küçük yazım farkları yalnızca kaynaklarda tek yakın tam ad bulunduğunda uyumlu sayılır ve ayrı açılır listede açıklanır. Uzun adlarda bir sözcükte iki harfe kadar fark kabul edilirken diğer sözcükler aynı olmalıdır. `M. Sezgin Tanrıkulu` gibi baş harfi kısaltmaları da yalnızca kullanıcı referansı ve KKBS kaynağında tek tam ada karşılık geldiğinde açılır; belirsiz kısaltmalar veya soyadı baş harfi onaylanmaz. İki farklı bilinen kişi adı yazım hatası bahanesiyle birleştirilmez. Eksik veya ayrıştırılamayan adlar kontrol listesine alınır.
- Son ad/soyad bileşeni yazılmamışsa, en az iki sözcüklü başlangıcın kaynaklarda tek tam ada karşılık gelmesi gerekir; uzun başlangıçta en fazla bir harf farkına izin verilir. Kabul edilen kısaltma açıklanır. Kısa ad ayrıca farklı bir bilinen kişiye aitse birleştirilmez; birden fazla olası tam ad varsa kontrol gerekir.
- Bakanın tam adının bulunması zorunlu değildir: **Çevre Bakanı** ile **Çevre, Şehircilik ve İklim Değişikliği Bakanı Murat Kurum** aynı kurumdur; **Adalet Bakanı** farklıdır. Sadece bakan adı varsa kullanıcıya ait `rules.json` listesindeki tam adla eşleştirme denenir. Bakanlık açıkça yazılıysa o kurum esas alınır. Bu işlem güncel bakan kişisini doğrulamaz ve internetten yeni liste almaz.
- KKBS özetinde konu içinde anılan bakan, muhatapla karıştırılmaz. `… Aile Bakanı'nın açıklamasına ilişkin Sağlık Bakanı'ndan yazılı soru önergesi` için Sağlık Bakanlığı alınır. Bu açık muhatap tanınmıyorsa konu içinde geçen başka bir bakanlıkla doldurulmaz.
- Uyuşmazlıklar ana sonuçta kırmızı bildirimle; kaynaklardaki değerleri, evrak/esas numaraları, Excel satırları ve açıklamalarıyla gösterilir. Eksik/şüpheli bilgiler **Kontrol gerekli** altında, kabul edilen küçük yazım farkları başka bir açılır listede bulunur. İki alandaki sorunlar aynı evrakı uyuşmazlık sayacında iki kez saydırmaz. Eşleşme yoksa veya belirsizlik varsa tüm kayıtlar uygun gösterilmez.
- CSV ve JSON bütün bulguları içerir; ekrandaki tablolar ilk 500 bulguyu gösterir. JSON ayrıca işlem türünü (`before`/`after`), her kaynağın dosya adını ve SHA-256 değerini, sayfa/sütun seçimlerini (sütun indeksleri sıfırdan başlar), karşılaştırma ve referans sürümlerini içerir. CSV'de formül olarak yorumlanabilecek hücreler etkisizleştirilir.
- Dosya, sayfa, sütun veya başlık değiştiğinde önceki sonuç kaldırılır. Veriler oturum belleğinde tutulur; ortak önbelleğe/diske yazılmaz ve çıkışta temizlenir. Kesilen Excel okuması yeniden denenir. İki sistemde aynı yanlış bilgi varsa bu karşılaştırma onu tespit edemez; uyuşmazlığın hangi tarafta olduğunu belirlemek için önergenin aslı kullanılır.

Doğrulama: ilk sürümde gerçek KKBS `(55).xlsx` dosyasındaki 106 kayıt, yapay EBYS karşılığıyla test edildi. Sonrasında kullanıcının gerçek iki kaynaklı Excel dosyasıyla 116 KKBS kaydının tamamı 127 EBYS kaydı arasında eşleştirildi; 3 evrakta uyuşmazlık ve yalnız EBYS'de bulunan 11 kayıt saptandı. Başlıksız sayfa, kopyalanmış özet sütunu, yardımcı sayfa, baş harfi kısaltması, konu içinde anılan farklı bakan ve boş açıklama durumları regresyon testlerine **yapay verilerle** eklendi; gerçek dosyalar depoya konulmaz. Karışık satır sırası, eksik/tekrar numaralar ve oturum değişiklikleri de test edilir.

Ayrı ham `kkbs.xlsx` ve `ebys.xlsx` dosyalarıyla 140 KKBS kaydının tamamı 172 EBYS kaydı arasında eşleştirildi; EBYS'deki 32 ek kayıt ayrı gösterildi. Otomatik testler aynı verinin birleşik ve ayrı dosyalarda aynı bulguları üretmesini, ters yükleme sırasını, aynı sayfa/dosya adlarını, ikinci dosyanın değiştirilmesini veya kaldırılmasını, kesilen okumayı ve eski menü oturumunun yeni bölüme taşınmasını kapsar.

### KKBS özetlerinde yazım önerileri

Sağdaki sarı sayaç **Yazım önerisi** sayısını gösterir. Kayıt eşleştirmesindeki eski kontrol bulgusu sayısı ve eşleşmeyen kayıtlar, sonuçların altında not olarak belirtilir; ayrıntıları kapalı kontrol listesinden açılır. Yazım önerileri uyuşmayan evrakların altında **Evrak No / Olan / Olması gereken** tablosunda gösterilir. Öneri sayısı ile etkilenen özet sayısı ayrı belirtilir.

Denetim yalnız **KKBS’nin asıl özet cümlesine** uygulanır; EBYS metinleri, otomatik milletvekili–seçim çevresi bilgisi, muhatap ve geliş tarihi denetlenmez. `Özet` veya `Önerge Sahibi Özeti` gibi sütunlar otomatik bulunur; sütun ayarlarından değiştirilebilir. Birleşik hücrede özet, sahip bilgisinden sonraki virgül ile doğrulanmış muhatap/yazılı soru son eki arasından ayrılır. Sınırın bulunması doğru yazılmış “ilişkin” sözcüğüne bağlı değildir; iç metinde geçen “ilişkin” sözcükleri özeti kesmez. Sınırlar güvenle belirlenemezse o kayıt için yazım onayı verilmez, atlanan evraklar rapora yazılır. Boş veya seçilmemiş özet sütunu “hatasız” sayılmaz. Eşleşmeyen KKBS kayıtlarının özetleri de denetlenir.

Yerel denetim fazla boşlukları, belirli yaygın yanlış yazımları, kurum adlarında kesmeyi ve makam/bağlaç yazımını kapsar. Kişi adlarının doğruluğunu araştırmaz; ilçe adları aşağıda açıklanan kullanıcı PDF’siyle ayrıca denetlenir. Genel bir dil bilgisi çözümleyicisi değildir. Kurallar **20 Kasım 2026** tarihinde [TDK Güncel Türkçe Sözlük](https://sozluk.gov.tr/), [kesme işareti](https://tdk.gov.tr/icerik/yazim-kurallari/kesme-isareti/) ve [büyük harf kuralları](https://tdk.gov.tr/icerik/yazim-kurallari/buyuk-harflerin-kullanildigi-yerler/) ile doğrulandı:

- Güncel sözlükte **ünvan** yazımı kullanılır; `unvan` ve ekli biçimleri için buna göre öneri üretilir.
- **25 Kasım 2026** tarihinde TDK sözlüğünden ayrıca doğrulanan `kayyum` maddesi `kayyım` biçimine yönlendirilir. `Kayyum / KAYYUM`, `kayyumun → kayyımın`, `kayyumluğuna → kayyımlığına` gibi biçimler ve ek uyumu da denetlenir; kişi/yer adı korumaları devam eder.
- `Sayıştay Başkanlığı'na → Sayıştay Başkanlığına`; kişi ünvanı olan `Türk Dil Kurumu Başkanı’na`, `TBMM’nin` gibi kısaltmalar ve `Avrupa Birliği’ne` istisnası değiştirilmez.
- `Bakan'ın → bakanın` gibi genel görev adı önerileri **bağlama bağlı** olarak etiketlenir; belirli kişinin adı yerine kullanılan makam adlarının büyük yazılabildiği açıklanır. `Sayın Bakan` veya kişi adına bağlı ünvanlar otomatik olarak küçültülmez.
- Ayrı yazılmış `bir çok / bir kaç / hiç bir`, `herşey / yada / pekçok`, `herkez / yalnış / yanlız` gibi tanımlı örnekler denetlenir. Alıntılar ve tanınan kişi/yer ifadeleri bu sözlük düzeltmelerinden korunur.

Asıl özetin **“ilişkin” ile bitmesi** ayrıca kontrol edilir. Bu, TDK sözlük üyeliğinden bağımsız bir KKBS işleyiş kuralıdır: “ilişki” sözlükte bulunsa da özetin sonunda uygun kabul edilmez. `ilişki / iliskin / ilişin / ilişkinn` gibi yakın yazımlar `ilişkin` olarak önerilir; sondaki noktalama da belirtilir. Bitiş farklıysa veya sözcük tamamen eksikse, yanlış bir hâl eki uydurmak yerine “… ilişkin” biçiminde editör düzenlemesi istenir. Boş/ayrılamayan özetler hâlâ not edilir ve denetlenmiş sayılmaz.

Kaynak Excel ve karşılaştırma bulguları değiştirilmez. Yazım önerileri ayrı CSV olarak ve ayrıntılı JSON raporunun `summary_review` alanında indirilir; eski karşılaştırma CSV’si aynı kalır. Kurallar için ayrı sürüm tutulur, sütun veya kural değişince oturum sonucu yenilenir. API ve ağ isteği yapılmaz; kredi tüketilmez.

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
- Aynı sunucu sürecinde, farklı Streamlit oturumları dahil, aynı anda bir ücretli inceleme yapılır. PDF işleme çağrıları süreç içinde sırayla çalıştırılır; farklı sunucu süreçleri ayrı sınırlara sahiptir. Eksik anahtar, kota, erişim ve ağ hataları arayüzde açıkça gösterilir.

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

## Kullanıcının milletvekili listesi (25.11.2026)

`KKBS - Kanunlar Kararlar Bilgi Sistemi (39).xlsx` dosyasındaki 600 adet 28. dönem ad–seçim çevresi eşleşmesi `member_reference.json` içine alındı. 599 farklı tam ad var; Mustafa DEMİR hem İstanbul hem Kilis için ayrı kayıt olarak korunur. Kontrol ad ve il birlikte yapılarak aynı adlı kişiler birbirine karıştırılmaz. Kaynakta bulunmayan adlar tahmin edilmez ve uygun sayılmaz. Listede ayrılmış üyeler de vardır; bu kaynak görevde olma durumunu denetlemez.

Tekli ve toplu PDF incelemesindeki şekil kontrolü bu listeye dayanır. Toplu incelemeye yüklenen KKBS grubundaki il, doğruluk kaynağı yerine geçmez: PDF ve KKBS aynı yanlış ili içeriyorsa da listeye aykırılık tespit edilir. PDF ile KKBS alanları ayrıca esas numarası üzerinden karşılaştırılmaya devam eder.

İkinci okuyucuda KKBS adı ve raporda bulunan seçim çevresi aynı listeyle denetlenir. Seçim çevresi ayrı sütundan veya milletvekili bilgisinin başındaki açık il ifadesinden alınır; özetin konusu içindeki yer adları kullanılmaz. Tekil bir adda il bulunmaması diğer alanları karşılaştırmayı engellemez; aynı adlı kişilerde iki taraftaki il olmadan kimlik eşitliği onaylanmaz. EBYS'deki küçük yazım farklarına tolerans korunur. Kaynak dosyanın adı ve SHA-256 değeri raporda yer alır; listede değişiklik olduğunda eski sonuçlar geçersizleşir. Ham liste, parti, cinsiyet ve görev tarihleri depoya alınmaz.

Listeyi yeniden üretmek için `python scripts/import_member_directory.py DOSYA.xlsx` kullanılır. Bu işlem bakan listesini ve özet üslup kaynağını değiştirmez.

Benzer tam adlar farklı kişileri gösteriyorsa kırmızı uyuşmazlıktır: Hasan ÖZTÜRK / Hasan ÖZTÜRKMEN ve Cengiz ÇİÇEK / Çiçek OTLU gibi seçim hataları küçük yazım farkı kabul edilmez. `Hasan Öztür` gibi birden fazla isme tamamlanabilen eksik girişler de yakın yazım yoluyla onaylanmaz; kontrol gerekli olur. Aynı yanlış kişi iki kayıt için de seçilmişse yalnız kayıt karşılaştırması bu hatayı ortaya çıkaramaz; fiziksel önergeyle karşılaştırma gerekir.

### KKBS özetlerinde ilçe denetimi (26.11.2026)

Kullanıcının yüklediği **İl ve İlçe Kuruluş Tarihleri 2018.pdf**, ilçe denetiminin kaynağıdır. 86 sayfalık belgeden **81 il altında 922 numaralı ilçe kaydı** çıkarıldı; metin satırları ile sayfadaki hücre konumları bağımsız okunup eşleştirildi. İlçe sıra numaralarının il bazında kesintisiz ve tekil olduğu doğrulandı. Ankara, İstanbul, İzmir ve Konya’nın devam sayfaları birleştirildi. İl başlıkları ayrıca ilçe sayılmadı; listede numarasız merkez ilçeler için yeni kayıt üretilmedi. Genel “merkez ilçesi” ifadesi listede yok diye hata sayılmaz.

`district_reference.json`, kaynak dosyanın adı, resmî URL’si, SHA-256 değeri, 2018 liste yılı ve PDF sayfa bilgileriyle birlikte il–ilçe eşleşmelerini tutar. Ham PDF depoya eklenmez. `python scripts/import_district_reference.py DOSYA.pdf` aynı kaynağı yeniden üretir; eksik başlık, sıra veya iki okuma arasında fark varsa durur. Yazım kontrolünün sürümü hem kodu hem kaynağı içerir; güncellemeden önceki sonuçlar yeniden kullanılmaz. Bu değişiklik ücretli PDF okumalarının sürümünü değiştirmez.

Denetim **yalnız asıl özette açıkça ilçe olarak belirtilen adlara** uygulanır. `Esenyurtt → Esenyurt` gibi yakın yazımlar, `Marmara Ereğlisi → Marmaraereğlisi` gibi bölünmüş yazımlar ve doğrudan belirtilmiş yanlış il–ilçe bağları bulunur. Sayıyla yazılan adlar da kaynakta karşılığı varsa bütün olarak değerlendirilir (`19 Mayıs → Ondokuzmayıs`). Bunlar kaynak yazımına göre öneridir; otomatik metin değişikliği yapılmaz. Aynı adlı ilçeler bağlı oldukları illerle birlikte korunur; birden fazla yakın aday varsa tek aday seçilmez. Özet içindeki ilgisiz bir il adı ilçeye bağlanmaz; kişi, köy ve belde adları ilçe gibi denetlenmez.

Liste 2018 tarihlidir. Listede bulunmayan bir yer için “kesinlikle ilçe değildir” veya “belde/köydür” kararı verilmez; kaynakta bulunamadığı açıklanır ve yerleşim türünün/güncel statünün kontrolü istenir. Öneriler mevcut **Evrak No / Olan / Olması gereken** tablosunda, yazım önerisi sayacında ve CSV/JSON indirmelerinde yer alır. Kaynak bilgisi ekranda görünür. Kontrol yerelde çalışır, API kredisi tüketmez.

Seçim çevresi kontrolü, imza alanından birebir okunan isim ve ili karşılaştırır. İstanbul yerine Diyarbakır yazılması gereken bir üyede yanlış il kırmızı uyarıdır. Kullanıcının açık talimatı gereği Dersim, Tunceli'nin eş anlamlısı kabul edilmez. Belgede geçen konu/olay yerleri seçim çevresi olarak kullanılmaz. Çok imzalı belgelerde her imza kontrol edilir; tek seçim çevresi kartında bütün sonuçlar açıklanır; bütün kesin hatalar kendi sayfalarında ve imza bloklarında işaretlenir.

Özet üslubu için önceki `KKBS_YazılıOnerge_Rapor_19-10-2026 09_27.xlsx` dosyasındaki 50.416 önerge kullanılmaya devam edilir. Excel'in tarihsel bakan isimleri muhatap listesine alınmamıştır; bakan kontrolü yalnızca `rules.json` içindeki kullanıcı listesiyle yapılır. Ham Excel ve tüm önerge dökümü depoya eklenmez. Gerekli ad–il eşleşmeleri, kaynak dosyanın SHA-256 değeri, üslup istatistikleri ve 22 temsili özet örneği tutulur. Eski `scripts/import_reference_workbook.py` betiği tarihsel önerge dökümünü yeniden üretir ve milletvekili dosyasını da yazar; kullanılırsa ardından güncel milletvekili listesi yukarıdaki betikle yeniden içeri alınmalıdır. Farklı dönemler otomatik olarak güncel kabul edilmez.

Özet analizinde medyan 10, yüzde 90 eşiği 14, maksimum 31 kelime bulundu; 19.766 özet 10 kelimeden uzundu. Örnekler sadece üslup içindir, belgeye dış bilgi eklemek için kullanılmaz. Yeni kaynaklarla güncelleme yapıldığında belgeyi yeniden analiz edin; eski raporlar kendiliğinden yeniden değerlendirilmez.

Bakan adlarını okuma aşaması, doğrulama listesinden ayrıdır: model beklenen bakan isimlerini görmez; görüntüden birebir okuma yapar, sonuç kodda kullanıcı listesiyle karşılaştırılır. PDF/OCR'den ayrıca çıkarılan açık muhatap farklıysa uygun onayı engellenir. Kullanılan listenin kopyası ve iki okuma raporun `recipient_audit` alanında ve arayüzdeki “Bakan kontrolünde kullanılan liste ve okumalar” bölümünde bulunur. Bakan kontrolünün sürümü değiştiğinde ekranda kalmış eski rapor kaldırılır; yeniden analiz gerekir. Kullanıcının yeniden teyit ettiği eşleşmeler İçişleri Mustafa ÇİFTÇİ ve Adalet Akın GÜRLEK'tir.


## Toplu son inceleme

**Yazılı Soru Önergesi İncelemesi → Toplu inceleme** altında, bakanlıklara gönderilecek önerge grubunun PDF taraması ve KKBS Excel’i birlikte yüklenir. En fazla **200 önerge, 100 MB PDF / 1.000 fiziksel sayfa** desteklenir; bir önerge en fazla 10 sayfa olarak incelenir. Tekli incelemenin 12 MB / 10 sayfa sınırı ve işaretleme davranışı korunur.

- Standart Excel’de `Esas No`, `Soru Sahibi`, `Soru Sahibi İli`, `Muhatap Unvanı` ve `Soru Muhatabı` başlıkları okunur. Kullanıcının **makrosuz paket şablonu** da desteklenir: `Veri` sayfasındaki `Paket Adı / [başlıksız esas numarası] / Genel Evrak No / Önerge Sahibi Özeti` düzeni tanınır; milletvekili ve il metnin başından, muhatap makamı ve varsa kişi adı sonundaki açık metadata ifadelerinden ayrılır. Yardımcı/çıktı sayfaları yerine tanınan veri sayfası otomatik seçilir. `Kullanici`, yardımcı formül sütunları ve genel evrak numarası eşleştirme kaynağı değildir. Başlıksız numara sütununda açık `7/numara` aranır; sıra bilgisinden esas numarası üretilmez.
- Yalnızca milletvekili adı, seçim çevresi, muhatap bakanlık ve varsa kayıtlı bakan adı karşılaştırılır. Paket metninde sadece makam yazılmışsa bakan kişi adının KKBS’de bulunmadığı arayüzde ve JSON raporunda açıklanır; her kayıt için sahte eksiklik bulgusu üretilmez. **Belgedeki bakan adı her durumda kullanıcı listesiyle şekil kontrolünden geçer.** Ayrı `Soru Muhatabı` sütunundaki beklenmedik boş hücreler hâlâ şüpheli bulgu oluşturur. **Tarih ve özet karşılaştırılmaz.** `Genel Evrak Tarihi` önerge tarihi yerine kullanılmaz.
- **Bakanlıklara göre bölümlenmiş liste** de yüklenebilir: bakanlık başlığı altında tekrarlanan `SIRA NO / ESAS NO / SAHİBİ VE ÖZETİ` tabloları okunur. `Evrak Kayıt No` gerekmez; varsa karşılaştırmada kullanılmaz. Muhatap bölüm başlığından, milletvekili ve seçim çevresi açık sahip ifadesinden alınır. Sıra numarası sıfırlansa da eşleştirme yalnız esas numarasıyla yapılır. Tekrarlanan tablo başlıkları önerge sayılmaz. Bakanlık başlığı eksik veya tanınmıyorsa önceki bölümün bakanlığı taşınmaz; dosyanın düzeltilmesi istenir. Kişi adı başlıkta açıkça varsa ayrıca karşılaştırılır; yoksa kullanıcı bakan listesiyle şekil kontrolü korunur. Dosyada hem `Veri` hem `İlk Çıkış` varsa satır bazında bilgi içeren `Veri` tercih edilir.
- Tam KKBS raporu yüklenebilir; başlangıç–bitiş esas numarasıyla en fazla 200 önergelik grup seçilir. Excel yalnız grubu içeriyorsa aralık boş bırakılabilir. Farklı dönemler karıştırılmaz; aynı esas numarasındaki çelişkili satırlar şüpheli kabul edilir. Geçersiz esas numaralı kaynak satırları düzeltilmeden işlem başlamaz.
- Sayfa sınırları görüntüdeki yeni **hitap–cevap talebi–vekil/imza bloğuna** göre belirlenir; önerge uzunluğu sabit değildir (örneğin 1, 3 veya 6 sayfa). Dört sayfalık okuma grubu belge sınırı sayılmaz. Her yeni grupta önceki sayfa ve son önergenin başlangıcı en fazla iki ek bağlam görüntüsü olarak verilir; bunlar yeniden sınıflandırılmaz. Soruların 1’den başlaması, tekrarlanan vekil üstbilgisi veya aynı esas numarasının devam sayfasında el yazısıyla bulunması tek başına yeni önerge sayılmaz. Ardından önerge görüntüleri KKBS alanları modele gösterilmeden okunur. Esas numarası, alan alıntıları ve mevcut PDF/OCR metni arasında anlamlı uyuşmazlık varsa sonuç onaylanmaz. Sıralama yalnızca okunamayan kaşeye **aday numara** önermek için kullanılır; bu aday KKBS ile doğrulanmış eşleşme sayılmaz.
- Metin katmanında çok sayıda sözcük içi rakam/bozuk karakter varsa bağımsız Türkçe/İngilizce Tesseract okuması denenir. Yalnızca yeterli uzunlukta ve belirgin biçimde daha az bozuk sonuç kullanılır; başarısızlıkta eski metin korunur. Seçim modelin okumasına veya referans isimlere göre yapılmaz, anlamlı alan uyuşmazlıkları onaylanmaz. Değiştirilen metin tekli incelemenin JSON raporunda `ocr_original` olarak saklanır; bu yöntem tamamen temiz metin garantisi değildir.
- Toplu işlemde **kaşe numarası gövde OCR’sinden ayrı doğrulanır**: numaralı paket şablonunun sağ üst bölgesindeki özgün, konumlu PDF sayı okuması korunur. Görsel okuma bu tekil kaşeyle aynıysa gövde OCR’sinin değiştirdiği rakam eşleştirmeyi bozmaz. Kaynak, modelin veya KKBS’nin beklediği sayıya göre seçilmez; özgün kaşeyle çelişen, birden fazla sayı içeren ya da görselde belirsiz olan okuma onaylanmaz. Bu bölgede geçerli özgün sayı yoksa mevcut OCR uyuşmazlığı kontrolü korunur. Modele kaşe bölgesinin yakın plan görüntüsü de verilir; OCR metni ve KKBS verileri verilmez. `7/` öneki ve kaşede rakamlar arasındaki boşluklar biçim farkı olarak ele alınır; farklı veya şüpheli rakamlar düzeltilmez.
- **İlk sayfanın sağ üstündeki numaratör baskısı ana numaradır.** OCR’nin aynı satırda, birbirine yakın ve ayrı sözcüklere böldüğü `52 3 42` gibi rakamlar konumları korunarak `52342` ile karşılaştırılır; farklı satırlar, uzak sütunlar, belirsiz harfler veya iki ayrı tam sayı birleştirilmez. Devam sayfalarının sağ üstündeki el yazıları ayrı ayrı görüntüden okunur (`continuation_numbers`); ana numara bu sayfalara kopyalanmaz ve okunamayan ilk baskının yerine el yazısı konmaz. Açıkça aynı numara ek bulgu oluşturmaz. Farklı, okunamayan veya dayanağı olmayan devam numarası yalnız ilgili fiziksel sayfada şüpheli eşleştirme olarak gösterilir; ilk sayfanın KKBS kaydı değiştirilmez. OCR’nin el yazısı yerine `w` gibi sayısal olmayan çıktı üretmesi farklı numara sayılmaz; konumlu sayısal OCR ile görsel okuma arasındaki gerçek rakam uyuşmazlığı kontrol gerektirir. Devam numarası hiç yoksa tek başına hata sayılmaz; ancak modelin devam sayfası kontrolünü tamamen atlaması eksik rapor olarak bildirilir.
- Mevcut altı şekil kontrolü uygulanır. Bakan adı için kullanıcının `rules.json` listesi korunur; toplu işlemde milletvekili–il kaynağı yüklenen KKBS grubudur. Kendi bilgisinden görevli veya seçim çevresi üretilmez. Şekil kontrolü hukuki iade kararı değildir.
- Milletvekili adı yanlış kayda girilmiş olsa bile, belgedeki kişinin il bilgisi yüklenen grubun başka satırlarında çelişkisiz olarak varsa şekil kontrolünde bu bilgi kullanılır. Böylece açık isim uyuşmazlığına gereksiz “il kaynağı yok” bulgusu eklenmez. KKBS satırıyla alan karşılaştırması her zaman aynı esas numarasındaki kayıt üzerinden yapılır; çelişkili milletvekili–il eşleşmeleri tahminle çözülmez.
- Ana sonuç tablosunda **hatalı bulgular** esas numarası, PDF’nin başından 1 ile sayılan fiziksel sayfa numarası, açıklama ve karşılaştırılan alanlarla gösterilir. **Şüpheli bulguları incele** bölümü başlangıçta kapalıdır; şüpheler ve tam açıklamaları buradan açılır. Hata bulunmaması, şüphelerin veya eksik eşleşmelerin uygun kabul edilmesi anlamına gelmez; tamamlanmamış KKBS karşılaştırması ana ekranda belirtilir. PDF işaretlenmez; uygun önergelerin kontrol listeleri gösterilmez. Yinelenen/geriye giden esas numaraları, belirsiz sayfa sınırları ve KKBS grubunda olup PDF’de doğrulanamayan kayıtlar da bildirilir. İndirilen CSV ve JSON raporları hata ve şüphelerin tamamını korur.
- **İşlenen belge sayısı ile KKBS eşleşmesi ayrıdır.** Arayüz eşleşen/beklenen kayıt sayısını gösterir; önerge başlangıcı sayısı Excel’den farklıysa uyarır. Bütün API çağrıları bitmiş olsa bile eksik, yinelenen veya sınırı belirsiz eşleşmelerde `complete=false` kalır ve rapor `eksik-karsilastirma` adıyla indirilir. `processing_complete` yalnız işlem döngüsünün bittiğini, `matching_complete` bütün kayıtların birebir eşleşmesini belirtir. Esas numarası reddedildiyse ham değer, alıntı ve ret nedeni JSON’daki `reading_evidence` alanında saklanır; ilgili kaydın milletvekili/bakanlık karşılaştırmasının yapılmadığı açıkça yazılır. Bu bilgiler okunamayan bir numarayı tahminle onaylamak için kullanılmaz.
- İşlem arka planda ilerler. Sayfayı açık tutarak **duraklat / kaldığı yerden devam et** kullanılabilir; tamamlanan kayıtlar tekrar API’ye gönderilmez. Kota veya bağlantı hatasında işlem durur; eksik sonuçlar uygun sayılmaz. Tamamlanamayan önerge analizleri ayrıca yeniden denenebilir. Sayfadan ayrılma/çıkışta duraklatma istenir; açık sayfanın takibi 90 saniye kesilirse yeni istek başlatılmaz. Başlamış API isteği tamamlanabilir.
- Belgeler ve ilerleme yalnız oturum belleğindedir. Sayfa yenilenmesi veya sunucu yeniden başlaması için kalıcı devam garantisi yoktur; ara rapor indirilebilir. Kullanıcılar arasında ortak belge önbelleği yoktur. Bellek ve API yükünü sınırlamak için aynı sunucuda bir toplu iş yürütülür; PDF’nin yalnız o an incelenen sayfaları görüntüye çevrilir.

### Kredi harcamadan ve küçük örnekle test

Toplu inceleme varsayılan olarak **Küçük örnekle dene** ile açılır. PDF’den en fazla 10 fiziksel sayfa seçilir; aralığın dışındaki görüntüler API’ye gönderilmez. **Seçilen sayfalar tek önergeye ait** seçeneğinde, önergenin başlangıcı ve tüm devam sayfaları kullanıcı tarafından seçilir; otomatik sayfa ayırma atlanır ve tek analiz isteği yapılır. **Sayfa ayırmayı da dene** seçeneği yalnız seçilen aralıkta ayırma ve inceleme yapar. Ekrandaki istek sayısı ücret tahmini değildir; tutar model, görsel ve çıktı uzunluğuna bağlıdır. Deneme raporları fiziksel PDF numaralarını korur, diğer KKBS kayıtlarını eksik tarama saymaz ve bütün grubun son kontrolü olarak gösterilmez.

Başarılı model okumasından sonra **Okumayı kaydet (ücretsiz tekrar test için)** ile JSON indirilir. Ücretli okuma, sonraki kod doğrulaması hata verse bile saklanır. Kayıt görüntü veya API anahtarı içermez; belge metni, OCR, kaşe dayanakları ve modelin ham alanlarını içerdiğinden kullanıcı tarafından korunmalıdır. Kayıt yalnız ilgili oturum belleğinde tutulur; ortak sunucu önbelleği değildir. Dosya/ayar değiştirmeden, sayfayı yenilemeden veya sunucu güncellemesinden önce indirilmelidir.

**Kayıtlı okumayı yeniden kontrol et (ücretsiz)** seçeneğinde aynı PDF, güncel KKBS Excel’i ve okuma kaydı yüklenir. PDF içerik özeti ve sayfa kapsamı doğrulanır; model veya görüntü işleme çağrısı yapılmadan güncel kurallar ve KKBS değerleri eski okumayla karşılaştırılır. API anahtarı gerekmez. Bu işlem yeni bir görsel okuma veya tüm paketin yeniden incelendiği anlamına gelmez; kayıtlı bir okuma hatasını düzeltemez. Eski yalnız-bulgu JSON raporları ham okumayı içermediği için bu amaçla kullanılamaz. Geçersiz/eski biçimde kayıt yüklemek otomatik ücretli yeniden okumaya yol açmaz.

**Tüm grubu incele** seçeneği ayrıca seçilmelidir. Esas numarası aralığı Excel kapsamını daraltır; PDF sayfa okuma maliyetini azaltmaz. Geliştirme testleri sahte API yanıtlarıyla ücretsiz çalışır; gerçek model doğruluğu için önce küçük ve bilinen bir örnek kullanılmalıdır.

## Gelen Kağıt İşlemleri

Girişten sonra **Gelen Kağıt İşlemleri** seçilir. Önce başlangıç ve bitiş esas numaraları elle girilir, ardından işlem aşaması seçilir. Excel (`.xlsx`) yüklenir veya başlıklarıyla birlikte tablo yapıştırılır ve **Listeyi oluştur** çalıştırılır. Yapıştırmada **Yapıştırılan tabloyu oku** düğmesi de kullanılabilir. İki uç numara dahildir; dosya değiştiğinde girilen aralık korunur. **Paketin süresini kullanıcı takip eder; uygulama tarih veya 15 günlük süre hesabı yapmaz.**

| İşlem aşaması | Esas numarası ve bakanlık listesine alınan durum |
| --- | --- |
| **Memur işlemi · İlan edilecekler** | Yalnızca `15 Günlük Cevaplanma Süresi Devam Ediyor`; kullanıcı, süresini takip ettiği paketin aralığını girer. Önceden ilan edilenler tekrar eklenmez. |
| **Uzman kontrolü · İlan edilenler** | Yalnızca `Cevaplanmadığı Gelen Kağıtlarda İlan Edildi`; hâlâ süresi devam ediyor görünen kayıtlar ayrıca uyarılır. |

Başlıklı KKBS tablolarında `Esas No`, `Son Durum`, `Muhatap Unvanı` ve varsa `Donem Adı` okunur. Yasama dönemi seçimi istenmez: varsa kaynak bilgisi otomatik okunur; aynı aralıkta birden fazla dönem varsa ayrı tablo istenir. Başlıksız yapıştırmada ilk üç sütun esas numarası, durum ve muhatap olmalıdır. Tam KKBS dökümü başlıklar olmadan yapıştırılırsa sütunlar tahmin edilmez. En fazla 12 MB ve 100.000 veri satırı desteklenir. Kaynak numara aralığı ve ilk beş kayıt arayüzden kontrol edilebilir.

- `Cevaplandı`, `Süresi İçinde Cevaplandı` ve `Süresi Geçtikten Sonra Cevaplandı` cevaplanan gruptadır. Geri alınanlar ayrıca sayılır; bu kayıtlar iki aşamanın da esas numarası listesine alınmaz.
- Aynı esas numarasının eşdeğer satırları tek sayılır. Çelişen kayıtlar ve tanınmayan durumlar ayrı gösterilir; sessizce cevaplanmamış kabul edilmez. Dönemler birbirine karıştırılmaz.
- Dosyada bulunmayan esas numaraları açıkça listelenir; eksik satırdan önerge üretilmez. Geçersiz numaralı satırlar kaynak satır numaralarıyla bildirilir. Kayıt bulunmayan aralık, tamamı cevaplanmış aralık ve tanınmayan durumlar farklı açıklamalarla gösterilir. Hiç kayıt değerlendirilemediyse 18 muhatap yokmuş gibi listelenmez. Eksik veri ve işlem aşaması uyarıları TXT/JSON raporunda da korunur.
- Bulunan bakanlıklar ve muhataplar, toplam sayılarıyla geniş ana kutuda; bulunmayanlar sağdaki daha küçük gri kutuda gösterilir. Milletvekilleri tek tek listelenmez. Hesaplama yalnızca **seçilen aşamaya alınan kayıtlar** üzerinden, kullanıcıya ait 18 muhataplık listeye (Cumhurbaşkanı Yardımcısı dahil) göre yapılır. Bu modül kişi adını doğrulamaz; `Adalet Bakanı`, `Adalet Bakanlığı`, `Adalet Bakanlığına` gibi aynı kurumu belirten yazımlar birleştirilir. Tanınmayan adlar başka bakanlığa tahminle atanmaz.
- Aralıklar KKBS giriş biçiminde, düz ASCII tire (`-`) ve boşluksuz noktalı virgülle yazılır; tek numaraların iki ucu da tekrarlanır: `45424-45493;45495-45512;45514-45523;45525-45525;45527-45530`. Alt alta liste de hemen altında, ek bir tıklama gerektirmeden görünür. TXT ve JSON aynı tek satırlık metni içerir; CSV'de formül olarak yorumlanabilecek metinler etkisizleştirilir.
- **Birleşik listeye ekle** ile arka arkaya sorgulanan gruplar oturum içinde biriktirilir. Birleşik metin ve alt alta liste birlikte görünür; yalnız giriş metnini içeren TXT indirilebilir. Her sorgunun eklenme anındaki aralıkları aynen saklanır ve ekleme sırasıyla `;` kullanılarak yan yana yazılır; sorgular arasında sıralama, tekilleştirme veya ardışık aralıkları birleştirme yapılmaz. Örneğin `50060-50100` ile sonraki sorgudaki `50101-50200`, birleşik listede `50060-50100;50101-50200` olarak kalır. Aynı başlangıç–bitiş aralığı yeniden eklenirse listedeki mevcut konumunda güncellenir. Farklı sonuç veren örtüşen sorgularda eski sorgunun çıkarılması istenir. Memur ve uzman listeleri ayrı tutulur; dönem bilgileri farklı gruplar birleştirilmez. Eklenen gruplar tek tek çıkarılabilir veya liste temizlenebilir. Dosya/aralık değiştirmek ve modüller arasında gezinmek birikimi silmez; sayfayı yenilemek veya çıkış yapmak oturumu sona erdirebildiğinden liste önceden indirilmelidir. Kaynak uyarıları birleşik listede de belirtilir.
- İndirme dosya adında **memur/uzman** aşaması bulunur. CSV bütün kayıtları içerir ve hangi kayıtların seçilen aşama listesine dahil olduğunu belirtir. Ekrandaki ayrıntı tablosu ilk 500 kayıtla sınırlıdır; indirilen CSV/JSON eksiksizdir. İndirme işlemi sayfayı yeniden çalıştırmaz.
- Bu bölüm OpenAI kullanmaz, API anahtarı gerektirmez ve API ücreti oluşturmaz. Dosyalar ortak önbelleğe veya diske yazılmaz; kaynak, aralık veya işlem aşaması değiştiğinde eski sonuç kaldırılır, çıkışta oturum temizlenir. Aynı adlı dosyada hücreler değişirse içerik özeti değişir ve dosya yeniden okunur.
- Excel veya yapıştırılan tablo okunurken sayfa yeniden çalıştırılırsa yarım kalan okuma tekrar denenir. Dosya ancak okuma tamamlanınca yüklenmiş sayılır; eski sürümden eksik kalmış oturum verileri de yeniden okunur.

Excel sayfa adları, büyük dosyanın ortak metin tablosu yüklenmeden okunur; veri tek kez yüklenir. Yanlış `1×1` çalışma sayfası boyutu bildiren dışa aktarımlarda gerçek satırlar okunur. Eksik/tanınmayan başlıklarda yanlış sütunlara geçmek yerine açıklayıcı hata verilir.

Referans konuşmadaki **49220–49329** aralığı, kullanıcının 50.416 satırlık gerçek Excel dosyasında **memur aşaması** ile doğrulandı: 110 kayıt, 97 cevap süresi devam eden, 13 cevaplanan; 16 muhatap ve eksik olarak Dışişleri ile Millî Savunma Bakanlıkları. Aynı dosyada bu aralık uzman aşamasına hazır değildir; ilan edilmiş kayıt yoktur ve 97 kayıt hâlâ süresi devam ediyor görünür.

## Analiz düzeltmeleri ve sürüm takibi

Kontroller daima hitap, milletvekili, seçim çevresi, muhatap, talep ve harf/yazım sırasındadır. Aynı model yanıtının tekrar doğrulanması özgün yanıtı değiştirmez. OCR karşılaştırması sayfa başına bir kez hesaplanır; alıntının başka yerde tekrar etmesi ilgili konumdaki farkı gizlemez. İlgili alan içindeki anlamlı ekleme ve çıkarmalar da kontrol edilir; farklı bir paragraftaki değişiklik bütün kontrolleri sarıya çevirmez.

**TÜRKİYE BÜYÜK MİLLET MECLİSİ BAŞKANLIĞINA**, **BAŞKANLIĞI’NA** ve **BAŞKANLIĞI'NA** biçimleri geçerli hitaptır. Kesme işareti farkı hitap/harf hatası veya OCR uyuşmazlığı sayılmaz; özgün alıntı korunur. Başka bir makam, farklı sözcük/ek, okunamayan alan veya dayanağı bulunmayan alıntı bu istisnayla onaylanmaz.

Tekrarlanan muhataplar tek kimlik olarak değerlendirilir; açık cevaplandırma talebi varsa anlatı içinde anılan diğer bakanlar muhatap sayılmaz. Sayın, Prof./Doç./Dr. ve yaygın kesme işareti ekleri desteklenir. Kullanıcı listesi dışında bakan bilgisi alınmaz.

PDF üzerindeki işaretler tamamlanmış analizden ayrı üretilir. PDF/OCR işaretleme hatası, metindeki bulguları ve indirilebilir JSON raporunu kaybettirmez. **PDF işaretlerini yeniden oluştur** yalnızca işaretlemeyi yeniden dener, ücretli API analizi başlatmaz. İşaretler eklenmeden önce tüm konumlar özgün sayfada aranır; OCR işlemi de 2200 piksel uzun kenar sınırına göre ölçeklenir.

Analiz sürümü, doğrulama kodu ve kullanıcı kaynaklarının içerik özetiyle belirlenir. Kaynaklar veya kurallar değiştiğinde eski oturum raporu kaldırılır. Gelen Kağıt raporlarında da işlem sürümü ve kaynak dosyanın özeti bulunur. Otomatik testler, canlı API ile hassas olmayan örnek PDF'ler ve gerçek Excel aralığı kontrolü farklı doğrulama katmanlarıdır; modelin her belgeyi hatasız okuyacağı garantisi değildir.
