# Perfboard Studio — Proje Planı

> Delikli plaket (perfboard) üzerine PCB gibi tasarım yapmayı, optimize bağlantılar
> çizmeyi ve bundan **çok detaylı bir lehim rehberi** üretmeyi sağlayan açık kaynak
> masaüstü uygulaması.
>
> **Durum:** uçtan uca çalışıyor ve yayında — **v0.12.0-dev**, PyPI'da ve üç masaüstü
> platformu için kurulum paketi olarak. Açık kalan iki şey var ve ikisi de kod değil:
> dogfood testi (§11) ve kod imzalama (§12).
> **Sahip:** medinstech · **Lisans:** Apache-2.0 · **İsim:** Perfboard Studio
>
> **Bu belge yaşayan bir plandır, dondurulmuş bir kehanet değil.** Bir süre öyleydi:
> "yazıldığı hâlde duruyor" diye bir notu vardı, ve bunun bedeli ödendi — burada duran
> eskimiş bir satır, sonradan yapılmayacak şeylerin gerekçesi olarak anıldı. Plan
> değişebilir; değişince burası da değişir. Bir öngörü tutmadıysa ne olduğu bir cümleyle
> yazılır ve devam edilir, çünkü tutmayan öngörü tutan öngörü kadar bilgi taşır.
>
> Ne nerede: **burası** ne yapılacağı ve neyin bilerek yapılmadığı. **`CLAUDE.md`** nasıl
> inşa edildiği ve neden öyle. **`CHANGELOG.md`** ne zaman ne değişti. Aynı şeyi üç yerde
> anlatmamak için buradaki bölümler kısa tutulur ve ayrıntı için oraya işaret edilir.

---

## 1. Tek Cümle

Bir şema netlist'ini al, delikli plakete yerleştir, bağlantıları optimize et,
doğruluğunu makine ile kanıtla, ve kullanıcının eline **adım adım lehimlenebilir,
ölçümle doğrulanabilir bir montaj rehberi** ver.

---

## 2. Kilitlenen Kararlar

| # | Karar | Seçim | Gerekçe |
|---|---|---|---|
| D1 | v1 kart tipi | **Ada bakırlı delikli plaket** (pad-per-hole) | TR'de en yaygın, en az desteklenen. Veri modeli üçünü de destekler, cila burada |
| D2 | Lisans | **Apache-2.0** | Şirket dostu, patent koruması. GPL'li DIYLC/VeroRoute kodundan tamamen bağımsız kalınacak |
| D4 | Rehber çıktısı | **4'ü birden**: interaktif offline HTML · 1:1 PDF · doğrulama kontrol listesi · CSV kesim listesi + BOM | Rehber projenin farklılaştırıcısı; yarım bırakılmaz |
| D5 | Masaüstü çatısı | ~~Tauri v2~~ → **PySide6 + VTK** | Aşağıya bak — karar tamamen değişti |
| D6 | 3D modeller | **Parametrik üretim + KiCad'den ödünç THT paketleri** | Aşağıya bak — karar kısmen değişti |
| D7 | 3D kapsamı | **Tam** — montaj animasyonu + patlatılmış görünüm dahil | 3D'yi dekorasyondan öğretim aracına çeviren şey bu |
| D8 | Lehim yolu | **Birinci sınıf yol çekme primitifi** (cezalı özel durum değil) | TR delikli plaket pratiğinde asıl yöntem; güç/toprak rayları böyle çekiliyor |

**D3 yoktu, kaldırıldı.** "Devre girişi: netlist import, şema editörü yazma yükü yok"
diye bir satırdı. Kimin koyduğu kayıtlı değil — bu dosya ilk commit'te, projenin
`Co-Authored-By` geleneğinden önce geldi — ve proje sahibi böyle bir karar vermediğini
söylüyor. Gerekçesi de tutmadı: bakınız aşağıdaki "Devre girişi". Kalan numaralar olduğu
gibi bırakıldı; D4'ü D3 yapmak CHANGELOG'daki ve kaynaktaki her D4..D8 atfını sessizce
yanlışlardı.

**D5 nerede durdu.** Tauri v2 + React + three.js seçilmişti; uygulama **PySide6 + VTK**
oldu ve çatı kadar dil de değişti — çekirdek TypeScript'ten Python'a taşındı. Sebep
gerekçenin kendisiydi: D5'in üç dayanağından biri "Linux WebKitGTK'da WebGL yeter mi"
sorusuydu ve §13'te risk olarak duruyordu. `tools/bench-3d` tam olarak bunu ölçmek için
yazıldı, ölçtü, ve cevabı "bu riski taşımaya değmez" çıktı. Qt'nin kendi OpenGL'i ve
VTK'nın bilimsel görselleştirme yığını aynı işi platform sorusu olmadan yapıyor.

TypeScript motoru silinmedi: `packages/` altında duruyor ve **diferansiyel kanıt** olarak
kullanılıyor — Python portunun çıktısı onun altın dosyalarına bayt bayt uyuyor. "Bütün
testler geçiyor" yerine "değiştirdiğimiz şeyle aynı sonucu üretiyor" diyebilmenin bedeli
bu. Ayrıntı `CLAUDE.md`'de.

**D6 nerede durdu.** Karar üç gerekçeye dayanıyordu: sıfır asset, footprint ile garantili
tutarlılık, temiz lisans. **İkisi aynen duruyor, üçüncüsü kısmen bırakıldı.**

Bırakılma sebebi tartışma değil, sonuca bakmaktı: bir çaptan ve bir yükseklikten üretilen
potansiyometre, üstünde çubuk olan bir disktir; röle bir kutudur; vidalı klemens vidasız
bir bloktur. Hiçbir gölgelendirme bunları o parça yapmıyor. KiCad'in `packages3D`
kütüphanesinde gerçeği var, ve lisansı yeniden dağıtıma açık.

Ödünç alınan şeyin sınırları, D6'nın koruduğu şeyleri koruyacak biçimde çizildi:

- **Üretilmiş gövde hâlâ her şeyin cevabı ve hâlâ yedek.** Eşlenmemiş bir footprint,
  gramerle istenmiş bir id (`box-4x2-p1-r3-15x10x8`), mesh'siz bir build — hepsi eskisi
  gibi çiziliyor. Hiçbir şey bir modelin varlığına bağlı değil.
- **Yalnızca kartın ÜSTÜNDEKİ şekil alınıyor.** Bacaklar bizim: deliklerden geçen ve lehim
  tarafında kesilmiş duran kısım, kartın kendi kalınlığından çiziliyor.
- **Gövdenin rengi bizim tablomuzdan.** `bodies.BODY_STYLES` 2D görünüm, 3D görünüm ve
  rehberin adım görselleri için tek tablo; ödünç bir mesh uğruna bundan vazgeçilmedi.
- **Malzemeler bizim.** Ödünç mesh, üretilmiş gövdeyle aynı kurallarla ışığa cevap veriyor.

**Lisans açıkça yazıldı, çünkü değişen şey bu.** Mesh'ler CC-BY-SA 4.0 — bu dağıtımın
Apache-2.0 olmayan tek parçası — ve kendi `LICENSE`/`NOTICE.md` dosyalarıyla birlikte
`src/perfboard_studio/ui/models/` içinde duruyorlar. KiCad'in istisnası tasarımları muaf
tutuyor: **bu araçla çizilen kart, şematik ve rehber etkilenmiyor.** Yeniden dağıtan o
dizini olduğu gibi taşır. §13'ün "lisans bulaşması" riski böyle sınırlandı: kod değil veri,
tek dizin, kendi lisansıyla.

**Devre girişi: iki yol, ve ikisi de birinci sınıf.** Ya bir netlist içe aktarılır, ya
devre burada çizilir. Sıra her iki durumda da aynı: **devre önce, kart sonra** — diğer her
EDA aracının çalıştığı sıra. `doc.parts` karta konmamış parçaları tutar (`part.add` /
`part.update` / `part.delete` / `part.place`, `component.unplace`), `net.connect` bir
parçanın kart üzerinde olmasını hiç istemiyordu, ve şema paneli (`Ctrl+2`) bu ikisini bir
araya getiriyor.

**Çizmek neden gerekti.** Netlist bir bağlantı listesidir; geometrisi yoktur. Sayfayı bu
araç zaten kendisi üretmek zorundaydı — `schematic.py` bunun için var — yani ortada
"başka yerden gelen bir şema" hiç olmadı. Olan şey, bakılabilen ama çizilemeyen bir
şemaydı: sembol taşınamıyor, döndürülemiyor, tel elle çekilemiyordu.

**Alınan yük ne kadardı.** Bir yıl değil. Çizim geometrisi netlist'in DIŞINDA tutulduğu için
— çizilen telin net kimliği yok, iki ucunu tutan net neyse odur — LVS, router, placer,
rehber ve kart tarafında tek satır değişmedi. Sembol sürüklenir, çeyrek çeyrek döndürülür,
aynalanır; tel pinden pine elle çekilir; tel çekilmeyen pin **ada göre** bağlanır; ve çizimin
üzerine metin, kutu, çizgi, daire konabilir.

**İki tür sayfa var ve hangisi olduğuna belge karar veriyor.** `doc.sheet` boşsa çizimin
tamamı eskisi gibi türetilir — semboller hücrelerde, teller yalnızca aralarındaki
kanallarda, hiçbir tel bir sembolü kesemez — ve her netlist içe aktarımı, her yeni belge ve
her `Arrange` basışı bunu üretir. İçinde bir şey varsa sayfa artık **çizilmiş** bir sayfadır
ve hiçbir şey düzenlenmez.

**Netlist hâlâ "neyin bağlı olduğu"nun tek cevabı.** Çizilen telin net kimliği yoktur:
hangi nete ait olduğu, iki ucunu birden tutan nettir ve her seferinde bakılır. LVS, router,
placer, rehber ve kart `doc.nets` okur; hiçbiri geometri öğrenmek zorunda değil, ve
kullanıcının sonradan kopardığı bir bağlantının teli sessizce "hâlâ bağlı" demek yerine
çizilmez olur. `.perf` biçimi kımıldamadı: üç dizi de boşken dosyadan düşüyor, on beş altın
fikstür bayt bayt aynı, `DOCUMENT_FORMAT_VERSION` hâlâ 1.

**Ek kararlar (tartışmaya açık ama varsayılan):**
- Uygulama içi AI paneli **v1 kapsamında değil**. Çekirdek motor asla AI'a bağımlı olmayacak — API anahtarı olmadan araç tam işlevli kalır.
- MCP tool sayısı hedefi **~25**, kasıtlı olarak dar (context tüketimini kontrol altında tutmak için).

---

## 3. Neden Var Olmalı — Boşluk Analizi

| Araç | Netlist import | Autoroute | DRC | Lehim rehberi | 3D | Ajan API | Açık |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| DIYLC | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |
| VeroRoute | ✓ | ✓ | kısmi | ✗ | ✗ | ✗ | ✓ |
| striprouter | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ |
| PerfBoard.app | ✗ | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ |
| VeeCAD | ✓ | kısmi | kısmi | ✗ | ✗ | ✗ | ✗ |
| **Perfboard Studio** | ✓ | ✓ | ✓ | **✓✓** | ✓ | ✓ | ✓ |

**Üç farklılaştırıcı:**

1. **Doğrulama kontrol noktalı lehim rehberi.** Netlist'ten deterministik türetilen
   ölçüm adımları: *"Blok 2 bitti → U1 pin 4 ile C3(−) arası süreklilik olmalı"*,
   *"Güç vermeden önce: GND–V+ arası > 10 kΩ olmalı"*. Hiçbir rakipte yok.
2. **Perfboard LVS.** Şema netlist'i ile fiziksel kartın bağlantı grafiği izomorfizmi.
   "Acaba doğru mu?" sorusunun makine cevabı.
3. **Ajan-yerel mimari.** MCP sunucusu + headless CLI + git-diff'lenebilir proje dosyası.

**Sonradan bir dördüncüsü eklendi: devrenin kendisi burada çizilebiliyor.** Tabloda
"Netlist import" sütunu duruyor ve doğru, ama artık tek kapı o değil — şema sayfasında
sembol yerleştirilir, döndürülür, tel çekilir, pin adına göre nete bağlanır. Sebebi §11'de
yazılı: devreyi yakalayıp çizemeyen bir araç, insanı zaten başka bir araca gönderiyor.

---

## 4. Alan Modeli (Çekirdek)

### 4.1 Delik adresleme
Sütun harfi + satır numarası (**A1, B7, AC12**) — insanların delikli plaket hakkında
konuşma biçimi, ve rehberin dili — dolayısıyla bir biçimlendirme ayrıntısı değil,
birinci sınıf kavram. `geometry.py` çeviriyi sahipleniyor: `coord_to_hole_ref` katı ve
gidiş dönüş yapıyor, `format_hole` ise hiç hata fırlatmıyor — kart dışı koordinat
tanımı gereği negatiftir ve hata veren denetleyicinin basması gereken tam olarak odur.

### 4.2 Kart
`model.Board`. Kart tipi bir görüntü ayarı değil: stripboard'da satırlar zaten birleşik
gelir, dolayısıyla connectivity, DRC, router ve rehber farklı cevap verir.

```python
type BoardType = Literal["pad-per-hole", "stripboard", "plain"]
type BoardMaterial = Literal["FR4", "FR2", "FR1"]

@dataclass(frozen=True, slots=True)
class Board:
    type: BoardType
    cols: int
    rows: int
    pitch: Mm                       # 2.54
    thickness: Mm                   # 1.6
    material: BoardMaterial
    pad_diameter: Mm
    drill_diameter: Mm
    strip_axis: Literal["horizontal", "vertical"] | None = None
    ...                             # pad şekli, kenar payı, basılı legend
```

Planda olmayıp sonradan gelenler, hepsi gerçek karttan: **oblong pad** (kenar şeridinde,
iki farklı komşuluk boşluğu demek — R5'in konusu), **eksen başına kenar payı** (5 × 7 cm
kart kenarlarda ~2.1 mm, üstte/altta ~4.5 mm), **basılı legend**, **tek yüzlü kart**,
**montaj delikleri** ve **kenar konnektörü parmakları**. `geometry.STANDARD_PRESETS`
tedarikçilerin sattığı boyutları tutuyor; kenar payı boyuttan ve delik sayısından
*çözülüyor*, ezberden yazılmıyor.

### 4.3 Komponent
`model.ComponentInstance` + `model.Footprint`. Footprint'ler **üretiliyor**, paketlenmiyor
— 61 tanesi bir avuç sayısal parametreden `footprints.py` içinde hesaplanıyor, sıfır
asset. Kütüphanede olmayan bir parça, parametrelerini kendi adında taşıyan bir id ile
isteniyor (`box-4x2-p1-r3-15x10x8`), böylece `.perf` formatı kımıldamıyor ve kart bir
yabancıda da aynı parçayla açılıyor.

**Çapa pin 1'dir ve grid ofseti (0, 0)'dır** — iki bacaklıda da, TO-220'de de, DIP'te de.
Geometrik merkez değil, gerçek bir fiziksel pin. `body_outline` ise **courtyard**'dır,
gövde değil: yarım grid adımı paylı, çünkü çakışma DRC'sinin ihtiyacı bu.

### 4.4 İletken — mimarinin kalbi
Delikli plakette bağlantı tek tip değil. Her iletken bir **tür**, bir **katman** ve
bir **maliyet** taşır:

```python
type ConductorKind = Literal[
    "lead-bend",           # komponent bacağı uzatılmış  → maliyet ~0, max 3-4 delik
    "solder-trace",        # LEHİM YOLU, saf lehim       → çok düşük/adım, uzunluk sınırlı
    "solder-trace-wired",  # LEHİM YOLU, omurgalı        → düşük + sabit hazırlık, sınırsız
    "bare-wire",           # lehim yüzü çıplak tel       → uzunluk×k, KESİŞEMEZ
    "insulated-wire",      # lehim yüzü izoleli tel      → uzunluk×k + sabit ceza, kesişebilir
    "top-jumper",          # üst yüz jumper              → yüksek ceza, gövde alanı işgal eder
    "strip",               # hazır bakır şerit           → bedava, kesim gerektirir
]
```

Bütün ağırlığı taşıyan iki yüklem `model.py`'da:

- `contacts_every_path_hole` — lehim yolu geçtiği **her** padde lehimlidir; tel yalnızca
  iki ucuna değer, aradaki deliklerin üzerinden geçer. Bunu yanlış bilmek, ekranda
  görünenden başka türlü bağlanmış bir kart üretir ve hiçbir yerde ses çıkarmaz.
- `is_crossing_blocked` — bakır düzlemini işgal eden, dolayısıyla kesişemeyen iletkenler.

Bu yüzden `connectivity.py` ("elektriksel olarak ne birleşik") ile `occupancy.py`
("fiziksel olarak ne yolda") ayrı modüller.

> `solder-bridge` ayrı bir tür değil — **iki padlik `solder-trace`**. Tek bir kavram,
> tek bir kural seti.

### 4.5 Bağlantı motoru
`(delik, yüz)` düğümleri üzerinde **union-find**. Her iletken komşu düğümleri
birleştirir; komponent pini kendi deliğinin üst ve alt yüzünü bağlar.
Çıktı: **fiziksel net listesi**.

> Bu motor yanlışsa her şey yanlış. Ayrı paket, ayrı test suiti, altın dosya testleri.

### 4.6 Lehim yolu — fiziksel model (D8)

Bitişik padlerin lehimle birleştirilerek oluşturulan iletken yol. TR pratiğinde
"lehim yolu çekmek". İki inşa biçimi:

| Biçim | Nasıl | Kullanım |
|---|---|---|
| **`solder-trace`** (saf) | Padler arasına doğrudan lehim akıtılır | Kısa yerel bağlantılar |
| **`solder-trace-wired`** (omurgalı) | Kalaylı bakır tel veya bacak kırpıntısı padler boyunca yatırılıp her padde lehimlenir | Güç/toprak rayları, uzun yollar |

```python
@dataclass(frozen=True, slots=True)
class SolderTraceConductor:
    kind: Literal["solder-trace", "solder-trace-wired"]
    path: tuple[HoleCoord, ...]       # INVARIANT: 4-komşu bitişik zincir
    spine: SpineSpec | None = None    # kalaylı bakır / bacak kırpıntısı + kesit
    buildup: SolderBuildup = "normal" # kesit tahmini
```

`geometry.validate_orthogonal_chain` bu koddaki tek komşuluk denetimi. Elle düzenlenmiş
bir dosya bunu ihlal ederse **uyarıyla** açılır ve DRC raporlar — kullanıcıyı kendi
projesinden kilitlemek yerine.

**Geometrik kısıt — router'ı doğrudan belirler.**
2.54 mm pitch'te tipik pad çapı ~1.9 mm →

- **Ortogonal komşu:** merkez arası 2.54 mm, **pad kenarları arası ≈ 0.6 mm** → kolayca
  köprülenir. Lehim yolunun tek meşru yönü. Yol = pad grafiğinde **4-komşu Manhattan yolu**.
- **Çapraz komşu:** merkez arası 3.59 mm, kenar arası ≈ 1.7 mm → belirgin şekilde zor,
  fazla lehim ister. **Varsayılan kapalı**, açılırsa ağır cezalı + uyarılı.

**Elektriksel model.**
Lehim özdirenci ≈ 15 µΩ·cm (Sn63Pb37) / ≈ 13 µΩ·cm (SAC305) — bakırın (1.68 µΩ·cm)
**yaklaşık 8-9 katı**. Etkin kesit `buildup` profilinden tahmin edilir.

| Örnek: 10 pad (25.4 mm) | Direnç | 3 A'de düşüm / kayıp |
|---|---|---|
| Saf lehim, ~0.3 mm² kesit | ≈ 13 mΩ | 38 mV / 114 mW |
| 0.6 mm kalaylı bakır omurgalı | ≈ 1.35 mΩ | 4.0 mV / 12 mW |

Omurgalı satır **paralel direnç** olarak hesaplanır: bakır omurga ve çevresindeki lehim
aynı boy üzerinde birbirine yapışıktır, ikisi de akım taşır. Yalnız bakırı saymak
1.51 mΩ verirdi; lehim dalı bunu 1.35 mΩ'a çeker. `drc.py` bu modeli kullanıyor.

→ **Omurga, direnci yaklaşık bir mertebe düşürüyor.** Araç bunu hesaplayıp söylemeli:
*"Bu net 3 A taşıyor, saf lehim yolu sınırda — omurga ekle."*

**Kesişim.** Lehim yolu lehim yüzünde yükseltilmiş fiziksel bir yapı: `bare-wire` ile
aynı katmanda, **kesişemez**. Üzerinden yalnızca `insulated-wire` atlayabilir.

**Asıl tehlike: 0.6 mm'lik komşuluk.** Lehim yolu, farklı nete ait bir padin ortogonal
komşusundan geçtiğinde kaza eseri köprülenme riski yüksektir. Delikli plaket
inşasının en yaygın arıza sebebi budur ve §5.2 R5' kuralının konusudur.

**Malzeme etkileşimi.** Ucuz pertinaks (FR-2 fenolik kâğıt) padleri, uzun süreli ısı
altında FR-4'e göre çok daha kolay **kalkar**. Uzun saf lehim yolu + FR-2 = pad kalkma
riski → §5.2 R5''.

---

## 5. Doğrulama Katmanı

### 5.1 LVS (Layout vs. Schematic)
Fiziksel net listesi ↔ şema net listesi izomorfizmi. Üç hata sınıfı:

- **OPEN** — şemada aynı net, kartta ayrı → eksik bağlantı
- **SHORT** — şemada ayrı net, kartta birleşik → kısa devre
- **FLOATING** — hiçbir nete bağlanmayan iletken

### 5.2 DRC kuralları

Planda 11 kural ve dört alt kural vardı; gerçekleşen 22. Numaralar tabloda kaldı çünkü
kaynakta ve `CHANGELOG`'da onlarla anılıyorlar; yanlarında kuralın **gerçek id'si** var,
`drc.py` bunları o adla raporluyor.

| # | id | Kural | Seviye |
|---|---|---|---|
| 1 | `component-body-overlap` | Gövde çakışması (courtyard) | hata |
| 2 | `component-off-board` | Kart sınırı dışı yerleşim | hata |
| 3 | `pin-not-connected` | Bağlanmamış pin (netlist karşılaştırması) | hata |
| 4 | `conductor-crossing` | Bakır düzlemini paylaşan iletkenlerin kesişimi | hata |
| — | `conductor-off-board` | Kart dışına çıkan iletken | hata |
| — | `solder-trace-invalid-path` | Lehim yolu ortogonal zincir değil | hata |
| — | `cut-track-conflict` | Kesilmiş strip deliğinde pin — hiçbir şeye lehimli | hata |
| — | `mounting-hole-conflict` | Montaj deliğinin yediği padde pin | hata |
| — | `edge-connector-conflict` | Delinmemiş parmakta pin | hata |
| — | `unknown-footprint` | Kütüphanenin tanımadığı footprint | hata |
| **5'** | `solder-trace-proximity` | **Lehim yolu komşuluk riski**: yol, farklı nete ait bir padin ortogonal komşusundan geçiyor (≈0.6 mm) | **uyarı, yüksek öncelik** |
| **5''** | `pad-lifting-risk` | FR-2/pertinaks + saf lehim yolu uzunluğu > eşik | uyarı |
| **5'''** | `solder-trace-too-long` | Saf lehim yolu > 5-6 pad → omurga öner | uyarı |
| 6 | `current-capacity` | Net akımı vs. tel kesiti / lehim yolu etkin kesiti | uyarı |
| 7 | `creepage-clearance` | 2.54 mm ≈ 300 V sınırı — şebeke devrelerinde | **uyarı, kalın** |
| 8 | `component-too-tall` | Yükseklik / gabari çakışması (3D'den) | uyarı |
| 9 | `heat-proximity` | TO-220 / güç direnci yanında elektrolitik | uyarı |
| 10 | `lead-bend-too-long` | Aşırı uzun bacak bükümü | uyarı |
| — | `jumper-under-body` | Bir gövdenin altında kalan üst yüz jumper'ı | uyarı |
| — | `mounting-hole-clearance` | Montaj deliği başına yer yok | uyarı |

**Komutlar belgeyi tutarlı tutar, DRC tasarım kalitesini raporlar.** Id'ler tekil,
referanslar çözülür, yollar kartın üstünde, model değişmezleri geçerli → **hata, mutasyon
reddedilir**. Çakışan gövdeler, köprüleme riski, yetersiz bakır → **DRC raporlar, asla
reddetmez.** Yeni bir denetimin nereye ait olduğu buradan bakılır: sonuç hâlâ bir *belge*
mi (DRC), değil mi (komut).

**Beşinci kural — `solder-trace-proximity` — bu dosyadaki en değerli kural**, ve nerede
öttüğü ince ayarlıdır: bir **pinin** yanından geçen yolda öter, başka bir yolun yanından
geçende değil, ve fiziksel çift başına bir kez. İkisinde de boşluk aynı 0.6 mm; fark
dikkattir. Yolun yanındaki yol, şu an sizin çektiğiniz, baktığınız yüzde, aynı fazda olan
bir yoldur — ve paralel dönüşler yoğun delikli plaketin kurulma biçimidir. NE555 önce
lehimle route edilince aracın az önce route ettiği kartta **51 bulgu** çıkıyordu; 30'u yol
yanı yol, 20'si aynı boşluğun iki uçtan iki kez sayılması. Router riski hâlâ fiyatlıyor,
yani etrafından dolaşıyor; sadece söylediğiniz stille artık tartışmıyor.

---

## 6. Algoritmalar---

## 6. Algoritmalar

**Router** — katmanlı grid üzerinde A\*/Lee maze + **rip-up & reroute**.
Net sıralaması kritikliğe göre (güç ve toprak önce, ray olarak).

### 6.1 Maliyet tablosu

| Primitif | Adım maliyeti | Sabit maliyet | Kısıt |
|---|---|---|---|
| `lead-bend` | ~0 | 0 | ≤3-4 delik, yalnız komponent pininden |
| **`solder-trace`** | **çok düşük** | ~0 | 4-komşu · ≤5-6 pad · kesişemez · komşuluk riski |
| **`solder-trace-wired`** | **düşük** | orta (omurga hazırlama) | 4-komşu · sınırsız · kesişemez |
| `bare-wire` | uzunluk×k | orta | serbest yön · kesişemez |
| `insulated-wire` | uzunluk×k | yüksek (kes/soy/lehimle) | kesişebilir |
| `top-jumper` | uzunluk×k | çok yüksek | kesişebilir · gövde alanını işgal eder |

Ek cezalar: kesişim (bare/solder yolu için ∞, insulated için orta) · **her yeni ayrı
iletken için sabit ceza** (az sayıda uzun yol, çok sayıda kısa yoldan montajı kolaydır)
· DRC risk cezaları (R5' komşuluk riski maliyet fonksiyonuna doğrudan girer, sonradan
uyarı olarak değil).

> **R5''yi maliyete gömmek kritik.** Router, lehim yolunu farklı-net padlerin yanından
> geçirmemeyi *tercih ederse*, üretilen layout sadece geçerli değil aynı zamanda
> **lehimlenmesi kolay** olur. Rakiplerin hiçbiri yapılabilirliği maliyet fonksiyonuna
> koymuyor.

### 6.2 Ray (bus) stratejisi — yüksek fan-out netler

GND ve V+ gibi çok bacaklı netler nokta-nokta route edilmez. Delikli plakette standart
pratik: bir satır/sütun boyunca **omurgalı lehim yolu rayı** çekip pinleri kısa saplarla
raya bağlamak. Router bunu ayrı bir strateji olarak tanıyor:

1. Net fan-out'u eşiği aşarsa ray moduna geç
2. Pin bulutuna en iyi uyan satır/sütunu seç (medyan eksen)
3. Ray = `solder-trace-wired`, saplar = `solder-trace` veya `lead-bend`
4. Rayı kart kenarına yakın tut (komşuluk riski azalır, ölçüm probu erişimi artar)

### 6.3 Yerleştirme optimizasyonu

Simulated annealing. Hamleler: ötele / döndür / iki komponenti takasla.
**Determinizm zorunlu:** tohumlu RNG, aynı girdi → aynı layout.

Planda maliyet **HPWL** (yarım-çevre tel uzunluğu) + DRC cezaları + mekanik kısıtlar diye
yazılmıştı. İki yerde daha ileri gitti, ikisi de kullanımdan çıktı:

**Önce dizilir, sonra tavlanır.** `placer.arrange` tavlayıcı hiç koşmadan **netlist'ten**
bir yerleşim kuruyor ve yeniden başlatmaların yarısı ondan başlıyor. Tavlama bir dizilişi
iyileştirir, dizilişi icat etmez — ve her yeniden başlatmanın kullanıcının kendi
yerleşiminden başlaması, aramanın hep parçaların zaten bulunduğu yerin etrafını
örneklemesi demekti. Parçalar bağlantıya göre sıralanıyor, üç ya da daha çok parçaya
uzanan güç/toprak netleri o grafiğin dışında bırakılıyor (her şeye değen bir ray her şeyi
komşu yapar), konnektörler kenarı önce alıyor, geri kalanı şeritlere paketleniyor.

**Maliyet HPWL değil, "bunu kurmak ne tutar".** Her aday route ediliyor ve route
maliyetiyle ölçülüyor. Bunun bir tuzağı var ve pahalıya patladı: karşılaştırma ancak
hepsi **aynı boş karttan** sorulursa bir cevap. Değildi — temel, kullanıcının kendi
belgesi, bakırı hâlâ kendi parçalarına uyuyor, dolayısıyla router yapacak bir şey bulamıyor
ve neredeyse sıfır dönüyordu; her aday ise parçaları oynattığı için bütün kartı yeniden
fiyatlandırıyordu. Sonuç: **otomatik yerleştirme, route edilmiş bir kartta hiçbir şeyi asla
oynatamıyordu** — yani insanın sormayı düşüneceği her kartta. `_build_cost` artık
karşılaştırmadan önce bakırı soyuyor.

**Bir şey yapmamak da bir aday.** Ve değişmeyen bir yerleşim neyi karşılaştırdığını
söylüyor: on saniyelik iş "yerleşim değişmedi" diye raporlanınca bozuk bir düğmeden
ayırt edilemiyor, "kurması elinizdekinden daha ucuz bir şey bulunamadı (796'ya karşı 845)"
diye raporlanınca insanın itiraz edebileceği bir cevap oluyor.

### 6.4 Beklenti yönetimi

"Butona bas, mükemmel layout" vaadi verilmiyor. Hedef **interaktif asistan**: route
edilemeyen netler açıkça raporlanır, sessizce bırakılmaz. Forumlardaki asıl şikâyet
("4 bağlantıyı bağlayamadan bıraktı") tam olarak bu tuzağa düşmekten kaynaklanıyor.

Plandaki "< 100 ms'de yeniden route" tutmadı ve tutturulmaya da çalışılmadı: tam bir
autoroute saniyeler sürüyor, bir `QThread`'de koşuyor ve ilerleme gösteriyor. Karşılığında
**`reroute`** var — yalnızca etkilenen netleri yeniden çeken ayrı bir komut — ve canlı
çalışan DRC. Verilen söz hız değil, ne yapamadığını söylemek.

---

## 7. Lehim Rehberi Spesifikasyonu

### 7.1 Adım sıralaması — iki anahtarlı
Fiziksel gerçek: parçalar gruplar hâlinde takılır → kart çevrilir → lehimlenir →
bacaklar kesilir → o bölgenin bağlantıları yapılır. Dolayısıyla sıralama
**(a) fonksiyonel blok** ve **(b) gövde yüksekliği** anahtarlarıyla yapılır.

```
Faz 0  Hazırlık        malzeme listesi, alet, havya sıcaklığı, kart kesimi, A1 referans işareti
Faz 1  En alçak        üst yüz jumper telleri, yatık direnç ve diyotlar
Faz 2  Soketler        IC soketleri  (IC'lerin kendisi EN SONA — ısı + ESD)
Faz 3  Küçük gövde     seramik/film kondansatör, TO-92 transistör
Faz 4  Orta gövde      elektrolitik, TO-220, kristal
Faz 5  Yüksek/mekanik  konnektör, potansiyometre, klemens, soğutucu
Faz 6  Lehim yüzü      çıplak tel ve köprüler (blok blok, her grup takıldıkça)
Faz 7  Uzun teller     izoleli bağlantılar
Faz 8  Kapanış         IC'leri sokete tak, son kontrol, kontrollü güç verme prosedürü
```

### 7.2 Her adım kartında bulunanlar
- Ref, değer, footprint, **tam delik koordinatları** (`R3: C7 → C11, 4 delik açıklık`)
- Polarite / oryantasyon uyarısı + pin-1 işareti
- **Bacak bükme şablonu** (`10.16 mm / 4 delik`)
- 3D'den otomatik render edilmiş, o parçanın vurgulandığı kare
- Üst görünüm **ve aynalanmış lehim yüzü görünümü** (kullanıcıların en çok hata yaptığı yer)
- Havya sıcaklığı / lehim teli / flux notu (ada büyüklüğüne göre)

### 7.3 Tel kesim listesi
```
uzunluk = Manhattan yol uzunluğu (mm)
        + 2 × (kart kalınlığı + büküm payı)
        + 2 × soyma boyu
```
Her tel için: kesit (akımdan hesaplanır), izolasyon tipi, **renk konvansiyonu**
(kırmızı = V+, siyah = GND, ...), delik-delik yol.
**Ayrı bölüm: omurga telleri** (`solder-trace-wired`) — kalaylı bakır tel uzunlukları
ve hangi bacak kırpıntısının nereye yeteceği.

### 7.4 Lehim yolu talimatları (D8)

Her lehim yolu için üretilen adım kartı:

- **Yol tanımı:** `GND rayı: B12 → K12, 10 pad, omurgalı`
- **İnşa biçimi:** saf mı, omurgalı mı; omurgalıysa tel kesiti ve boyu
- **Yön:** tek yönde çalış, soğumuş bölümün üzerine geri dönme
- **Isı bütçesi:** malzemeye göre havya sıcaklığı ve pad başına temas süresi üst sınırı
  (FR-2/pertinaks için belirgin şekilde düşük — pad kalkma riski)
- **Flux zorunlu** notu; padleri önce tek tek hafif kalayla, sonra birleştir
- **Komşuluk uyarısı (R5'):** *"C7 ve F7 padleri farklı nete ait ve yolun 0.6 mm
  yanında — bu iki noktada dikkat, sonra mutlaka izolasyon ölç"*
- **Elektriksel özet:** hesaplanan direnç, net akımında gerilim düşümü ve kayıp

**Teknik notu (otomatik metin):** 3+ pad için lehim yığmak yerine bacak kırpıntısını
veya kalaylı teli omurga olarak kullan — direnç yaklaşık bir mertebe düşer,
mekanik dayanım ve tekrar edilebilirlik belirgin artar.

### 7.5 Doğrulama kontrol noktaları — **farklılaştırıcı**
Netlist'ten deterministik üretilir:
- Her blok sonunda **süreklilik listesi** (bağlı OLMASI gerekenler)
- Her blok sonunda **izolasyon listesi** (bağlı OLMAMASI gerekenler, özellikle güç rayları)
- **DRC risk listesi doğrudan test listesine dönüşür.** R5' ile işaretlenen her
  komşuluk riski, o lehim yolu bitince yapılacak somut bir izolasyon ölçümü olur:
  *"C7 ↔ C8 arası direnç ölç, açık devre olmalı."* Böylece aracın öngördüğü risk ile
  kullanıcının yaptığı ölçüm aynı listeden gelir — delikli plaketin en yaygın arızası
  daha kart bitmeden yakalanır.
- Uzun lehim yolları için **uçtan uca direnç kontrolü** (hesaplanan değer ± tolerans),
  soğuk lehim ve çatlak yakalar
- Güç vermeden önce: V+ ↔ GND direnç makullüğü, elektrolitik polarite taraması, IC yönü
- Güç verme prosedürü: akım sınırlı besleme, beklenen boştaki akım (kullanıcı girerse)

### 7.6 Çıktı formatları
| Format | Not |
|---|---|
| **İnteraktif HTML** | Tek dosya, offline, adımlar tiklenir, ilerleme `localStorage`'da; karta tıklayınca ilgili adım vurgulanır |
| **PDF** | 1:1 baskı doğruluğu — üst görünüm + aynalanmış lehim yüzü, karta tutturulabilir şablon |
| **CSV** | Tel kesim listesi + BOM |
| **JSON** | Makine okunur rehber (ajanlar ve entegrasyonlar için) |

---

## 8. Mimari

### 8.1 Command Bus — tek kural
> **UI hiçbir zaman veri modelini doğrudan değiştirmez.** Her eylem bir komut
> nesnesidir ve tek bir bus'tan geçer.

```
   GUI (2D/3D) ──┐
   CLI         ──┤
   MCP Server  ──┼──►  Command Bus  ──►  Document  ──► 2D / 3D / DRC / LVS / Guide
   Makro/Script──┘      + Undo/Redo        (immutable)
```

Bu tek karardan bedava gelenler: undo/redo · makro kaydı · **deterministik replay
testleri** · oturum kaydı · ajanın ve kullanıcının aynı belgeyi eşzamanlı sürmesi.

### 8.2 Paket düzeni

```
src/perfboard_studio/
  model.py          doküman: her dataclass frozen, hiçbir şey yerinde değişmez
  command.py        command bus + undo/redo + journal
  commands.py       her mutasyon burada bir CommandDefinition
  geometry.py       delik adresleme, ızgara komşuluğu, kart ölçüleri, hazır kart boyları
  footprints.py     61 footprint, hepsi üretiliyor — sıfır asset
  connectivity.py   union-find: ne elektriksel olarak birleşik
  occupancy.py      ne fiziksel olarak yolda
  drc.py  lvs.py    doğrulama katmanı (§5)
  router.py  autoroute.py  placer.py  ratsnest.py      algoritmalar (§6)
  stripboard.py  striproute.py                         stripboard geometrisi ve router'ı
  schematic.py  schematic_export.py                    devre şeması, türetilen ve çizilen
  guide.py  guide_export.py                            lehim rehberi (§7)
  persist.py        .perf okuma/yazma — bayt bayt sabit
  parsers/          KiCad netlist (saf metin → veri)
  ui/               PySide6 + VTK; motor burayı hiç bilmez
  mcp/              MCP sunucusu (§9)
```

**Motor saftır.** `ui/` ve `mcp/` dışında saat yok, RNG yok, dosya sistemi yok, Qt ve VTK
import'u yok. `persist.py` dokümanı metne çevirir; dosyayı **host** okur ve yazar.
Zaman damgasını host basar. Yerleştiricinin simulated annealing'i tohumlu: aynı doküman +
aynı tohum = aynı kart. Bunu bozmak §2'deki diferansiyel kanıtı bozar.

**Headless render pazarlık konusu değil** — MCP'nin render tool'ları, rehber üretimi ve
CI görsel testleri GUI olmadan çalışmalı. `--headless` (`ui/headless.py`) 2D/3D/PDF ve
şemayı üretip DRC + LVS koşuyor; üç işletim sisteminde de.

### 8.3 2D / 3D
- **2D — authoring görünümü.** `QGraphicsView`, sahne birimi = 1 mm (1:1 PDF'in fudge
  faktörü olmamasının sebebi bu). Delik ızgarası **önceden rasterlenmiş tek bir pad
  pixmap'i** olarak basılıyor: 6000 deliği alışılmış yoldan çizmek kare başına 124 ms,
  tek bir even-odd `QPainterPath` ise 5.8 s sürüyordu.
- **3D — doğrulama ve iletişim görünümü.** VTK. Kart **delinir, boyanmaz**: bir yüz, deliği
  çıkarılmış tek bir kiremitin her delikte yinelenmesidir — 945 delikli bir kartın iki yüzü
  böylece iki actor, delik başına boolean çıkarma ile iki bine yakın olurdu.
- **Parçalar malzeme olarak gölgelendirilir.** Phong bir *parlama* tarif eder, bir şeyin
  neden yapıldığını söylemez; `metallic` (0 ya da 1, arası yok) ve `roughness` ise
  söyler. Yansıyacak bir şey olması için oda da **üretilir**, indirilmez.
- **Lehim yolu görselleştirmesi.** Lehim bakırı ıslatır: 3D'de bir yolun merkez çizgisi
  pad düzleminin kendisidir ve yalnız dış yarısı görünür; tel ise bir yarıçap yukarıdadır
  ve iki ucu deliklere iner. Yol **tek bir değişken yarıçaplı tüp** — her lehim noktasında
  şişip aralarda incelen. Bu incelme süs değil: rehberi takip eden insan yol boyunca lehim
  noktalarını sayar.
- Seçim/hover durumu iki yönlü paylaşılır. 2D'de yüz toggle'ı, 3D'de gerçek çevirme.
- **Gövdeler:** parametrik üretim **artı** KiCad'den ödünç alınmış gerçek THT paketleri
  (D6). Üretilen gövde her parça için hâlâ geri düşüş.

### 8.4 3D'nin işlevsel gerekçeleri
1. Yükseklik/çarpışma kontrolü (DRC #8) — 2D'de görünmez
2. Lehim yüzü tel karmaşasının okunması
3. **Montaj animasyonu** — rehber adımlarının 3D oynatımı (D7)
4. **Rehbere otomatik adım görseli** — elle görsel hazırlama derdi biter
5. (v2) Muhafaza tasarımı: yükseklik profili + kontur → STL/GLB

---

## 9. Ajan Entegrasyonu

### 9.1 Taşıma — ikisi birden
- **stdio (birincil).** Claude Code *ve* Antigravity ikisinde de sorunsuz. GUI gerekmez,
  headless döner, CI'da koşar.
- **Streamable HTTP (localhost).** Açık duran GUI'ye bağlanmak için; ajan düzenler,
  kullanıcı canlı görür. **Yeni SSE-only sunucu yazılmayacak** (deprecated).
- **Tuzak:** tüm log **stderr**'e. Kaçak bir `print` stdout'u kirletir ve istemci
  alakasız, anlaşılmaz bir hata gösterir. `perfboard_studio.mcp` altında hiçbir şey
  yazdırmaz; Qt ve VTK import'ları bile modül seviyesinde değil, tool'un içinde
  yapılır — asıl risk onlar, motorun kendisinde zaten `print` yok.

### 9.2 Tool yüzeyi

**Gerçekleşen: 51 tool**, plandaki "~25"e karşı. Tavan tutmadı, kural tuttu ve asıl
istenen kuraldı: her tool `docs/MCP.md`'de bir gruba ve bir gerekçeye bağlı, ve
`test_mcp.py` bunu iki yönden birden denetliyor — dokümante edilmemiş bir tool kimsenin
savunmadığı bir tool, artık var olmayan bir dokümante tool ise ajanı olmayan bir şeye
gönderir. Tool eklemek, satırını ve paragrafını eklemek demek. Liste `docs/MCP.md`'de;
burada tekrarlanmıyor, çünkü iki yerde tutulan bir liste bir kere kaydı bile.

**En kritik ikisi hâlâ aynı:**
- `render_*` — görsel geri bildirim olmadan ajan kör çalışır. Kartı *görebilmeli*.
- `snapshot`/`restore` — ajan deneyip geri alabilmeli.

**Reddedilen bir komut sessizce patlamaz.** Sınırı geçen her sonuç düz JSON, her delik
**adresiyle** (`"C7"`) veriliyor, ve reddedilen bir komut `{"ok": false, "code": ...}`
dönüyor — `CommandBus.dispatch`'in sözleşmesiyle aynı. Ajan bir şey deneyip "hayır"
cevabını alabilmeli.

### 9.3 Proje dosyası ajan-dostu
Stabil anahtar sıralamalı, pretty-print JSON (`.perf` uzantısı, içi JSON).
Git-diff'lenebilir. Uygulama dosyayı izler ve hot-reload eder →
**MCP olmadan bile**, sadece dosya yazan bir Claude Code oturumu çalışır.

---

## 10. Test ve Doğrulama Stratejisi

~2340 test, bir dakikanın altında. Daraltmaya gerek yok, hepsi koşulur.

| Tür | Kapsam |
|---|---|
| **Diferansiyel** | Python motorunun çıktısı, yerini aldığı TypeScript motorunun altın dosyalarına **bayt bayt** uyuyor. "Bütün testler geçiyor" değil, "değiştirdiğimiz şeyle aynı sonucu üretiyor" |
| **Property test** | Rastgele netlist → autoroute → **LVS geçmek ZORUNDA** |
| Altın dosya | Router çıktıları, connectivity, footprint'ler (son IEEE-754 basamağına kadar), rehberin dört çıktısı, şema sayfası |
| Birim | Union-find bağlantı motoru — en kritik bileşen, ayrı suit |
| Round-trip | doküman → kaydet → yükle → **bayt birebir** aynı, 15 altın dosyanın hepsinde |
| Görsel regresyon | 2D render'ın 6 × 6 hücresinin ortalama rengi (`test_render_golden.py`). Mürekkep kapsamını ölçen ilk deneme neredeyse işe yaramazdı — delikli plaket zaten çoğunlukla kart |
| Replay | Kaydedilmiş komut logu → aynı doküman (command bus'tan bedava) |
| Tipler | `mypy --strict src` — motor katı-temiz ve öyle kalmalı. Testler değil, hiç olmadı |

**3D için altın görüntü bilerek yok.** VTK makinede ne OpenGL varsa onunla çiziyor;
üç işletim sistemi matrisinde ortalama-renk karşılaştırması kimsenin elinden bir şey
gelmeyen sebeplerle patlardı. Yerine kararların kendisi sabitleniyor.

**VTK'ya dokunan her test `@requires_offscreen_gl` taşımak zorunda.** GL bağlamı yokken
VTK hata fırlatmaz, süreci öldürür — işaretlenmemiş bir test başarısız olmaz, koşuyu
ortasından özetsiz keser.

CI her push'ta üç işletim sistemi matrisini koşuyor ve bunu ilk günden hak etti: ilk tam
matris Windows'ta bir VTK abort'u ve macOS arm64'te son ULP'de ayrışan iki footprint
altın dosyası buldu — ikisini de Linux göremez.

---

## 11. Yol Haritası

Plandaki hâli **4 kişi, paralel üç şerit, M0–M7, ~5.5 ay part-time** idi. Ekip o
büyüklükte olmadı ve şeritler paralel gitmedi; buna rağmen M0–M7'nin **kapsamı** sırayla
karşılandı, tek istisnası aşağıda. Hangi sürümde ne geldiği `CHANGELOG.md`'de duruyor, o
yüzden burada yalnızca **ne kaldığı** yazılı.

| Milestone | Kapsam | Durum |
|---|---|---|
| **M0** Risk düşürme | 3D stres testi · command bus + doküman iskeleti · dikey dilim | ✅ — sonucu D5'i değiştirdi (`tools/bench-3d`) |
| **M1** Editör + kütüphane | 2D grid editör, THT footprint kütüphanesi, parametrik gövdeler, kaydet/yükle | ✅ |
| **M2** Bağlantı + doğrulama | Union-find, KiCad netlist import, ratsnest, DRC v1 (**R5' dahil**), **LVS**, lehim yolu elektriksel modeli | ✅ |
| **M3** Router + yerleştirme | A\*/Lee + rip-up & reroute, lehim yolu primitifi + ray stratejisi, SA yerleştirme | ✅ |
| **M4** 3D tam | Montaj animasyonu, patlatılmış görünüm, yükseklik/çarpışma DRC, headless render | ✅ |
| **M5** Lehim rehberi | Sıralama motoru, adım kartları, tel kesim listesi, **doğrulama kontrol noktaları**, HTML+PDF+CSV | Kod ✅ · **dogfood ❌** |
| **M6** MCP + CLI | 51 tool, iki taşıma, dosya izleme, snapshot/restore | ✅ |
| **M7** Lansman | TR/EN i18n, dokümantasyon, örnek projeler, CI, paketleme, imzalama | İmzalama dışında ✅ (§14) |

**Kalan tek kapsam maddesi: M5'in dogfood testi.** Rehberi takip ederek gerçek bir kart
sıfırdan lehimlenip çalıştırılmadı. Pazarlık konusu değil, ve duyuru (§14) bundan önce
yapılmaz: bu araç insanları havyanın başına gönderiyor, ve rehberin doğru olduğunu
söyleyen tek şey şu an testler.

### Sonraki işler

Plandan gelmeyen, kullanımdan gelen işler. Sıra bağlayıcı değil.

- **Şema sayfasında dal (T) bağlantısı.** Çizilen tel tam olarak iki pin arasında; dört
  pinli bir net üç telle çiziliyor. Bir telin ortasına bağlanmak dördüncü bir uç türü
  ister ve iki uçtan biri her oynadığında yerinden kayar — çözülebilir, çözülmedi.
- **Hiyerarşik sayfa ve bus.** Yok. 24 parçalık kartlarda ihtiyaç duyulmadı.
- **`docs/` Türkçesi.** Arayüz tam Türkçe, `README` iki dilde; `docs/` yalnız İngilizce.
- **Kod imzalama** — §12.

---

## 12. Açık Konular

Kapanmış olanlar da duruyor, cevaplarıyla — bir sorunun nasıl kapandığı, kapalı olduğu
bilgisinden fazlasını taşıyor.

**İsim — kapandı: Perfboard Studio.** Adaylar PerfStudio · PadPilot · Protoforge ·
SolderPlan idi; PerfStudio seçildi, on sürüm taşıdı ve v0.11'de bırakıldı. Okunuşu bir
sebep ("perf" ile "perv" arasında tek harf var), ama asıl sebep kısaltmanın yazılımdaki
anlamı: "perf" performans demek — Linux'ta profiler'ın adı, ve AMD yıllarca **GPU
PerfStudio** adlı bir grafik profiler'ı yayınladı. Yani ismi seçtiren gerekçe —
keşfedilebilirlik — tam da kendi aleyhine çalışıyordu.

Tanıtıcının `perfboard` değil `perfboard-studio` olması ayrı bir karar: `perfboard`
plaketin kendi adı, bu programın değil. Jenerik kelimeyi paket adı olarak sahiplenmek
ürünle malzemeyi karıştırır. `.perf` uzantısı ve `DOCUMENT_FORMAT_VERSION` kıpırdamadı.

**Footprint kütüphanesi kaynağı — kapandı: üretiliyor.** "M1'de karar verilecek" diyordu;
61 footprint bir avuç parametreden hesaplanıyor, sıfır asset, ve kütüphanede olmayan bir
parça parametrelerini adında taşıyan bir id ile isteniyor. KiCad footprint'lerini bundle
etme alternatifi alınmadı — ama 3D **gövdeler** için tam olarak o yapıldı (D6), ve
CC-BY-SA klasörü orada duruyor.

**Kod imzalama — hâlâ açık.** Windows EV sertifikası ~$300/yıl, Apple notarization
$99/yıl. Şu an imzasız yayınlanıyor: Windows'ta SmartScreen uyarısı çıkıyor, macOS paketi
ad-hoc imzalı ama notarize değil. Kabul edilmiş bir durum, çözülmüş değil — ve otomatik
güncellemenin kurulumu **başlatmamasının** sebeplerinden biri de bu (§14).

---

## 13. Riskler

| Risk | Etki | Azaltma |
|---|---|---|
| ~~Linux WebKitGTK'da WebGL yetersiz~~ | — | **Kapandı, riskten kaçınılarak.** M0 ölçtü ve cevap "bu riski taşımaya değmez" çıktı: çatı Qt + VTK oldu (D5), platform sorusu ortadan kalktı. Yerini alan risk, sürücünün VTK'ya yetmemesi — `PERFBOARD_STUDIO_SIMPLE_3D=1` onun kaçış yolu |
| Autorouter beklenti tuzağı | **Yüksek** | "Interaktif asistan" konumlandırması; route edilemeyen netler açıkça raporlanır, sessizce bırakılmaz |
| 3D'de fotogerçekçilik scope creep | Orta | Hedef sabit: "doğru ve anlaşılır". **Hedef bir kez bilerek yükseltildi:** parçalar Phong yerine malzeme olarak gölgelendiriliyor, çünkü hiçbir Phong değeri alüminyumu alüminyum göstermiyordu — ve bir DIP ile kristal kutuyu ayırt edememek doğruluk sorunuydu, süs sorunu değil. Bütçe hâlâ sınırlı: iki ağır parçanın ikisi de kapatılabiliyor |
| MCP tool sayısı patlaması | Orta | **Gerçekleşen: 51 tool.** Tavan tutmadı, kural tuttu: her tool `docs/MCP.md`'de bir gruba ve bir gerekçeye bağlı (11 grup; sonuncusu "tasarım", yukarıdaki "Devre girişi" notuna bak). ~25 sayısı yüzey bilinmeden atılmış bir tahmindi; korumaya çalıştığı şey sayı değil gerekçe zorunluluğuydu ve o yürürlükte. Kuralın bir kez kaydığı da ölçüldü: `reroute` sunucuda vardı, dokümanda yoktu — sayıyı üç yerde üç farklı yapan buydu, ve artık `test_mcp.py` kaymayı bir daha bırakmıyor |
| Lisans kirlenmesi (GPL'li rakip kod) | **Yüksek** | Clean-room tutuldu: DIYLC/VeroRoute kaynağına bakılmadı; `docs/prior-art.md` neye bakıldığını yazıyor. Apache-2.0 olmayan tek parça KiCad'in 3D mesh'leri (D6), kendi lisansıyla tek klasörde |
| Kapsamın 3 kart tipine yayılması | Orta | v1 sadece pad-per-hole. Stripboard artık uçtan uca: `stripboard.py` geometri, `striproute.py` router, 2D'de kesme modu, ve `placer.py` strip hizasını skorluyor |
| **Lehim yolu güvenilirliği**: araç kullanıcıyı kırılgan yapıya teşvik edebilir | **Yüksek** | DRC bilgilendirir, engellemez: uzun saf yolda omurga önerir, FR-2'de ısı uyarısı verir, R5' risklerini test adımına çevirir. Karar kullanıcının, veri aracın |

---

## 14. Açık Kaynak Lansman Kontrol Listesi

Kutular gerçek durumu gösterir; yarısı yapılmış bir madde işaretlenmez, ne kaldığı yazılır.

- [x] README: ne işe yarar + 30 saniyelik demo GIF (`docs/images/assembly.gif`) + kurulum
- [x] Apache-2.0 LICENSE + NOTICE
- [x] CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue/PR şablonları (`.github/ISSUE_TEMPLATE/`,
      "kuramadığım kart" şablonu dahil)
- [x] CI: test + lint (`ruff`) + tipler (`mypy --strict`) + 3 işletim sistemi matrisi +
      görsel regresyon (`test_render_golden.py`, suite'in içinde). 3 platform **build**'i
      `release.yml`'de, etikete basınca
- [x] Release: installer üç platformda da var (`release.yml`), Windows imzasız / macOS
      ad-hoc imzalı ama notarize değil — §12'nin kabul ettiği durum. Otomatik güncelleme
      yazıldı: uygulama günde bir kez (ve Yardım menüsünden istendiğinde) GitHub'a bakıyor,
      yeni sürümü kartın üstünde bir şeritle duyuruyor, platforma uygun dosyayı indirip
      release'e eklenen `SHA256SUMS` ile doğruluyor. **Kurulumu başlatmıyor ve bu bir
      eksik değil, karar:** imzasız bir kurulumu kullanıcı adına çalıştırmak (Windows'ta
      yükseltme, macOS'ta /Applications içindeki paketi değiştirme, Linux'ta çalışan
      AppImage'ın üstüne yazma) kötü amaçlı yazılımdan ayırt edilemeyen ve geri dönüşü
      olmayan bir mekanizma. Son tıklama kullanıcının
- [x] Örnek projeler: 555 flaşör, LM317 güç kaynağı, Arduino shield, gitar pedalı
      (`examples/`, dördü de netlist + kart)
- [x] MCP kurulum dokümanı (`docs/MCP.md`: Claude Code, ve JSON config okuyan her şey —
      Claude Desktop, Antigravity, Cursor)
- [ ] TR + EN dokümantasyon: README iki dilde ve arayüzün tam Türkçe kataloğu var.
      **Kalan:** `docs/` (MCP, RELEASING, prior-art) yalnızca İngilizce
- [ ] Duyuru: Hackaday, r/diyelectronics, r/AskElectronics, EEVblog, diyAudio, Show HN
      — M5'in dogfood testi kapanmadan yapılmaz
