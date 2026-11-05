"""Translating the interface (PLAN.md milestone M7).

WHY NOT Qt LINGUIST. Qt's own mechanism -- ``tr()``, ``.ts`` files, ``lrelease`` -- is
the obvious answer for a Qt application and is the wrong one here. It needs a build step
producing binary ``.qm`` files, which this project has no build step to hang off; the
catalogue lives in an XML format nothing else in the repo can read; and a missing or
stale translation is invisible until someone runs the application in that language. This
module is a dict, checked by tests, and it costs one function call at each string.

THE RULES, both enforced by tests/test_i18n.py:

  EVERY KEY IS THE ENGLISH STRING. There is no separate identifier to keep in step with
  anything, so a translation cannot silently attach to the wrong message, and English is
  never "missing" -- it is the key.

  THE CATALOGUE MAY NOT DRIFT. A test scans the UI source for every translated literal
  and fails if the catalogue names a string the interface no longer has, which is how a
  translation file usually rots. Missing translations are allowed and fall through to
  English, because a half-translated interface is useful and a crash is not.

WHAT IS NOT TRANSLATED, deliberately: hole addresses (``C7``), DRC rule ids, net names,
component references, file paths and the engine's own messages. The addresses are the
tool's vocabulary and are the same in every language; the rule ids are identifiers.
DRC and LVS message text is generated in the engine, which has no UI dependency and is
where the differential proof lives -- translating it there would mean translating
strings that golden fixtures compare byte for byte.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

#: Languages with a catalogue. English is the source language and needs none.
AVAILABLE = ("en", "tr")

TURKISH: Mapping[str, str] = {
    # -- menus ---------------------------------------------------------------
    "&File": "&Dosya",
    "&Edit": "Dü&zen",
    "&Wiring": "&Kablolama",
    "&View": "&Görünüm",
    "&Help": "Y&ardım",
    "No mounting holes or edge connectors": "Montaj deliği ya da kenar konnektörü yok",
    "{count} mounting hole": "{count} montaj deliği",
    "{count} mounting holes": "{count} montaj deliği",
    "{count} edge connector": "{count} kenar konnektörü",
    "{count} edge connectors": "{count} kenar konnektörü",
    "{count} to check at the bench": "tezgâhta kontrol edilecek {count} yer",
    "To check at the bench": "Tezgâhta kontrol edilecekler",
    "Not wrong: the build guide turns each of these into a check to make with a meter or by eye.": "Hata değil: montaj rehberi bunların her birini ölçü aletiyle ya da gözle yapılacak bir kontrole dönüştürür.",
    "An older package of this part.": "Bu parçanın eski bir kılıfı.",
    "Use the Current Package": "Güncel Kılıfı Kullan",
    "Use the C&urrent Package": "&Güncel Kılıfı Kullan",
    "{count} part is on the current package now.": "{count} parça artık güncel kılıfında.",
    "{count} parts are on the current package now.": "{count} parça artık güncel kılıfında.",
    "This board": "Bu kart",
    "The hole it is drilled at, or beside when it is in the border.": "Delindiği delik; kenar payındaysa yanındaki delik.",
    "How far the bore sits from its hole, across and down: into the border, for a corner hole clear of every pad.": "Montaj deliğinin, adres deliğinden yatay ve dikey uzaklığı: köşe deliğinin hiçbir pede değmemesi için kenar payına doğru.",
    "Offset": "Kaydırma",
    "outside {hole}": "{hole} deliğinin dışında",
    "Inset from the edge (holes)": "Kenardan uzaklık (delik)",
    "Mounting holes and edge connectors": "Montaj delikleri ve kenar konnektörleri",
    "None yet.": "Henüz yok.",
    "FR-4 (glass epoxy)": "FR-4 (cam epoksi)",
    "FR-2 (phenolic paper)": "FR-2 (pertinaks)",
    "FR-1 (phenolic paper)": "FR-1 (fenolik kâğıt)",
    "Could not be wired": "Kablolanamadı",
    "{count} connection could not be wired: why is in Problems.": "{count} bağlantı kablolanamadı: nedeni Sorunlar'da.",
    "{count} connections could not be wired: why is in Problems.": "{count} bağlantı kablolanamadı: nedenleri Sorunlar'da.",
    "perfboard, stripboard, move to, take to, transfer": "perfboard, delikli kart, şerit kart, taşı, aktar, geçir",
    "No part in the Library matches that.": "Kütüphanede buna uyan bir parça yok.",
    "Next Problem": "Sonraki Sorun",
    "Wire the connections that are left, as Next does on Wiring.": "Kalan bağlantıları kablolar; Kablolama adımında Sonraki düğmesinin yaptığı gibi.",
    "&Go to It": "&Oraya Git",
    "Auto-wire Its &Connections": "&Bağlantılarını Otomatik Kablola",
    "Auto-wire {count} Connection": "{count} Bağlantıyı Otomatik Kablola",
    "Auto-wire {count} Connections": "{count} Bağlantıyı Otomatik Kablola",
    "Nothing in the list to go to.": "Listede gidilecek bir şey yok.",
    "Solderless breadboard": "Lehimsiz breadboard",
    "Solderless breadboard, wide channel (ESP32 / modules)": "Lehimsiz breadboard, geniş oluklu (ESP32 / modüller)",
    "As the material is sold": "Malzemenin satıldığı gibi",
    "&Design the Board…": "Kartı Tas&arla…",
    "Start from a board you can buy -- green with an edge connector, brown phenolic -- and change its size, pads, holes, printing and colour, seen as you go.": (
        "Satın alabileceğiniz bir karttan başlayın -- kenar konnektörlü yeşil, kahverengi fenolik -- ve ölçüsünü, pedlerini, deliklerini, yazılarını ve rengini görerek değiştirin."
    ),
    "Design the Board": "Kartı Tasarla",
    "Board families": "Kart aileleri",
    "A name for this board, to save it as your own": "Kendi kartınız olarak kaydetmek için bir ad",
    "Save as My Board…": "Kendi Kartım Olarak Kaydet…",
    "Stock size": "Hazır ölçü",
    "Size in mm": "Ölçü (mm)",
    "Grid and pads": "Izgara ve pedler",
    "Pitch": "Aralık",
    "Pad diameter": "Ped çapı",
    "Drill": "Delik çapı",
    "Edge connector along two edges": "İki kenar boyunca kenar konnektörü",
    "Edges": "Kenarlar",
    "Shape": "Şekil",
    "Width": "Genişlik",
    "Mounting holes": "Montaj delikleri",
    "A hole in each corner": "Her köşede bir delik",
    "Diameter": "Çap",
    "Screw head": "Vida başı",
    "Legend and text": "Numaralandırma ve yazılar",
    "Letters": "Harfler",
    "Numbers": "Sayılar",
    "Printed on it": "Üzerinde yazan",
    "Mask": "Maske",
    "Pad finish": "Ped kaplaması",
    "Your own size": "Kendi ölçünüz",
    "no edge connector": "kenar konnektörü yok",
    "Made from {template}: the size in centimetres, as the board prints it.": (
        "{template} kalıbından: ölçü santimetre olarak, kartın bastığı gibi."
    ),
    "Pad per hole": "Delik başına ped",
    "Solderable breadboard": "Lehimlenebilir breadboard",
    "The short edges": "Kısa kenarlar",
    "The long edges": "Uzun kenarlar",
    "Rounded": "Yuvarlatılmış",
    "Oblong": "Oval",
    "Square": "Kare",
    "Along the top": "Üstte",
    "Along the bottom": "Altta",
    "Top and bottom": "Üstte ve altta",
    "Not printed": "Basılmamış",
    "Down the left": "Solda",
    "Down the right": "Sağda",
    "Down both sides": "İki yanda",
    "Green": "Yeşil",
    "No mask": "Maskesiz",
    "Tinned (HASL)": "Kalaylı (HASL)",
    "Tinned, lead-free": "Kalaylı, kurşunsuz",
    "Bare copper": "Çıplak bakır",
    "Gold (ENIG)": "Altın (ENIG)",
    "Green double-sided (FR-4, tinned)": "Yeşil çift yüzlü (FR-4, kalaylı)",
    "Phenolic single-sided (bare copper)": "Pertinaks tek yüzlü (çıplak bakır)",
    "&Circuit": "D&evre",
    "&Board": "Ka&rt",
    "&Export": "Dışa Ak&tar",
    "Sho&w on the Board": "Kartta &Göster",
    "&Build Guide…": "Montaj &Rehberi…",
    "&Schematic…": "Ş&ema…",
    "1:1 &PDF (parts side + solder side)…": "1:1 &PDF (parça + lehim yüzü)…",
    "3D S&napshot…": "3D &Görüntü…",
    "3D &Model (STEP)…": "3D &Model (STEP)…",
    # -- file ----------------------------------------------------------------
    "&New Board": "&Yeni Kart",
    "New Board from This &Design…": "Bu Tasarımdan Yeni Kart &Oluştur…",
    "The same circuit on a board with nothing on it yet — how a design tried on a breadboard goes on to perfboard. The board it is on now, and its file, stay exactly as they are.":
        "Aynı devre, üzerinde henüz hiçbir şey olmayan bir kartta — breadboard'da denenen bir tasarım perfboard'a böyle geçer. Şimdiki kart ve dosyası olduğu gibi kalır.",
    "There is no circuit here to take to another board.": "Burada başka bir karta taşınacak bir devre yok.",
    "Same &Layout on a Solderable Breadboard…": "Aynı Yerleşimle &Lehimlenebilir Breadboard'a…",
    "Every part and every jumper on the same holes of a solderable breadboard, as a new document — how a circuit that works on the breadboard is made permanent. The breadboard and its file stay exactly as they are.":
        "Her parça ve her jumper, lehimlenebilir bir breadboard'un aynı deliklerinde, yeni bir belge olarak — breadboard'da çalışan bir devre böyle kalıcı hâle getirilir. Breadboard ve dosyası olduğu gibi kalır.",
    "Only a solderless breadboard's layout moves to a solderable one.": "Yalnızca lehimsiz bir breadboard'un yerleşimi lehimlenebilir bir karta taşınır.",
    "The same layout on a solderable breadboard: {parts} part(s) and {wires} wire(s), each on the holes it had.":
        "Aynı yerleşim lehimlenebilir bir breadboard'da: {parts} parça ve {wires} tel, her biri eski deliklerinde.",
    "{count} part(s) waiting in the design: choose the board they go on.": "Tasarımda {count} parça bekliyor: hangi "
                                                                           "karta gideceklerini seçin.",
    "&Open…": "&Aç…",
    "&Save": "&Kaydet",
    "Save &As…": "&Farklı Kaydet…",
    "Reload from Dis&k": "Diskten Ye&niden Yükle",
    "Reload from disk?": "Diskten yeniden yüklensin mi?",
    # Ayar&ları, not &Ayarları: "&Aç…" already claims A in this menu, and two items with
    # the same accelerator means one of them cannot be reached from the keyboard at all.
    "Board &Features…": "Kart &Öğeleri…",
    "Open Recen&t": "&Son Kullanılanlar",
    "(nothing yet)": "(henüz yok)",
    "&Clear List": "Listeyi &Temizle",
    "&Import from KiCad…": "KiCad'den &İçe Aktar…",
    # Ş rather than S: "&Son Kullanılanlar" has S in this menu, and Turkish treats the two
    # as different letters -- which is exactly what makes it a free accelerator here.
    "Write the circuit as a sheet: SVG to embed or edit, PDF to print, PNG to "
    "paste into a message asking somebody what is wrong with it.": (
        "Devreyi bir sayfa olarak yazın: gömmek ya da düzenlemek için SVG, basmak için "
        "PDF, birine neyin yanlış olduğunu sormak üzere mesaja yapıştırmak için PNG."
    ),
    "Write the board as solids for a mechanical CAD program: the board with its holes "
    "and every part as the room it takes, named by its reference — to draw the "
    "enclosure round.": (
        "Kartı mekanik bir CAD programı için katı olarak yazın: delikleriyle kart ve her "
        "parça kapladığı hacim olarak, referansıyla adlandırılmış — kutusunu çevresine "
        "çizmek için."
    ),
    "&Quit": "&Çıkış",
    # -- edit ----------------------------------------------------------------
    "&Undo": "&Geri Al",
    "&Redo": "&Yinele",
    # Kopyala takes p and Yapıştır takes r: G, Y, D, T, A, K and S are all spoken for in
    # this menu already, and an item whose accelerator is claimed cannot be reached from
    # the keyboard at all.
    "Cop&y": "Ko&pyala",
    "&Paste": "Yapıştı&r",
    "Dupl&icate": "&Çoğalt",
    "Rotate &Clockwise": "Saat Yönünde &Döndür",
    "Rotate Counter-clock&wise": "Saat Yönünün &Tersine Döndür",
    "&Mirror": "&Aynala",
    "Toggle &Lock": "&Kilidi Aç/Kapat",
    "&Delete": "&Sil",
    # -- draw ----------------------------------------------------------------
    "&Solder Trace": "&Lehim Yolu",
    "&Reinforced Solder Trace": "&Telli Lehim Yolu",
    "&Bare Wire": "&Çıplak Tel",
    "&Insulated Wire": "İ&zoleli Tel",
    "&Jumper Over the Parts": "Parçaların Üstünden &Jumper",
    "Join adjacent pads with solder. Orthogonal steps only — solder spans the "
    "0.6 mm gap to the next pad and not the 1.7 mm diagonal one. Click where "
    "the run starts and wherever it turns: every pad between is soldered. "
    "Enter, right-click or a double-click finishes.": (
        "Komşu pedleri lehimle birleştirir. Yalnızca düz adımlar — lehim yandaki pede olan "
        "0,6 mm boşluğu kapatır, çaprazdaki 1,7 mm boşluğu kapatmaz. Yolun başladığı ve "
        "döndüğü yerlere tıklayın: aradaki her ped lehimlenir. Enter, sağ tık ya da çift "
        "tık bitirir."
    ),
    "A solder trace laid over a tinned wire: about ten times lower resistance, and what a "
    "power or ground rail longer than five or six pads wants.": (
        "Kalaylı bir telin üzerine çekilen lehim yolu: yaklaşık on kat düşük direnç; beş "
        "altı pedden uzun bir güç ya da toprak rayının istediği de budur."
    ),
    "Tinned wire on the solder side. Cannot cross other copper. Click both "
    "ends.": (
        "Lehim yüzünde kalaylı tel. Başka bakırın üzerinden geçemez. İki ucuna da tıklayın."
    ),
    "May cross anything, at the cost of stripping it. Click both ends.": (
        "Her şeyin üzerinden geçebilir; bedeli uçlarını soymaktır. İki ucuna da tıklayın."
    ),
    "An insulated wire on the parts' side, hopping over everything below. It takes room "
    "the parts would use.": (
        "Parça yüzünde, alttaki her şeyin üstünden atlayan izoleli tel. Parçaların "
        "kullanacağı yeri kaplar."
    ),
    "C&ut Strip": "Şeridi &Kes",
    "Sto&p the Current Tool": "Aracı &Bırak",
    # -- nets ----------------------------------------------------------------
    # "&Net" becomes the plural "Netler": a menu named with the same word in both
    # languages would be an untranslated entry, which the catalogue tests refuse.
    "&Connect Two Pins": "&İki Pini Bağla",
    "&New Net…": "&Yeni Net…",
    "&Add Pins to Net": "Nete &Pin Ekle",
    "&Finish Adding Pins": "Pin Eklemeyi &Bitir",
    "&Edit Net…": "Neti &Düzenle…",
    "&Disconnect Selected Pins": "Seçili Pinleri &Ayır",
    "De&lete Net": "Neti Si&l",
    "Delete net": "Neti sil",
    "Name": "Ad",
    "Class": "Sınıf",
    "Signal": "Sinyal",
    "Ground — wired first, and wants a rail": "Toprak — önce kablolanır, ray ister",
    "Power — wired after ground, same reason": "Güç — topraktan sonra kablolanır, aynı "
                                                "sebeple",
    "Current": "Akım",
    "Voltage": "Gerilim",
    "not stated": "belirtilmedi",
    "state a voltage": "gerilim belirtin",
    # -- place and route -----------------------------------------------------
    "&Rearrange Parts": "Parçaları Yeniden &Diz",
    "&Try Another Arrangement": "&Başka Bir Yerleşim Dene",
    "&Auto-wire Everything": "Hepsini &Otomatik Kablola",
    "Auto-wire the S&election": "&Seçileni Otomatik Kablola",
    "Redo All &Wiring": "Bütün Kablolamayı &Yeniden Yap",
    "Redo Wiring of the Se&lection": "Seçilenin Kablolamasını Yeniden Y&ap",
    "Remove Ou&t-of-Date Wiring": "Eski&miş Kablolamayı Kaldır",
    "Wiring St&yle": "Kablolama Ta&rzı",
    "&Try each and keep the best": "&Hepsini dene, en iyisini tut",
    "&Solder trace where possible": "Mümkün olan her yerde &lehim yolu",
    "&Balanced": "&Dengeli",
    "&Wire where possible": "Mümkün olan her yerde &tel",
    "Bend component &legs where possible": "Mümkün olan her yerde &bacak bük",
    "Wire the board once with every style, measure what each would cost to build — traces, "
    "wires, wire length, bridging risk — and keep the best. Takes about as long as wiring "
    "it twice; the comparison is reported.": (
        "Kartı her tarzla bir kez kablolar, her birinin yapım maliyetini ölçer — lehim "
        "yolları, teller, tel uzunluğu, köprüleme riski — ve en iyisini tutar. İki sıradan "
        "kablolama kadar sürer; karşılaştırma raporlanır."
    ),
    "Every connection a solder trace can make, IS one — wire only where a trace physically "
    "cannot get there. A short jumper carries a run over anything it must cross. On the "
    "NE555 example: all 14 connections, not one wire.": (
        "Bir lehim yolunun yapabildiği her bağlantı lehim yolu olur — tel yalnızca lehim "
        "yolunun fiziksel olarak ulaşamadığı yerde. Kesmesi gereken her şeyin üzerinden "
        "kısa bir atlama teli geçirir. NE555 örneğinde: 14 bağlantının hepsi, tek tel yok."
    ),
    "No commitment: weigh each kind of connection on its own cost and take the cheapest "
    "each time. The default. On a populated board this comes out as wire far more often "
    "than people expect.": (
        "Bağlılık yok: her bağlantı türü kendi maliyetiyle tartılır ve her seferinde en "
        "ucuzu alınır. Varsayılan budur. Dolu bir kartta beklenenden çok daha sık tel "
        "çıkar."
    ),
    "For anyone assembling with wire: every connection a wire can make is a "
    "wire, including the rails. Solder only where a wire cannot reach.": (
        "Telle kuranlar için: bir telin yapabildiği her bağlantı tel olur, raylar dahil. "
        "Lehim yalnızca telin ulaşamadığı yerde."
    ),
    "Fold a component's own leg to a nearby hole first, then solder, then wire. "
    "The cheapest connection there is — no wire to cut, and already soldered "
    "at one end.": (
        "Önce parçanın kendi bacağını yakındaki bir deliğe bükün, sonra lehim, sonra tel. "
        "Olabilecek en ucuz bağlantı — kesilecek tel yok, bir ucu zaten lehimli."
    ),
    "Wiring style": "Kablolama tarzı",
    "applies the next time you auto-wire": "bir sonraki otomatik kablolamada geçerli olur",
    "Lay Wires Along the &Grid": "Telleri &Izgara Boyunca Döşe",
    "When a Trace Must &Cross": "Lehim Yolu Kesi&şirse",
    "When a trace must cross": "Lehim yolu kesişirse",
    "&Hop over it with a short jumper": "Kısa bir &atlama teliyle üstünden geç",
    "Make the whole connection one &wire": "Bağlantının tamamını tek bir &tel yap",
    "&Never use wire; leave it unwired": "&Hiç tel kullanma; kablolanmadan bırak",
    "Solder trace as far as it goes, and one short insulated jumper over each "
    "thing it may not cross — what somebody building by hand does. Most of the "
    "run is solder and only the crossing costs a piece of wire. The default.": (
        "Lehim yolu gidebildiği yere kadar gider, geçemeyeceği her şeyin üstünden de "
        "kısa bir izoleli atlama teli geçer — elle kart yapan birinin yaptığı gibi. "
        "Yolun çoğu lehimdir, yalnızca kesişme bir parça tele mal olur. Varsayılan."
    ),
    "A connection that has to cross something becomes one insulated wire from "
    "end to end, for anybody who would rather run one clean wire than solder up "
    "to a jumper.": (
        "Bir şeyin üstünden geçmesi gereken bağlantı baştan sona tek bir izoleli tel "
        "olur; bir atlama teline kadar lehim çekmektense tek temiz bir tel döşemeyi "
        "tercih eden için."
    ),
    "No wire of any kind, whichever wiring style is chosen: solder traces only. A "
    "connection a trace cannot make is left unwired and named, rather than made with wire "
    "you did not ask for. On a crowded board that can be several, and moving parts is "
    "usually the answer.": (
        "Kablolama tarzı ne olursa olsun hiçbir türde tel yok: yalnızca lehim yolu. Bir "
        "yolun yapamadığı bağlantı, istemediğiniz bir telle yapılmak yerine kablolanmadan "
        "bırakılır ve adıyla bildirilir. Kalabalık bir kartta bunlar birkaç tane olabilir; "
        "çözüm çoğu zaman parçaları taşımaktır."
    ),
    "Run every wire square to the grid, along the rows and columns of holes, "
    "with as few bends as the board allows — the way wire is dressed on "
    "perfboard. Off, a wire is one straight run at whatever angle, which is "
    "shorter and crosses everything near it.": (
        "Her teli ızgaraya dik olarak, delik satırları ve sütunları boyunca, kartın izin "
        "verdiği en az bükümle döşer — perfboard'da tel böyle döşenir. Kapalıyken tel, "
        "açısı ne olursa olsun tek bir düz parçadır; daha kısadır ve yakınındaki her şeyi "
        "keser."
    ),
    "on": "açık",
    "off": "kapalı",
    # -- view ----------------------------------------------------------------
    "Flip Board (parts side / solder side)": "Kartı Çevir (parça yüzü / lehim yüzü)",
    "&Fit Board": "Karta &Sığdır",
    "Zoom &In": "&Yakınlaştır",
    "Zoom &Out": "&Uzaklaştır",
    "Show &Missing Connections": "Eksik &Bağlantıları Göster",
    "Show Hole &Addresses": "Delik &Adreslerini Göster",
    "&Hatch Copper on the Far Side": "Karşı Yüzdeki Bakırı &Taralı Göster",
    "Measure &Distance": "&Mesafe Ölç",
    "&Go to Part…": "Parçaya G&it…",
    "Filter parts…  (R37, 10k, TO-220, C7)": "Parçaları süz…  (R37, 10k, TO-220, C7)",
    "Show &3D View": "&3D Görünümü Göster",
    # Ca&mera, not &Camera: "Board &Colour" has C in the same menu.
    "Reset 3D Ca&mera": "3D K&amerayı Sıfırla",
    # Par&çaları / Parça &Listesini / &Netleri / L&VS: ç, L, N and V are the free letters
    # in the Turkish View menu, where S, Y, U, B, D, T, M, G, K, R and Ş are all spoken
    # for and P went to "&Patlatılmış Görünüm". The library takes ç, the Part List L; the
    # English Part List has no letter at all, every one of its own being taken.
    "Show &Library": "Kütüp&haneyi Göster",
    "Show &Nets": "&Netleri Göster",
    "Show P&arts": "Par&çaları Göster",
    "Show Part Val&ues": "Parça De&ğerlerini Göster",
    "Print each part's value after its reference — 4k7, 100n, 1N4148 — on the board and on "
    "the 1:1 print, to check the board against the build at a glance.": (
        "Her parçanın değerini referansının yanına yazar — 4k7, 100n, 1N4148 — kartta ve 1:1 "
        "baskıda; kartı bir bakışta montajla karşılaştırmak için."
    ),
    "Show &Problems": "Sorunlar&ı Göster",
    "Board &Colour": "Kart R&engi",
    "As the &Board Says": "&Kartın Kendi Rengi",
    "Green (FR-4)": "Yeşil (FR-4)",
    "Blue": "Mavi",
    "Black": "Siyah",
    "Red": "Kırmızı",
    "Purple": "Mor",
    "White": "Beyaz",
    "Orange (phenolic)": "Turuncu (pertinaks)",
    "&Keyboard Shortcuts…": "&Klavye Kısayolları…",
    "Check for &Updates…": "&Güncellemeleri Denetle…",
    "Check Automatically at &Startup": "Açılışta Otomatik &Denetle",
    "&About Perfboard Studio": "Perfboard Studio &Hakkında",
    # -- the update check (updater.py), from "is there one?" to "here is the file" ---
    "Ask GitHub whether a newer release has been published.":
        "GitHub'a sorar: daha yeni bir sürüm yayınlanmış mı?",
    "Look once a day, as the window opens. Nothing is downloaded or installed "
    "without you asking for it.":
        "Günde bir kez, pencere açılırken bakar. Siz istemeden hiçbir şey indirilmez, "
        "hiçbir şey kurulmaz.",
    "Check for updates?": "Güncellemeler denetlensin mi?",
    "Should Perfboard Studio look for new versions?": "Perfboard Studio yeni sürümlere baksın mı?",
    "It would ask GitHub once a day, as the window opens, and tell you when a "
    "newer release exists. Nothing is downloaded or installed without you "
    "asking for it. Either answer can be changed in the Help menu.":
        "Günde bir kez, pencere açılırken GitHub'a sorar ve daha yeni bir sürüm varsa "
        "size söyler. Siz istemeden hiçbir şey indirilmez, hiçbir şey kurulmaz. İki "
        "yanıt da Yardım menüsünden değiştirilebilir.",
    "Check for Updates": "Güncellemeleri Denetle",
    "Do Not Check": "Denetleme",
    "Checking for updates…": "Güncellemeler denetleniyor…",
    "Perfboard Studio {version} is the newest release.":
        "En yeni sürüm zaten bu: Perfboard Studio {version}.",
    "Could not check for updates: {reason}": "Güncellemeler denetlenemedi: {reason}",
    "Perfboard Studio {new} is available — you have {old}.":
        "Perfboard Studio {new} çıktı — sizde {old} var.",
    "Download": "İndir",
    "Fetch the installer into your Downloads folder and check it arrived intact.":
        "Kurulum dosyasını İndirilenler klasörüne indirir ve eksiksiz geldiğini doğrular.",
    "Open the Download Page": "İndirme Sayfasını Aç",
    "There is no installer for this build. If you installed with pip, the "
    "update is “pip install -U perfboard-studio”; the release page carries "
    "everything else.": (
        "Bu yapı için kurulum dosyası yok. pip ile kurduysanız güncelleme "
        "“pip install -U perfboard-studio”; geri kalan her şey sürüm sayfasında."
    ),
    "What Changed": "Ne Değişti",
    "Open this release's notes on GitHub.": "Bu sürümün notlarını GitHub'da açar.",
    "Show the File": "Dosyayı Göster",
    "Open the folder the installer was saved in.":
        "Kurulum dosyasının kaydedildiği klasörü açar.",
    "Hide": "Gizle",
    "Stop mentioning this version. The next one will still be announced when "
    "it is released.":
        "Bu sürümü bir daha anmaz. Bir sonraki çıktığında yine haber verilir.",
    "Downloading… {done:.0f} of {all:.0f} MB": "İndiriliyor… {done:.0f} / {all:.0f} MB",
    "Downloading… {done:.0f} MB": "İndiriliyor… {done:.0f} MB",
    "Downloaded to {path}": "Şuraya indirildi: {path}",
    "Its checksum matched. Close Perfboard Studio before you run it.":
        "Sağlama toplamı tuttu. Çalıştırmadan önce Perfboard Studio'yu kapatın.",
    "This release published no checksum, so the file was not verified.":
        "Bu sürüm sağlama toplamı yayınlamamış, dosya doğrulanamadı.",
    "The update could not be downloaded.": "Güncelleme indirilemedi.",
    "The download did not match its published checksum, so it was deleted.":
        "İndirilen dosya yayınlanan sağlama toplamıyla uyuşmadı, o yüzden silindi.",
    "The download could not be saved.": "İndirilen dosya kaydedilemedi.",
    # -- the shortcut card, the mode banner and the empty-board guidance -------
    "Keyboard Shortcuts": "Klavye Kısayolları",
    "Action": "Eylem",
    "Shortcut": "Kısayol",
    "On the board": "Kart üzerinde",
    "⌀{drill} mm, {head} mm head": "⌀{drill} mm, {head} mm vida başı",
    "Nothing is drilled into a solderless breadboard.": "Lehimsiz bir breadboard'a delik açılmaz.",
    "A breadboard's edges are its rails, not fingers.": "Breadboard'un kenarlarında parmak değil, raylar var.",
    "cathode is the banded end": "katot, bantlı uçtur",
    "TO-92 legs 1-2-3 left to right, flat face towards you, legs down":
        "TO-92 bacakları soldan sağa 1-2-3, düz yüz size dönük, bacaklar aşağıda",
    "TO-220 legs 1-2-3 left to right, printed face towards you, tab behind":
        "TO-220 bacakları soldan sağa 1-2-3, yazılı yüz size dönük, metal sırt arkada",
    "Middle-drag": "Orta tuşla sürükle",
    "Pan the board": "Kartı kaydır",
    "Select &All": "Tü&münü Seç",
    "Every part on the board, or every symbol on the sheet when the sheet has the keyboard.":
        "Karttaki bütün parçalar; klavye şemadaysa şemadaki bütün semboller.",
    "Space+drag": "Boşluk+sürükle",
    "Mouse Wheel": "Fare Tekerleği",
    "&Zooms": "&Yakınlaştırır",
    "&Scrolls (Ctrl+Wheel Zooms)": "&Kaydırır (Ctrl+Tekerlek yakınlaştırır)",
    "The wheel zooms about the pointer; a trackpad that says it is one pans.":
        "Tekerlek imlecin çevresinde yakınlaştırır; kendini dokunmatik yüzey olarak bildiren bir yüzey kaydırır.",
    "The wheel and two fingers on a trackpad move the board; Ctrl+wheel or a pinch zooms.":
        "Tekerlek ve dokunmatik yüzeyde iki parmak kartı kaydırır; Ctrl+tekerlek ya da sıkıştırma yakınlaştırır.",
    "Pinch, or Ctrl+wheel": "Sıkıştır ya da Ctrl+tekerlek",
    "Wheel": "Tekerlek",
    "Zoom about the pointer": "İmlecin çevresinde yakınlaştır",
    "Drag a part": "Bir parçayı sürükle",
    "Shift- or Ctrl-click": "Shift ya da Ctrl ile tıkla",
    "Add to the selection, or take out of it": "Seçime ekle ya da seçimden çıkar",
    "Move it, snapping to the nearest hole": "Taşır, en yakın deliğe oturtur",
    "Arrow keys": "Ok tuşları",
    "Nudge the selected part one hole (Shift: five)": "Seçili parçayı bir delik kaydır (Shift: beş)",
    "Right-click": "Sağ tık",
    "Finish the trace or net being drawn": "Çizilmekte olan lehim yolunu ya da neti bitir",
    "Finish it without moving the pointer": "İmleci oynatmadan bitir",
    "Turn the corner of the trace being drawn the other way":
        "Çizilmekte olan yolun köşesini öbür yana çevir",
    "Leave the current mode": "Geçerli kipten çık",
    "Double-click a net": "Bir nete çift tıkla",
    "Wire just that net": "Yalnızca o neti kablola",
    "Click a problem": "Bir soruna tıklayın",
    "Zoom to the holes it names": "Andığı deliklere yakınlaş",
    "Undo": "Geri al:",
    "Nothing to undo": "Geri alınacak bir şey yok",
    "Redo": "Yinele:",
    "Nothing to redo": "Yinelenecek bir şey yok",
    "Placing": "Yerleştiriliyor:",
    "click a hole, Esc cancels": "bir deliğe tıklayın, Esc iptal eder",
    "Drawing": "Çiziliyor:",
    "click both ends, Esc cancels": "iki ucu da tıklayın, Esc iptal eder",
    "click where it turns, Enter or right-click finishes, / flips the corner, Esc cancels":
        "döndüğü yere tıklayın, Enter veya sağ tık bitirir, / köşeyi çevirir, Esc iptal eder",
    "Cutting tracks": "Şerit kesiliyor",
    "click a hole, Esc ends": "bir deliğe tıklayın, Esc bitirir",
    "Measuring": "Ölçülüyor",
    "click two holes": "iki deliğe tıklayın",
    "from": "başlangıç",
    "Esc ends": "Esc bitirir",
    "Adding pins to": "Pin ekleniyor:",
    "Enter or right-click finishes, Esc cancels": "Enter veya sağ tık bitirir, Esc iptal eder",
    "no pins yet": "henüz pin yok",
    "The guide has no steps yet: it is written from the parts on the board.":
        "Rehberde henüz adım yok: rehber karttaki parçalardan yazılır.",
    "{count} part(s) in the design are not on the board yet: Place on the Board puts them there, arranged.":
        "Tasarımdaki {count} parça henüz kartta değil: Karta Yerleştir onları dizerek "
        "oraya koyar.",
    "Copied {parts} part(s), {conductors} conductor(s)": "{parts} parça, {conductors} iletken kopyalandı",
    "{count} lead bend(s) left behind: a bent leg belongs to a part that was not in the selection":
        "{count} bacak bükme geride kaldı: bükülen bacak, seçimde olmayan bir parçanın",
    "Pasted {parts} part(s) and {conductors} conductor(s) at {hole}":
        "{parts} parça ve {conductors} iletken {hole} deliğine yapıştırıldı",
    "Duplicated {parts} part(s) and {conductors} conductor(s) at {hole}":
        "{parts} parça ve {conductors} iletken {hole} deliğine çoğaltıldı",
    "{count} conductor(s) would have run off the board": "{count} iletken kartın dışına taşacaktı",
    "{ref} at {hole}": "{ref}, {hole} deliğinde",
    "untitled": "adsız",
    "{path} is a directory, not a .perf document.": "{path} bir klasör, .perf belgesi değil.",
    "Cannot open {path}: {reason}.": "{path} açılamıyor: {reason}.",
    "Cannot open {path}: not UTF-8 text. A .perf document is JSON.":
        "{path} açılamıyor: UTF-8 metin değil. Bir .perf belgesi JSON'dur.",
    "{count} conductor(s) are now out of date; Ctrl+R clears and rewires them":
        "{count} iletken eskidi; Ctrl+R temizler ve yeniden kablolar",
    "{count} out-of-date conductor(s) removed first": "önce {count} eskimiş iletken kaldırıldı",
    "“{style}” beat {count} other style(s)": "“{style}” diğer {count} stilden iyi çıktı",
    "Filter nets…  (gnd, power, U1)": "Netleri süz…  (gnd, güç, U1)",
    "Filter parts…  (resistor, dip, 5mm)": "Parçaları süz…  (direnç, dip, 5mm)",
    # -- toolbar ---------------------------------------------------------------
    # Short labels for the buttons; the menus keep the full wording. Qt draws an action's
    # iconText on a toolbar and its text in a menu, so these are the only place they differ.
    "Auto-wire": "Otomatik Kablola",
    "Delete": "Sil",
    # "Flip Side" was here until the toolbar stopped making its own action for it and
    # started sharing the View menu's, whose button label is "Flip".
    "Flip": "Çevir",
    # -- the connect tool ------------------------------------------------------
    "Connecting": "Bağlanıyor",
    "click the first pin, Esc cancels": "ilk pine tıklayın, Esc iptal eder",
    "Connecting from": "Bağlantı başlangıcı:",
    "click the pin it joins, Esc cancels": "birleşeceği pine tıklayın, Esc iptal eder",
    # -- docks ---------------------------------------------------------------
    "Library": "Kütüphane",
    "Nets": "Netler",
    "Parts": "Parçalar",
    "3D View": "3D Görünüm",
    "Problems": "Sorunlar",
    # -- dialogs -------------------------------------------------------------
    "Rows": "Satır",
    "Material": "Malzeme",
    # -- board setup: which kind of board this is -----------------------------
    "Strips run": "Şeritler",
    # -- board setup: the sizes you can buy -----------------------------------
    "Board": "Kart",
    # -- board setup: pad shape and the printed legend ------------------------
    "Pad shape": "Ped şekli",
    "Pad length": "Ped uzunluğu",
    "Long axis": "Uzun eksen",
    "Round": "Yuvarlak",
    "Oblong — solder bridges easily along the long axis": (
        "Oval — lehim uzun eksen boyunca kolayca köprü yapar"
    ),
    "Down a column": "Sütun boyunca",
    "Along a row": "Satır boyunca",
    "Row digits": "Satır basamağı",
    "Columns printed as": "Sütunlarda basılı",
    "Rows printed as": "Satırlarda basılı",
    "marked every": "işaret aralığı",
    "digits": "basamak",
    "What the board prints along its columns when that is not the addresses: runs of "
    "letters or of numbers from the first hole on. A-Z, A-P is A to Z and then A to P "
    "again. Left empty, the board prints the addresses.": (
        "Kart sütunlar boyunca adresleri değil de kendi numaralandırmasını basıyorsa o: "
        "ilk delikten itibaren harf ya da sayı dizileri. A-Z, A-P: önce A–Z, sonra "
        "yeniden A–P. Boş bırakılırsa kart adresleri basar."
    ),
    "What the board prints down its rows when that is not the addresses: runs of "
    "letters or of numbers from the first hole on. A-Z, 1-4 is A to Z and then 1 to 4. "
    "Left empty, the board prints the row numbers.": (
        "Kart satırlar boyunca adresleri değil de kendi numaralandırmasını basıyorsa o: "
        "ilk delikten itibaren harf ya da sayı dizileri. A-Z, 1-4: önce A–Z, sonra 1–4. "
        "Boş bırakılırsa kart satır numaralarını basar."
    ),
    "Only every Nth hole carries a label: 5 is a board numbered 05, 10, 15 and so on.": (
        "Yalnızca her N. delikte bir etiket var: 5, kartın 05, 10, 15 diye numaralandığı "
        "demek."
    ),
    "Numbers are padded to this many digits: 2 prints 5 as 05. Letters never are.": (
        "Sayılar bu kadar basamağa tamamlanır: 2 ile 5, 05 olarak basılır. Harfler "
        "tamamlanmaz."
    ),
    "{hole}, printed {printed}": "{hole}, kartta {printed} yazar",
    '2 prints row 7 as "07", the way most such boards do.': (
        '2, 7. satırı "07" olarak basar; bu kartların çoğu böyle yapar.'
    ),
    # -- board features: mounting holes and edge connectors -------------------
    "Where": "Yer",
    "Size": "Ölçü",
    "Remove": "Kaldır",
    "Mounting hole": "Montaj deliği",
    "Edge connector": "Kenar konnektörü",
    "Hole diameter": "Delik çapı",
    "How many holes in from each corner; 0 uses the corner hole itself.": (
        "Her köşeden kaç delik içeride; 0, köşe deliğinin kendisini kullanır."
    ),
    "Add Corner Holes": "Köşe Delikleri Ekle",
    "Add Edge Connector": "Kenar Konnektörü Ekle",
    "Edge": "Kenar",
    "Top": "Üst",
    "Bottom": "Alt",
    "Left": "Sol",
    "Right": "Sağ",
    "First hole": "İlk delik",
    "Fingers": "Parmak sayısı",
    "That inset does not fit on this board.": "Bu kaçıklık bu karta sığmıyor.",
    "&Exploded View": "&Patlatılmış Görünüm",
    "Play": "Oynat",
    "Pause": "Duraklat",
    "Play the build from here, one step at a time.": (
        "Montajı buradan itibaren adım adım oynatır."
    ),
    "Drag back to see the board part-way through the build.": (
        "Geriye sürükleyerek kartın montajın ortasındaki hâlini görün."
    ),
    "Back one step. The left arrow key does the same while the 3D view has the focus.": (
        "Bir adım geri. 3D görünüm odaktayken sol ok tuşu da aynısını yapar."
    ),
    "Forward one step. The right arrow key does the same while the 3D view has the focus.": (
        "Bir adım ileri. 3D görünüm odaktayken sağ ok tuşu da aynısını yapar."
    ),
    "Finished board": "Bitmiş kart",
    "Bare board": "Boş kart",
    "Lift every part off the board, with a line down to the holes it goes in.": (
        "Her parçayı karttan kaldırır; girdiği deliklere inen bir çizgi ile birlikte."
    ),
    "Height limit": "Yükseklik sınırı",
    "No limit": "Sınırsız",
    "Clear height inside the case, above the board. Taller parts are reported by DRC.": (
        "Kutunun içinde, kartın üstünde kalan net yükseklik. "
        "Daha yüksek parçaları DRC bildirir."
    ),
    "Unsaved changes": "Kaydedilmemiş değişiklikler",
    "Open failed": "Açılamadı",
    "Import failed": "İçe aktarılamadı",
    "Export failed": "Dışa aktarılamadı",
    "Working": "Çalışıyor",
    "Drawing the build steps…": "Montaj adımları çiziliyor…",
    # -- messages that used to be built as English f-strings -------------------
    "Esc to stop placing.": "yerleştirmeyi bitirmek için Esc.",
    "Cannot place there: {why}": "Oraya yerleştirilemez: {why}",
    "{ref} is only named by a net; edit the net to remove it.": (
        "{ref} yalnızca bir nette adı geçiyor; kaldırmak için neti düzenleyin."
    ),
    "{count} would not fit": "{count} tanesi sığmadı",
    "Ctrl+R wires it; Ctrl+Shift+A tries another arrangement.": (
        "Ctrl+R bağlantıları kurar; Ctrl+Shift+A başka bir yerleşim dener."
    ),
    "Pressing Rearrange again tries another arrangement.": (
        "Yeniden Diz'e yeniden basmak başka bir yerleşim dener."
    ),
    "Done: {what}": "Yapıldı: {what}",
    "Undone: {what}": "Geri alındı: {what}",
    "Redone: {what}": "Yinelendi: {what}",
    "Everything is wired already, so Auto-wire plans it again.": (
        "Her şey zaten kablolanmış; Otomatik Kablola hepsini yeniden planlıyor."
    ),
    "Wired again, and it came out exactly as it is. A different Wiring ▸ Wiring Style or "
    "Wiring ▸ When a Trace Must Cross gives different wiring.": (
        "Yeniden kablolandı ve tıpatıp aynısı çıktı. Farklı bir kablolama için Kablolama ▸ "
        "Kablolama Tarzı ya da Kablolama ▸ Lehim Yolu Kesişirse ayarını değiştirin."
    ),
    "This board is wired by its own planner — cuts and links on stripboard, jumpers on a "
    "breadboard — so this does not apply to it.": (
        "Bu kartı kendi planlayıcısı kurar — şeritli kartta kesim ve köprü, breadboard'da "
        "jumper — bu yüzden bu ayar ona uygulanmaz."
    ),
    "On a breadboard this shapes the jumpers: along a row and down a column, the way the "
    "pre-bent kits are made, and round a part rather than under it. Off, each jumper is "
    "one straight run from clip to clip.": (
        "Breadboard'da jumper'ların biçimini belirler: hazır bükülmüş setlerdeki gibi bir "
        "satır boyunca ve bir sütun aşağı, bir parçanın altından değil etrafından. "
        "Kapalıyken her jumper klipsten klipse tek bir düz parçadır."
    ),
    "Planned again, and it came out exactly as it is. "
    "Moving a part is what gives a different one.": (
        "Yeniden planlandı ve tıpatıp aynısı çıktı. Farklı bir sonucu "
        "bir parçayı taşımak verir."
    ),
    "Nothing to re-route": "Yeniden kablolanacak bir şey yok",
    "Ctrl+Z puts them back.": "Ctrl+Z geri getirir.",
    "Nothing to wire:": "Kablolanacak bir şey yok:",
    "Move or delete whatever is in the way and try again.": (
        "Yolda ne varsa taşıyın ya da silin, sonra yeniden deneyin."
    ),
    "From {pin} — click the pin it joins.": "{pin} pininden — birleşeceği pine tıklayın.",
    "Could not write the guide: {err}": "Rehber yazılamadı: {err}",
    "{name} and {count} more": "{name} ve {count} dosya daha",
    "Written to {folder}, with {count} thing(s) it could not cover:": (
        "{folder} klasörüne yazıldı; kapsayamadığı {count} şey var:"
    ),
    "Could not write the schematic: {err}": "Şema yazılamadı: {err}",
    "{parts} part(s)": "{parts} parça",
    "Perfboard layout design, verification and a soldering guide.": (
        "Perfboard yerleşim tasarımı, doğrulama ve bir lehimleme rehberi."
    ),
    "Code: Apache-2.0 · 3D part models: CC-BY-SA 4.0, from KiCad": (
        "Kod: Apache-2.0 · 3D parça modelleri: CC-BY-SA 4.0, KiCad'den"
    ),
    "Parts that move: {moved} of {movable}": (
        "Yer değiştiren parçalar: {movable} taneden {moved}"
    ),
    "locked, and left where they are: {locked}.": "kilitli olduğu için yerinde kalan: {locked}.",
    "Estimated connection length: {before} mm → {after} mm.": (
        "Tahmini bağlantı uzunluğu: {before} mm → {after} mm."
    ),
    "Each arrangement found was wired, and this is the one cheapest to build (cost {cost}; "
    "seed {seed}).": (
        "Bulunan her yerleşim kablolandı; bu, kurulması en ucuz olanı (maliyet {cost}; "
        "tohum {seed})."
    ),
    "Overlapping bodies: {before} → {after}.": "Çakışan gövdeler: {before} → {after}.",
    "Pins sharing a hole: {before} → {after}.": "Aynı deliği paylaşan pinler: {before} → {after}.",
    "{ref} is in the design, not on the board yet.": "{ref} tasarımda var, ama henüz kartta değil.",
    "In the design, not on the board yet.": "Tasarımda var, ama henüz kartta değil.",
    "{ref} is in the design, not on the board yet. Place on the Board puts it there.": (
        "{ref} tasarımda var, ama henüz kartta değil. Karta Yerleştir onu karta koyar."
    ),
    "{ref} is named by a net and is not in the design at all.": (
        "{ref} yalnızca bir nette adı geçiyor; tasarımda hiç yok."
    ),
    "Could not read the file.": "Dosya okunamadı.",
    # -- what the findings panel calls each rule ---------------------------------
    "Parts overlap": "Parçalar çakışıyor",
    "Part off the board": "Parça kartın dışında",
    # -- a part dragged across the board, while it is dragged ---------------------------
    "and {count} more": "ve {count} parça daha",
    "off the board": "kartın dışında",
    "{count} pin(s) in a used hole": "{count} pin dolu bir delikte",
    "{count} pin(s) where there is no pad": "{count} pin pedi olmayan bir yerde",
    "Part hangs past the edge": "Parça kenardan taşıyor",
    "Part too tall for the case": "Parça kutuya göre fazla yüksek",
    "Wires or traces cross": "Teller ya da yollar kesişiyor",
    "Wire or trace off the board": "Tel ya da yol kartın dışında",
    "Too close for the voltage": "Gerilime göre fazla yakın",
    "Two nets in one hole": "Bir delikte iki net",
    "Too thin for the current": "Akıma göre fazla ince",
    "Pin on a cut strip": "Kesik şerit üzerinde pin",
    "Two pins in one hole": "Bir delikte iki pin",
    "Pin on an edge finger": "Kenar konnektörü parmağında pin",
    "Heat source too close": "Isı kaynağı fazla yakın",
    "Jumper under a part": "Parçanın altında jumper",
    "Bent leg too long": "Bükülen bacak fazla uzun",
    "Too close to a mounting hole": "Montaj deliğine fazla yakın",
    "Pin on a mounting hole": "Montaj deliğinde pin",
    "No hole there": "Orada delik yok",
    "Not possible on a breadboard": "Breadboard'da olmaz",
    "Pin on the wrong rail": "Pin yanlış rayda",
    "Pads may lift": "Pedler kalkabilir",
    "Pin connected to nothing": "Hiçbir yere bağlı olmayan pin",
    "Solder trace skips a hole": "Lehim yolu bir deliği atlıyor",
    "Solder next to another net": "Başka bir netin yanında lehim",
    "Solder trace too long": "Lehim yolu fazla uzun",
    "Screw terminal's wire entry blocked": "Klemensin kablo girişi kapalı",
    "Screw terminal faces inward": "Klemens kartın içine bakıyor",
    "Part under a module": "Modülün altında parça",
    "Older package": "Eski kılıf",
    "Measure between bodies": "Gövdeler arasını ölç",
    "Body clearance": "Gövde aralığı",
    "Off, parts are kept apart by their courtyards (a half-pitch margin round each). On, by "
    "their real bodies plus this clearance — tighter, for a board where every hole counts.": (
        "Kapalıyken parçalar çevrelerindeki yarım adımlık güvenlik paylarıyla ayrı tutulur. "
        "Açıkken gerçek gövdeleri ve bu aralıkla ölçülür — her deliğin önemli olduğu bir kart "
        "için daha sıkı."
    ),
    "How far apart two parts' bodies must stand. A pin under another part's body is still in "
    "its way.": (
        "İki parçanın gövdeleri arasında kalması gereken mesafe. Başka bir parçanın gövdesinin "
        "altında kalan bir bacak yine engel sayılır."
    ),
    "Unknown package": "Bilinmeyen kılıf",
    "Bare wire on a joint": "Lehim noktası üzerinde çıplak tel",
    "Wire too thick for the hole": "Tel delik için fazla kalın",
    "Power pin not connected": "Besleme pini bağlı değil",
    "Power pin on the wrong net": "Besleme pini yanlış nette",
    "Part drawn backwards": "Parça ters çizilmiş",
    "Net names a missing pin": "Net olmayan bir pini anıyor",
    "One power pin left open": "Bir besleme pini boşta",
    "Nothing brings power in": "Karta güç getiren bir şey yok",
    "“No connect” pin wired": "“Bağlanmaz” (NC) pini bağlanmış",
    "Net with only one pin": "Tek pinli net",
    "Part connected to nothing": "Parça hiçbir yere bağlı değil",
    "Net names a part that isn't there": "Net, olmayan bir parçayı anıyor",
    # The three groups of the Problems panel: what each check is, its acronym after it.
    "Circuit check (ERC)": "Devre denetimi (ERC)",
    "Board check (DRC)": "Kart denetimi (DRC)",
    "Matches circuit (LVS)": "Devreyle uyum (LVS)",
    "Whether the circuit itself is right, before any board is asked about.": (
        "Devrenin kendisinin doğru olup olmadığı — daha hiçbir karta bakılmadan."
    ),
    "Broken: a net in pieces": "Kopuk: net parçalı",
    "Short circuit: two nets touch": "Kısa devre: iki net birbirine değiyor",
    "Copper joined to no pin": "Hiçbir pine bağlı olmayan bakır",
    "Part not on the board": "Parça kartta değil",
    "Net not wired yet": "Net henüz bağlanmadı",
    "Pin not wired yet": "Pin henüz bağlanmadı",
    "error": "hata",
    "warning": "uyarı",
    "Export 1:1 PDF": "1:1 PDF Dışa Aktar",
    "Export 1:1 PDF — the solder side is written beside it": (
        "1:1 PDF Dışa Aktar — lehim yüzü yanına yazılır"
    ),
    "PDF (*.pdf)": "PDF belgesi (*.pdf)",
    "Export 3D Snapshot": "3D Görüntüyü Dışa Aktar",
    "PNG image (*.png)": "PNG görüntüsü (*.png)",
    "Export 3D Model (STEP)": "3D Modeli Dışa Aktar (STEP)",
    "STEP model (*.step *.stp)": "STEP modeli (*.step *.stp)",
    "Export Build Guide — the cut list, parts list and JSON go beside it": (
        "Montaj Rehberini Dışa Aktar — kesim listesi, parça listesi ve JSON yanına yazılır"
    ),
    "HTML page (*.html)": "HTML sayfası (*.html)",
    "Export Schematic — the SVG and PNG are written beside it": (
        "Şemayı Dışa Aktar — SVG ve PNG yanına yazılır"
    ),
    "Open E&xample": "Örn&ek Aç",
    "Opens as a new, untitled board: Save asks where your copy goes.": (
        "Yeni, adsız bir kart olarak açılır: Kaydet, kopyanın nereye gideceğini sorar."
    ),
    "Opened the example {name}. Save keeps a copy of your own.": (
        "{name} örneği açıldı. Kaydet, kendi kopyanızı saklar."
    ),
    "Drawing step {done} of {total}…": "{total} adımın {done}. adımı çiziliyor…",
    "Skip the Pictures": "Görselleri Atla",
    "without its pictures": "görselleri olmadan",
    "Cancel": "İptal",
    "Delete parts": "Parçaları sil",
    "Delete conductors": "İletkenleri sil",
    "Apply this placement?": "Bu yerleşim uygulansın mı?",
    "Redo the wiring?": "Kablolama yeniden yapılsın mı?",
    "Redo Wiring": "Kablolamayı Yeniden Yap",
    "Conductors to remove: {removed}; to plan in their place: {planned}. Copper with no net "
    "assigned is left alone.": (
        "Kaldırılacak iletken: {removed}; yerlerine planlanacak: {planned}. Neti atanmamış "
        "bakıra dokunulmaz."
    ),
    "One Ctrl+Z puts it all back.": "Tek bir Ctrl+Z hepsini geri getirir.",
    "Placement refused": "Yerleşim reddedildi",
    "Wiring refused": "Kablolama reddedildi",
    "Redoing the wiring was refused": "Kablolamayı yeniden yapma reddedildi",
    "The guide has gaps": "Rehberde eksikler var",
    "About Perfboard Studio": "Perfboard Studio Hakkında",
    # -- status bar ----------------------------------------------------------
    "hole": "delik",
    "parts side": "parça yüzü",
    "solder side": "lehim yüzü",
    "mirrored": "aynalanmış",
    # -- a part's own properties ----------------------------------------------
    "Proper&ties…": "Ö&zellikler…",
    "Note": "Not",
    "Why this part is here, for whoever builds or mends it later": (
        "Bu parça neden burada: sonra onu kuracak ya da onaracak kişi için"
    ),
    "Saved with the board, shown when the pointer rests on the part, and printed at its "
    "step in the build guide.": (
        "Kartla birlikte kaydedilir; imleç parçanın üzerinde durunca görünür ve montaj "
        "rehberinde o parçanın adımına yazılır."
    ),
    "Reference": "Referans",
    "Value": "Değer",
    "Position": "Konum",
    "State": "Durum",
    "Pin 1 at": "1. pin",
    "Change…": "Değiştir…",
    "Rotation": "Dönüş",
    "Mirrored": "Aynalanmış",
    "Face": "Yüz",
    "Step {n} of {total}": "Adım {n} / {total}",
    "◀  Back": "◀  Geri",
    "Done, next  ▶": "Yapıldı, sıradaki  ▶",
    "Done  ✓": "Yapıldı  ✓",
    "1 step is not ticked yet": "1 adım henüz işaretlenmedi",
    "{n} steps are not ticked yet": "{n} adım henüz işaretlenmedi",
    "Go to Step {n}": "{n}. Adıma Git",
    "Every check is ticked too.": "Bütün ölçümler de işaretlendi.",
    "Checks not ticked yet. Measure each with the board in front of you, and tick it when it reads what it should.": (
        "Henüz işaretlenmemiş ölçümler. Her birini kart önünüzdeyken ölçün ve beklenen değeri "
        "okuyunca işaretleyin."
    ),
    "Save": "Kaydet",
    "Checks for this phase": "Bu aşamanın ölçümleri",
    "Cut list": "Kesim listesi",
    "Track cuts": "Şerit kesimleri",
    "Overview": "Genel bakış",
    "Polarity": "Yön",
    "Wire to cut": "Kesilecek tel",
    "◀  Step by step": "◀  Adım adım",
    "Cut": "Kes",
    "Colour": "Renk",
    "Strip": "Şerit",
    "A new design. Draw the circuit; the board it goes on is the next step, tried with the circuit on it.": (
        "Yeni bir tasarım. Devreyi çizin; gideceği kart bir sonraki adımda, devre üzerindeyken denenir."
    ),
    "{removed} conductor(s) on them go and are planned again; copper with no net assigned is left alone. One Ctrl+Z puts it all back.": (
        "Üzerlerindeki {removed} iletken kaldırılıp yeniden planlanır; neti olmayan bakıra dokunulmaz. Tek Ctrl+Z hepsini geri alır."
    ),
    "Locked": "Kilitli",
    "Kind": "Tür",
    "Type what the part is; Enter puts it on the sheet.": (
        "Parçanın ne olduğunu yazın; Enter onu şemaya koyar."
    ),
    "Holes": "Delikler",
    "Bent lead": "Bükülmüş bacak",
    "Copper strip": "Bakır şerit",
    "{start} → {end}, {count} holes": "{start} → {end}, {count} delik",
    "Mixed": "Karışık",
    "Typed once, given to every part selected, as one step to undo.": (
        "Bir kez yazılır, seçili her parçaya verilir; tek adımda geri alınır."
    ),
    "{hole} is not a hole on this board.": "{hole} bu kartta bir delik değil.",
    "The hole pin 1 is in. Type another to move the part there.": (
        "1. pinin girdiği delik. Parçayı oraya taşımak için başka bir delik yazın."
    ),
    "Height": "Yükseklik",
    "locked — Rearrange leaves it where it is": (
        "kilitli — Yeniden Diz onu yerinde bırakır"
    ),
    "Every part is identified by its reference, so it cannot be blank.": (
        "Her parça referansıyla tanınır, dolayısıyla boş bırakılamaz."
    ),
    # -- changing a placed part's package ---------------------------------------------
    "C&hange Part…": "&Farklı Parça Seç…",
    "Another package or another part from the library, on the same holes and the same "
    "nets.": "Kütüphaneden başka bir gövde ya da parça; aynı deliklerde, aynı netlerde.",
    "Another package or another part from the library on the same holes: a 3 mm LED for "
    "a 5 mm one, a resistor on a wider span. Its nets stay.": (
        "Aynı deliklere kütüphaneden başka bir gövde ya da parça: 5 mm LED yerine 3 mm, "
        "daha geniş açıklıklı bir direnç. Netleri kalır."
    ),
    "Locked: a new package would move its pins. Unlock it first.": (
        "Kilitli: yeni bir gövde pinlerini kaydırır. Önce kilidini açın."
    ),
    "{ref} is locked, and a new package would move its pins. Unlock it first (Toggle "
    "Lock).": (
        "{ref} kilitli ve yeni bir gövde pinlerini kaydırır. Önce kilidini açın (Kilidi "
        "Aç/Kapat)."
    ),
    "Pin 1 stays in {hole}, and every net it is on stays.": (
        "1. pin {hole} deliğinde kalır; bağlı olduğu bütün netler de kalır."
    ),
    "Pin {pin} lands in {hole}.": "{pin} pini {hole} deliğine gelir.",
    "Pin {pin} would land off the board.": "{pin} pini kartın dışına düşer.",
    "The wiring is checked again after the change.": (
        "Değişiklikten sonra bağlantılar yeniden denetlenir."
    ),
    "Its {count} lead bend(s) were bent to this package's pins and go with it.": (
        "{count} bacak bükümü bu gövdenin pinlerine göre bükülmüştü; onunla birlikte kalkar."
    ),
    "{ref} is a {part} now.": "{ref} artık bir {part}.",
    "Properties edits one part at a time — select a single part.": (
        "Özellikler tek seferde tek parçayı düzenler — tek bir parça seçin."
    ),
    "The part's reference and value. The value is what the build guide's bill "
    "of materials groups on, and nothing else in the window can set it.": (
        "Parçanın referansı ve değeri. Montaj rehberinin malzeme listesi değere göre "
        "gruplanır ve bu değeri pencerede başka hiçbir şey belirleyemez."
    ),
    "The designator the schematic uses. Every net this part is wired into "
    "follows the new name, so a rename is safe at any point.": (
        "Şemanın kullandığı tanımlayıcı. Parçanın bağlı olduğu her net yeni adı takip "
        "eder, bu yüzden yeniden adlandırmak her an güvenlidir."
    ),
    "What the part actually is. This is the column the build guide's bill of "
    "materials groups on, so a blank one becomes a line you cannot order.": (
        "Parçanın gerçekte ne olduğu. Montaj rehberinin malzeme listesi bu sütuna göre "
        "gruplanır; boş bırakılırsa sipariş edilemeyecek bir satır olur."
    ),
    "Given to each part as it is placed. Leave it blank and the part is placed "
    "without one; F2 sets it afterwards either way.": (
        "Yerleştirilen her parçaya verilir. Boş bırakılırsa parça değersiz yerleştirilir; "
        "her hâlükârda F2 ile sonradan da girilebilir."
    ),
    "Click a hole to place": "Yerleştirmek için bir deliğe tıkla:",
    "Esc cancels.": "Esc iptal eder.",
    # -- panel headings --------------------------------------------------------
    "Part": "Parça",
    "Pins": "Pin",
    "Problem": "Sorun",
    "Details": "Ayrıntı",
    "Filter problems…  (error, short, C7)": "Sorunları süz…  (hata, kısa devre, C7)",
    "pads": "ped",
    "a pin has no pad there — see Problems": "orada bir pinin pedi yok — Sorunlar'a bakın",
    "it overlaps an existing pin — see Problems": "mevcut bir pinle çakışıyor — Sorunlar'a bakın",
    # "To route", not "Left": the board edge in Board Features is already called Left,
    # and one English key cannot carry two meanings in a catalogue whose keys ARE the
    # English strings. Saying what the number counts is better English anyway.
    "To wire": "Kalan",
    # -- the schematic, in the window ------------------------------------------
    "Schematic": "Şema",
    "Show &Schematic": "&Şemayı Göster",
    "The circuit (Ctrl+2). Clicking a symbol selects that part on the board; "
    "clicking a wire highlights its net.": (
        "Devre (Ctrl+2). Bir sembole tıklamak o parçayı kart üzerinde seçer, bir hatta "
        "tıklamak ait olduğu neti vurgular."
    ),
    "Show &Board": "&Kartı Göster",
    "The board itself (Ctrl+1). A panel like every other one: drag it beside "
    "the schematic, or out of the window altogether.": (
        "Kartın kendisi (Ctrl+1). Diğer her panel gibi bir panel: şemayla yan yana "
        "sürükleyin ya da tamamen pencerenin dışına çıkarın."
    ),
    "&Reset the Panel Layout": "Panel Düzenini Sıfı&rla",
    "Panels": "Paneller",
    "Put every panel back where it opens on a new installation. A window "
    "rearranged into a corner has no other way back.": (
        "Her paneli yeni bir kurulumda açıldığı yere geri koyar. Bir köşeye sıkıştırılmış "
        "bir pencerenin başka dönüş yolu yoktur."
    ),
    "Panels put back where they started.": "Paneller başlangıç yerlerine kondu.",
    "Every view is closed. Ctrl+1 brings the board back and Ctrl+2 the "
    "schematic, and View \u25b8 Panels opens any of them.": (
        "Bütün görünümler kapalı. Ctrl+1 kartı, Ctrl+2 şemayı geri getirir; "
        "Görünüm \u25b8 Paneller hepsini açar."
    ),
    # The strip the update check puts across the top. Its title is never drawn -- the panel
    # has no title bar -- but it is what Qt calls the dock, so it is named like one.
    "Update": "Güncelleme",
    "Put a part in the design without deciding where it goes on the board yet.": (
        "Kart üzerinde nereye geleceğine karar vermeden tasarıma bir parça ekler."
    ),
    "Click a pin, then the pin it joins — or a wire already drawn, and the pin "
    "branches off it in a T. Neither on a net yet? One gets made. Exactly what the "
    "board's connect tool does, because it is the same code.": (
        "Bir pine tıklayın, sonra birleşeceği pine — ya da çizilmiş bir tele; pin o telden "
        "T ile dallanır. İkisi de bir nette değilse yeni bir net oluşur. Kartın bağlama "
        "aracıyla birebir aynı davranış — çünkü aynı kod."
    ),
    "Take the selected part out of the design, along with its connections. A "
    "part that is on the board comes off it and stays in the design instead.": (
        "Seçili parçayı bağlantılarıyla birlikte tasarımdan çıkarır. Kart üzerindeki bir "
        "parça ise karttan alınır ve tasarımda kalır."
    ),
    "Place on the Board": "Karta Yerleştir",
    "Put the whole design on the board, arranged: connectors on the edge, the "
    "rest lined up by what they connect to. Suggests a stock board size first, "
    "while the board is still empty. One undo step for the lot.": (
        "Tasarımın tamamını yerleşimi yapılmış hâlde kart üzerine koyar: konnektörler "
        "kenara, geri kalanı bağlantılarına göre hizalı. Kart boşken önce hazır satılan "
        "bir kart boyutu önerir. Tamamı tek geri alma adımı."
    ),
    # -- the sheet's own tools -------------------------------------------------
    # "Perfboard Studio" is the product's name and stays out of the catalogue, as the
    # welcome dialog's own note says. "Net" is the Nets panel's column heading and reads
    # the same in Turkish.
    "Select": "Seç",
    "Pick symbols up, move them, rubber-band several at once. Delete takes "
    "the selection out of the design.": (
        "Sembolleri tutar, taşır, kementle birden çoğunu seçer. Delete seçili olanı "
        "tasarımdan çıkarır."
    ),
    "Label": "Etiket",
    "Join a pin to a net by NAME instead of drawing a line to it. Two pins "
    "carrying one name are one net — which here is simply true, because "
    "the name is printed from the net.": (
        "Bir pini çizgi çekmek yerine ADINA göre bir nete bağlar. Aynı adı taşıyan iki pin "
        "tek nettir — burada bu zaten doğrudur, çünkü ad net'in kendisinden basılır."
    ),
    "Text": "Metin",
    "Write on the drawing. Nothing derives anything from it.": (
        "Çizimin üzerine yazı yazar. Hiçbir şey bundan bir şey türetmez."
    ),
    "Box": "Kutu",
    "Draw a box round a block of the circuit. Drag for a line or a circle.": (
        "Devrenin bir bölümünün etrafına kutu çizer. Çizgi ya da daire için sürükleyin."
    ),
    "Line": "Çizgi",
    "Circle": "Daire",
    "Rotate the selected symbols a quarter turn clockwise. R does the same.": (
        "Seçili sembolleri saat yönünde çeyrek tur döndürür. R tuşu da aynısını yapar."
    ),
    "Flip the selected symbols about their own centre, so their pins swap sides.": (
        "Seçili sembolleri kendi merkezlerine göre aynalar; pinleri taraf değiştirir."
    ),
    "Select a symbol on the sheet first.": "Önce sayfada bir sembol seçin.",
    "Click a pin and name the net it belongs to. Two pins with one name are "
    "one net. Esc cancels.": (
        "Bir pine tıklayın ve ait olduğu netin adını yazın. Aynı ada sahip iki pin tek "
        "nettir. Esc iptal eder."
    ),
    "Click where the text goes. Esc cancels.": (
        "Metnin geleceği yere tıklayın. Esc iptal eder."
    ),
    "Drag out the shape. Esc cancels.": "Şekli sürükleyerek çizin. Esc iptal eder.",
    "Connect by Name": "Ada Göre Bağla",
    "Net for {pin}:": "{pin} için net:",
    "No package called {id}.": "{id} adında bir kılıf yok.",
    "Keep the symbols where they are": "Sembolleri yerlerinde tut",
    "Double-click a part, or press Enter, to put it on the sheet. On the board: pick one, "
    "then click a hole. Esc cancels.": (
        "Şemaya koymak için parçaya çift tıklayın ya da Enter'a basın. Kartta ise birini "
        "seçin, sonra bir deliğe tıklayın. Esc iptal eder."
    ),
    # -- the welcome dialog, and autosave that writes the file itself ----------
    # "Perfboard Studio" is deliberately absent: it is the product's name, and a name is
    # the one string that must read the same in every language.
    "Autosave to the &File": "&Dosyaya Otomatik Kaydet",
    "Write the board to its own file every half minute, keeping the last save "
    "you made yourself as a .bak beside it. Off, autosave still writes a "
    "crash-recovery copy elsewhere, and nothing reaches your file until Ctrl+S.": (
        "Kartı yarım dakikada bir kendi dosyasına yazar; kendi elinizle yaptığınız son "
        "kaydı yanında .bak olarak saklar. Kapalıyken otomatik kaydetme yalnızca başka "
        "bir yere çökme kurtarma kopyası yazar ve Ctrl+S'e basana dek dosyanıza hiçbir "
        "şey yazılmaz."
    ),
    "Autosave writes the file itself every half minute; the previous save is kept as .bak.": (
        "Otomatik kaydetme yarım dakikada bir dosyanın kendisine yazıyor; önceki kayıt "
        ".bak olarak saklanıyor."
    ),
    "Autosave now only writes a crash-recovery copy; Ctrl+S saves the file.": (
        "Otomatik kaydetme artık yalnızca çökme kurtarma kopyası yazıyor; dosyayı Ctrl+S "
        "kaydeder."
    ),
    # -- the schematic as a view of its own, not a panel down the side ---------
    # "Board" is already in this catalogue, as the Board Setup dialog's own label.
    "Hand the whole sheet back to the layout: every symbol you moved and every "
    "wire you drew. What is connected is not touched — only how it was drawn.": (
        "Sayfanın tamamını düzene geri verir: taşıdığınız her sembol ve çizdiğiniz her tel. "
        "Neyin bağlı olduğuna dokunulmaz — yalnızca nasıl çizildiğine."
    ),
    "Hand the whole sheet back to the layout: every symbol you moved and every "
    "wire you drew. What is connected is not touched.": (
        "Sayfanın tamamını düzene geri verir: taşıdığınız her sembol ve çizdiğiniz her tel. "
        "Neyin bağlı olduğuna dokunulmaz."
    ),
    "Nothing on this sheet has been moved by hand.": (
        "Bu sayfada elle taşınmış bir şey yok."
    ),
    "Put the sheet in a window of its own, so it and the board can sit side by "
    "side. Dragging its title bar does the same, and so does dropping it back.": (
        "Sayfayı kendi penceresine alır, böylece kartla yan yana durabilirler. Başlık "
        "çubuğundan sürüklemek de aynı işi yapar, geri bırakmak da."
    ),
    # -- editing the circuit from the sheet, by right-clicking the thing that is wrong -
    # Three menus, chosen by what the pointer is over. The accelerators are checked as
    # three groups in tests/test_i18n.py, since the pin entry shares the symbol's menu.
    "&Properties…": "Ö&zellikler…",
    "What this part is, what it is called and what it is worth — including swapping its "
    "package for a different one.": (
        "Bu parçanın ne olduğu, adı ve değeri — kılıfını bir başkasıyla değiştirmek de "
        "dahil."
    ),
    "Re&name…": "Yeniden Adlandı&r…",
    "A new designator. Every net it is wired into comes with it.": (
        "Yeni bir etiket. Bağlı olduğu her net onunla birlikte gelir."
    ),
    "D&uplicate": "&Çoğalt",
    "Another part of the same kind and value, with the next free designator "
    "and no connections of its own.": (
        "Aynı türden ve aynı değerde bir parça daha; sıradaki boş etiketleyin ve kendine "
        "ait hiçbir bağlantı olmadan."
    ),
    "&Arrange This Symbol": "Bu Sembolü &Düzenle",
    "Give this one symbol back to the layout, leaving the rest where you put them.": (
        "Yalnızca bu sembolü yerleşime geri verir, diğerlerini koyduğunuz yerde bırakır."
    ),
    "Take &off the Board": "Karttan &Al",
    "Back into the design, with its wiring intact.": (
        "Bağlantıları bozulmadan tasarıma geri döner."
    ),
    "&Remove from the Design": "Tasarımdan Çı&kar",
    "Remo&ve from the Design": "Tasarımdan Çı&kar",
    "Out of the design, along with its connections.": (
        "Bağlantılarıyla birlikte tasarımın dışına."
    ),
    "&Disconnect {pin} from {net}": "{pin} pinini {net} netinden A&yır",
    "&Rub Out This Wire": "Bu Teli &Sil",
    "Take the line off the sheet. The pins stay connected — the net says so by "
    "name instead.": (
        "Çizgiyi sayfadan kaldırır. Pinler bağlı kalır — net bunu artık adıyla söyler."
    ),
    "Re&name Net…": "Neti Yeniden Adlandı&r…",
    "A new name. The pins on it, and any copper laid for it, stay.": (
        "Yeni bir ad. Üzerindeki pinler ve onun için döşenmiş bakır yerinde kalır."
    ),
    "Net &Class": "Net &Sınıfı",
    "&Signal": "&Sinyal",
    "&Ground": "&Toprak",
    "&Power": "&Güç",
    "The name, the class, and what it carries — which is the only way to state a current.": (
        "Adı, sınıfı ve ne taşıdığı — bir akım belirtmenin tek yolu burası."
    ),
    "{ref} is named by a net and is not in the design.": (
        "{ref} bir netin adıyla anılıyor ama tasarımda değil."
    ),
    "&Add Part…": "Parça &Ekle…",
    "Add Pa&rt…": "Parça &Ekle…",
    "Arran&ge the Sheet": "Say&fayı Düzenle",
    "Arrange": "Düzenle",
    "Arrange redraws this sheet tidily, with power and ground as rail symbols. Symbols move; every connection stays. One undo step.": (
        "Düzenle, bu sayfayı derli toplu yeniden çizer; güç ve toprak ray simgesi olur. Semboller yer değiştirir, her bağlantı yerinde kalır. Tek adımda geri alınır."
    ),
    "Fit the S&heet": "Sayfayı &Sığdır",
    # -- projects: the folder a board and everything made from it live in ------
    "New &Project…": "Yeni &Proje…",
    "Name the board and start in the schematic; which board it goes on is the "
    "next step. Makes a folder to keep the board and everything generated from "
    "it.": (
        "Karta bir ad verin ve şemadan başlayın; hangi karta gideceği sonraki adımdır. "
        "Kartı ve ondan üretilen her şeyi bir arada tutacak bir klasör oluşturur."
    ),
    "A blank board with no home on disk yet.": "Diskte henüz bir yeri olmayan boş kart.",
    "Open P&roject…": "P&roje Aç…",
    "Open the board inside a project folder. A folder with two boards in it is not one.": (
        "Bir proje klasöründeki kartı açar. İçinde iki kart olan klasör proje değildir."
    ),
    "Save Pro&ject": "Pro&jeyi Kaydet",
    "Save the board and rewrite everything generated from it — the 1:1 sheets, "
    "the schematic, the build guide, the bill of materials — into outputs/ "
    "beside it.": (
        "Kartı kaydeder ve ondan üretilen her şeyi — 1:1 baskıları, şemayı, montaj "
        "rehberini, malzeme listesini — yanındaki outputs/ klasörüne yeniden yazar."
    ),
    "New Project": "Yeni Proje",
    "What is this board called?": "Bu kartın adı ne?",
    "My Board": "Kartım",
    "Where should the project go?": "Proje nereye kurulsun?",
    "That folder is not empty": "O klasör boş değil",
    "{path} already has something in it. Pick another place, or another name.": (
        "{path} içinde zaten bir şeyler var. Başka bir yer ya da başka bir ad seçin."
    ),
    "Could not make the folder": "Klasör oluşturulamadı",
    "New project in {path}. Draw the circuit; the board it goes on is the next "
    "step, tried with the circuit on it.": (
        "{path} içinde yeni proje. Devreyi çizin; gideceği kart sonraki adımdır ve devre "
        "üzerine yerleştirilerek denenir."
    ),
    "Other Board…": "Başka Kart…",
    "Stopping…": "Durduruluyor…",
    "A breadboard, a stripboard, or a board of any size: Design the Board.": (
        "Breadboard, şeritli kart ya da istenen boyutta bir kart: Kartı Tasarla."
    ),
    "Open a project": "Bir proje aç",
    "Could not open the project": "Proje açılamadı",
    "Not a project": "Proje değil",
    "A project is a folder built around exactly one board. {path} has {count} of them.": (
        "Proje, tam olarak bir kartın etrafında kurulmuş bir klasördür. {path} içinde "
        "{count} tane var."
    ),
    "Could not save the project": "Proje kaydedilemedi",
    "The board itself: {err}": "Kartın kendisi: {err}",
    "{count} not written": "{count} tanesi yazılmadı",
    "Project saved to {path}: the board and {count} generated file(s){note}": (
        "Proje {path} konumuna kaydedildi: kart ve {count} üretilmiş dosya{note}"
    ),
    "Some files were not written": "Bazı dosyalar yazılmadı",
    "no board view to print from": "basılacak bir kart görünümü yok",
    "the design has no parts to draw yet": "tasarımda henüz çizilecek parça yok",
    "Could not write the download: {error}": "İndirilen dosya yazılamadı: {error}",
    "50 mm — measure this with a ruler to confirm 1:1": "50 mm — 1:1 olduğunu cetvelle ölçerek "
                                                        "doğrulayın",
    "SOLDER SIDE (mirrored)": "LEHİM YÜZÜ (aynalı)",
    "COMPONENT SIDE": "PARÇA YÜZÜ",
    "printed 1:1": "1:1 basıldı",
    "Everything else is saved. These had nothing to write:\n\n{lines}": (
        "Diğer her şey kaydedildi. Bunların yazacak bir şeyi yoktu:\n\n{lines}"
    ),
    # -- choosing the board the circuit goes on --------------------------------
    "Which board is this going on?": "Bu devre hangi karta girecek?",
    "Your circuit was placed, wired and checked on the roomy board and on the "
    "sizes below it. The suggested one is the smallest that builds as well: every "
    "part placed, every connection made, no warning the roomy board does not have, "
    "and at most {percent}% dearer to wire.": (
        "Devreniz geniş kartta ve ondan küçük boylarda yerleştirildi, kablolandı ve "
        "denetlendi. Önerilen, aynı iyilikte kurulan en küçük boy: her parça yerinde, "
        "her bağlantı yapılmış, geniş kartta olmayan hiçbir uyarı yok, ve kablolaması en "
        "fazla %{percent} daha pahalı."
    ),
    "Stopped before every board was tried; the suggestion is the smallest tried.": (
        "Her kart denenmeden durduruldu; öneri, denenenler arasındaki en küçük kart."
    ),
    "Trying your circuit on smaller boards…": "Devreniz daha küçük kartlarda deneniyor…",
    "Trying your circuit on a {board} board…": "Devreniz {board} kartta deneniyor…",
    "the roomy board the smaller ones are measured against": (
        "küçük kartların kıyaslandığı geniş kart"
    ),
    "builds as well, wiring at {percent}% of the roomy board's cost": (
        "aynı iyilikte kuruluyor, kablolaması geniş karta göre %{percent}"
    ),
    "wires dearer: {percent}% of the roomy board's cost": (
        "kablolaması pahalı: geniş karta göre %{percent}"
    ),
    "warns: {rules}": "uyarı veriyor: {rules}",
    "{count} connection would not wire": "{count} bağlantı kablolanamıyor",
    "{count} connections would not wire": "{count} bağlantı kablolanamıyor",
    "{count} board-check error once wired": "kablolanınca {count} kart denetimi hatası",
    "{count} board-check errors once wired": "kablolanınca {count} kart denetimi hatası",
    "not tried · a quick layout had no room for {count} part": (
        "denenmedi · hızlı yerleşimde {count} parçaya yer çıkmadı"
    ),
    "not tried · a quick layout had no room for {count} parts": (
        "denenmedi · hızlı yerleşimde {count} parçaya yer çıkmadı"
    ),
    "Keep the board I have  ·  {cols} × {rows}": "Mevcut kartım kalsın  ·  {cols} × {rows}",
    "fits, {percent}% full": "sığıyor, %{percent} dolu",
    "too small — {count} part will not fit": "çok küçük — {count} parça sığmıyor",
    "too small — {count} parts will not fit": "çok küçük — {count} parça sığmıyor",
    "Suggested:  ": "Önerilen:  ",
    "Arranging the circuit on the board…": "Devre kart üzerine yerleştiriliyor…",
    "Board refused": "Kart reddedildi",
    "Every part in the design is already on the board.": (
        "Tasarımdaki her parça zaten kart üzerinde."
    ),
    "No room on this board for the parts in the design. Make it bigger, or "
    "place them one at a time.": (
        "Bu kartta tasarımdaki parçalar için yer yok. Kartı büyütün ya da parçaları "
        "teker teker yerleştirin."
    ),
    "From {pin} — click the pin or the wire it joins.": (
        "{pin} pininden — birleşeceği pine ya da tele tıklayın."
    ),
    "On the wire {wire} — click the pin that branches off it.": (
        "{wire} teli üzerinde — ondan dallanacak pine tıklayın."
    ),
    "Cancelled.": "İptal edildi.",
    "Filter parts…  (555, BC547, resistor, dip-8)": "Parçaları süz…  (555, BC547, direnç, dip-8)",
    "Put the whole schematic back in the view. The sheet is not re-fitted "
    "when the board changes, so an edit cannot move what you were looking at.": (
        "Şemanın tamamını panele geri sığdırır. Kart değiştiğinde sayfa yeniden "
        "sığdırılmaz; böylece bir düzenleme baktığınız yeri kaydıramaz."
    ),
    # -- the build guide, in the window ----------------------------------------
    "Build Guide": "Montaj Rehberi",
    # M&ontaj, not &Montaj: "&Mesafe Ölç" is in the same menu.
    "Show B&uild Guide": "M&ontaj Rehberini Göster",
    "The soldering order, in the window: shortest part first, jumpers before "
    "whatever stands on them, ICs last. Picking a step shows it on the board.": (
        "Lehimleme sırası, pencerenin içinde: önce en alçak parça, üzerinde bir şey duran "
        "jumperlar ondan önce, entegreler en sonda. Bir adımı seçmek onu kart üzerinde gösterir."
    ),
    "Export the Guide…": "Rehberi Dışa Aktar…",
    "Next Step to Do": "Sıradaki Adım",
    "The first step not ticked off yet, shown on the board and in 3D.": (
        "Henüz işaretlenmemiş ilk adım; kartta ve 3D'de gösterilir."
    ),
    "Clear Progress": "İlerlemeyi Temizle",
    " (hold for more)": " (diğerleri için basılı tutun)",
    "Clear": "Temizle",
    "Untick every step of this board.": "Bu kartın bütün adımlarının işaretini kaldırır.",
    "{done} of {total} steps done": "{total} adımın {done} tanesi yapıldı",
    "Every step is done.": "Bütün adımlar yapıldı.",
    "Untick all {count} steps done on this board?": (
        "Bu kartta yapılmış {count} adımın işareti kaldırılsın mı?"
    ),
    "Build guide written": "Montaj rehberi yazıldı",
    "Written to {folder}, with one other file.": (
        "Bir başka dosyayla birlikte {folder} klasörüne yazıldı."
    ),
    "Written to {folder}, with {count} other files.": (
        "{count} başka dosyayla birlikte {folder} klasörüne yazıldı."
    ),
    "Open the Guide": "Rehberi Aç",
    "Schematic written": "Şema yazıldı",
    "Open the Sheet": "Sayfayı Aç",
    "Nothing to export": "Dışa aktarılacak bir şey yok",
    "This document has no parts to draw yet.": "Bu belgede henüz çizilecek parça yok.",
    "Show the Folder": "Klasörü Göster",
    "Close": "Kapat",
    # -- right-click -----------------------------------------------------------
    "&Copy This Problem": "Bu Sorunu &Kopyala",
    "Copy &All Problems": "&Tüm Sorunları Kopyala",
    "problems copied to the clipboard": "sorun panoya kopyalandı",
    # -- crash recovery ---------------------------------------------------------
    "Unsaved work was found": "Kaydedilmemiş çalışma bulundu",
    "Perfboard Studio stopped without saving this board. A copy from {when} is "
    "still here. Opening it does not touch the file on disk — you decide "
    "whether to save over it.": (
        "Perfboard Studio bu kartı kaydetmeden durdu. {when} tarihli bir kopyası hâlâ burada. "
        "Onu açmak diskteki dosyaya dokunmaz — üzerine yazıp yazmayacağınıza siz "
        "karar verirsiniz."
    ),
    "Open the Recovered Board": "Kurtarılan Kartı Aç",
    "Discard It": "Kopyayı At",
    "Decide Later": "Sonra Karar Ver",
    "Recovered {name}. It has not been saved yet.": (
        "{name} kurtarıldı. Henüz kaydedilmedi."
    ),
    "Could not write the recovery file — save your work yourself.": (
        "Kurtarma dosyası yazılamadı — çalışmanızı kendiniz kaydedin."
    ),
    # -- a part the library does not have --------------------------------------
    #
    # The families and their measurements. Not identifiers: the IDENTIFIER a custom part
    # gets (`box-4x2-p1-r3-15x10x8`) is engine text and stays untranslated, like a hole
    # address or a DRC rule name, because it is what goes into the file.
    "Custom Part": "Özel Parça",
    "No part matches “{query}”. Try a shorter word, or describe the part with Custom Part…": (
        "“{query}” ile eşleşen bir parça yok. Daha kısa bir kelime deneyin ya da parçayı Özel Parça… ile tanımlayın."
    ),
    # -- what moved in 0.23 (ui/whatsnew.py) -------------------------------------------
    "What moved in 0.23": "0.23'te yeri değişenler",
    "The window is new. Click a line to see where it went.": (
        "Pencere yenilendi. Bir satıra tıklayın; yeni yeri gösterilir."
    ),
    "Board Setup… → Board ▸ Design the Board…": "Kart Ayarları… → Kart ▸ Kartı Tasarla…",
    "Part Properties → Properties, always open on the right": (
        "Parça Özellikleri → Özellikler, sağda hep açık"
    ),
    "The toolbar → tools inside the Board panel": "Araç çubuğu → Kart panelinin içindeki araçlar",
    "Route ▸ Autoroute All Nets → Wiring ▸ Auto-wire Everything": (
        "Yönlendir ▸ Tüm Netleri Otomatik Yönlendir → Kablolama ▸ Hepsini Otomatik Kablola"
    ),
    "The menu bar → ☰ at the top left, or Alt": "Menü çubuğu → sol üstte ☰ ya da Alt",
    "A command you can't find → Ctrl+K, by its name": (
        "Bulamadığınız bir komut → Ctrl+K, adını yazarak"
    ),
    "Got It": "Tamam",
    "What &Moved in 0.23": "0.23'te Ye&ri Değişenler",
    "Where Board Setup, Part Properties, the toolbar and the menus went.": (
        "Kart Ayarları, Parça Özellikleri, araç çubuğu ve menülerin yeni yerleri."
    ),
    "Offered instead": "Bunun yerine önerilenler",
    "Custom Part…": "Özel Parça…",
    "Describe a part the library does not have. It is stored as an identifier "
    "that carries its own dimensions, so it travels with the board.": (
        "Kütüphanede olmayan bir parçayı tarif edin. Ölçülerini kendi taşıyan bir kimlik "
        "olarak saklanır, böylece kartla birlikte gider."
    ),
    "The identifier this part is stored under. It carries the dimensions, so "
    "the part travels with the board rather than living in a library the next "
    "person has to have.": (
        "Bu parçanın saklandığı kimlik. Ölçüleri kendisi taşıdığı için parça, bir sonraki "
        "kişinin kurması gereken bir kütüphanede değil, kartın kendisiyle birlikte gider."
    ),
    "Those measurements do not make a part.": "Bu ölçüler bir parça etmiyor.",
    "{name} — {pins} pin(s), {height} mm tall": (
        "{name} — {pins} pin, {height} mm yükseklik"
    ),
    "{count} pin(s)": "{count} pin",
    # -- the Parts panel's package families (main._archetype_headings) -------------------
    "Axial resistors and diodes": "Eksenel dirençler ve diyotlar",
    "Resistors and diodes stood on end": "Dik takılan dirençler ve diyotlar",
    "Ceramic disc capacitors": "Seramik disk kondansatörler",
    "Film capacitors": "Film kondansatörler",
    "Electrolytic capacitors": "Elektrolitik kondansatörler",
    "LEDs": "LED'ler",
    "LED packages": "LED kılıfları",
    "Packages: any part of this shape; you give it its value and pin names.": (
        "Kılıflar: bu biçimdeki herhangi bir parça; değerini ve pin adlarını siz verirsiniz."
    ),
    "Crystals": "Kristaller",
    "TO-92 packages": "TO-92 kılıfları",
    "TO-220 packages": "TO-220 kılıfları",
    "DIP packages": "DIP kılıfları",
    "Pin headers": "Pin başlıkları",
    "Wire-to-board connectors": "Kablo-kart konnektörleri",
    "IDC box headers": "IDC kutu başlıklar",
    "Screw terminals": "Vidalı klemensler",
    "Screw terminals, wires from above": "Dik klemensler, tel yukarıdan",
    "Potentiometers": "Potansiyometreler",
    "Tactile switches": "Tact butonlar",
    "Relays": "Röleler",
    "Relay packages": "Röle kılıfları",
    "Module packages": "Modül kılıfları",
    "SMD chips on DIP adapters": "DIP adaptöründe SMD çipler",
    "Boxes of any size": "Her boyutta kutular",
    "Any rectangular part": "Herhangi bir dikdörtgen parça",
    "DIP (dual in-line)": "DIP (çift sıra)",
    "Pin header": "Pin başlığı",
    "Screw terminal": "Vidalı klemens",
    "Axial part (resistor, diode, choke)": "Eksenel parça (direnç, diyot, bobin)",
    "Electrolytic capacitor": "Elektrolitik kondansatör",
    "Disc ceramic capacitor": "Disk seramik kondansatör",
    "Film capacitor": "Film kondansatör",
    "LED": "LED",
    "Pins across": "Yatay pin sayısı",
    "Rows of pins": "Pin sırası sayısı",
    "Holes between pins": "Pinler arası delik",
    "Holes between rows": "Sıralar arası delik",
    "Pins per row": "Sıra başına pin",
    "Ways": "Yol sayısı",
    "Wide body (0.6 in)": "Geniş gövde (0,6 inç)",
    "Polarised (banded end)": "Kutuplu (bantlı uç)",
    "Mounted": "Takılışı",
    "Lying flat": "Yatık",
    "Standing on pin 1": "1. pinin üstünde dik",
    "Standing on pin 2": "2. pinin üstünde dik",
    "Lead span (holes)": "Bacak açıklığı (delik)",
    "Lead pitch (holes)": "Bacak aralığı (delik)",
    "Body width (mm)": "Gövde genişliği (mm)",
    "Body depth (mm)": "Gövde derinliği (mm)",
    "Body height (mm)": "Gövde yüksekliği (mm)",
    "Body length (mm)": "Gövde uzunluğu (mm)",
    "Body diameter (mm)": "Gövde çapı (mm)",
    "Can diameter (mm)": "Kutu çapı (mm)",
    "Can height (mm)": "Kutu yüksekliği (mm)",
    "Disc diameter (mm)": "Disk çapı (mm)",
    "Disc thickness (mm)": "Disk kalınlığı (mm)",
    "LED diameter (mm)": "LED çapı (mm)",
    # -- the language of the interface itself ----------------------------------
    "Lan&guage": "&Dil",
    "Language changed": "Dil değişti",
    # -- the theme: dark or light, also from the next start ----------------------
    "&Theme": "&Tema",
    "&Dark": "&Koyu",
    "&Light": "&Açık",
    "Theme changed": "Tema değişti",
    "The window's colours are set as it opens, so the new theme appears the next time "
    "Perfboard Studio starts.": (
        "Pencerenin renkleri açılırken belirlenir; yeni tema Perfboard Studio'nun bir "
        "sonraki açılışında görünür."
    ),
    "The interface is built in one language when the window opens, so the new "
    "one appears the next time Perfboard Studio starts.": (
        "Arayüz, pencere açılırken tek bir dilde kurulur; yeni dil Perfboard Studio'nun "
        "bir sonraki açılışında görünür."
    ),
    # -- tooltips: what each command actually does -----------------------------
    # Every one of these was English in a Turkish interface, which is the half that
    # matters: a menu item names a command, and the tooltip is where it is explained.
    "Load the file again, discarding what is in this window. The board reloads "
    "itself automatically when it changes on disk and there is nothing unsaved.": (
        "Dosyayı yeniden yükler, bu penceredekini atar. Kaydedilmemiş bir şey yoksa kart, "
        "diskte değiştiğinde kendini zaten otomatik yeniler."
    ),
    "Grid size and substrate. The material is not cosmetic: it decides the iron "
    "temperature the build guide gives and whether the pad-lifting rule applies.": (
        "Izgara ölçüsü ve taban malzemesi. Malzeme süs değildir: montaj rehberindeki havya "
        "sıcaklığını ve ped kalkması kuralının geçerli olup olmadığını belirler."
    ),
    "Mounting holes and edge-connector fingers. A mounting bore takes the copper off the "
    "pads around it, so the board check (DRC) treats a pin left there as an error.": (
        "Montaj delikleri ve kenar konnektörü parmakları. Montaj deliği çevresindeki "
        "pedlerin bakırını alır; bu yüzden kart denetimi (DRC) orada kalan bir pini hata "
        "sayar."
    ),
    "Write the step-by-step soldering guide: one offline HTML file, the wire cut "
    "list and BOM as CSV, and the whole thing as JSON.": (
        "Adım adım lehimleme rehberini yazar: çevrimdışı tek bir HTML dosyası, tel "
        "kesim listesi ve malzeme listesi CSV olarak, tamamı da JSON olarak."
    ),
    "Put the selected parts and copper on the clipboard as text, so a block can "
    "be pasted into another board, another window, or a bug report.": (
        "Seçili parçaları ve bakırı metin olarak panoya koyar; böylece bir blok başka bir "
        "karta, başka bir pencereye ya da bir hata bildirimine yapıştırılabilir."
    ),
    "Place the clipboard's block under the pointer. New references, no net "
    "claim: a copy of R1 is not R1, and its copper is not on R1's net.": (
        "Panodaki bloğu imlecin altına yerleştirir. Yeni referanslar, net iddiası yok: "
        "R1'in kopyası R1 değildir ve bakırı da R1'in netinde değildir."
    ),
    "Copy and paste the selection in one step, beside itself and without "
    "touching the clipboard.": (
        "Seçimi tek adımda kopyalayıp yanına yapıştırır, panoya dokunmadan."
    ),
    "Break the strip at a hole. The cut is drilled through the pad, so that hole "
    "has nothing to solder to afterwards — click a cut again to take it back.": (
        "Şeridi bir delikte koparır. Kesik pedin içinden delinir, dolayısıyla o deliğin "
        "ardından lehimlenecek bir şeyi kalmaz — kesiği geri almak için tekrar tıklayın."
    ),
    "Leave any board mode: placing a part, drawing a conductor, connecting pins.": (
        "Hangi kart kipindeyseniz bırakır: parça yerleştirme, iletken çizme, pin bağlama."
    ),
    "Rearrange the unlocked parts to shorten the connections and make them "
    "solderable as traces rather than wires. Shows the result before applying it.": (
        "Kilitli olmayan parçaları, bağlantıları kısaltmak ve telle değil lehim yoluyla "
        "yapılabilir kılmak için yeniden düzenler. Sonucu uygulamadan önce gösterir."
    ),
    "Search again from a different seed. Annealing is a random walk, so this is "
    "a real second answer rather than the same one twice.": (
        "Farklı bir tohumdan yeniden arar. Tavlama rastgele bir yürüyüştür; bu yüzden bu, "
        "aynı cevabın tekrarı değil gerçek bir ikinci cevaptır."
    ),
    "Click one pin, then another. They end up on the same net: an existing one if "
    "either pin is already on it, or a new one named for you if neither is.": (
        "Bir pine, sonra bir başkasına tıklayın. İkisi aynı nete girer: pinlerden biri "
        "zaten bir netteyse o net, hiçbiri değilse sizin için adlandırılan yeni bir net."
    ),
    "Name a net, then click its pins on the board. Nothing here needs KiCad.": (
        "Bir nete ad verin, sonra pinlerine kart üzerinde tıklayın. Burada KiCad gerekmez."
    ),
    "Click each pin that belongs to the selected net. Right-click or Enter "
    "finishes, and the whole session goes on the history as one step.": (
        "Seçili nete ait her pine tıklayın. Sağ tık veya Enter bitirir ve oturumun tamamı "
        "geçmişe tek adım olarak geçer."
    ),
    "Name, class, and the current and voltage it carries — which nothing else in "
    "the application can set, and which DRC's capacity and creepage rules need.": (
        "Ad, sınıf ve taşıdığı akım ile gerilim — bunları uygulamada başka hiçbir şey "
        "belirleyemez ve DRC'nin kapasite ile yüzeysel kaçak kuralları bunlara ihtiyaç duyar."
    ),
    "Take the pins selected in the Nets panel off their net. Expand a net to "
    "see them.": (
        "Netler panelinde seçili pinleri netlerinden çıkarır. Görmek için neti genişletin."
    ),
    "Forget what the net was for. Copper already laid for it stays on the board, and Redo "
    "Wiring and Remove Out-of-Date Wiring leave it alone from then on.": (
        "Netin ne için olduğunu unutur. Onun için döşenmiş bakır kartta kalır; Kablolamayı "
        "Yeniden Yap ve Eskimiş Kablolamayı Kaldır artık ona dokunmaz."
    ),
    "Remove the wiring and lay it again from nothing. Use this after moving parts: "
    "Auto-wire only adds, so it leaves the copper laid out for where things used to be. "
    "Hand-drawn copper with no net is never touched.": (
        "Kablolamayı söküp sıfırdan yeniden döşer. Parçaları taşıdıktan sonra kullanın: "
        "Otomatik Kablola yalnızca ekler, dolayısıyla eski konumlar için döşenmiş bakırı "
        "yerinde bırakır. Neti olmayan elle çizilmiş bakıra asla dokunulmaz."
    ),
    "Draw conductors on the face you are NOT looking at as hatched, the way a part "
    "on the far side already is. Turn it off to see them solid.": (
        "Bakmadığınız yüzdeki iletkenleri, karşı yüzdeki bir parçanın çizildiği gibi "
        "taralı çizer. Dolu görmek için kapatın."
    ),
    "Click two holes. Says how many holes across they are, how far apart in mm, "
    "and how many steps of solder trace it would take to join them — three "
    "different numbers that answer three different questions.": (
        "İki deliğe tıklayın. Kaç delik ötede olduklarını, mm cinsinden aralarındaki "
        "mesafeyi ve birleştirmek için kaç adım lehim yolu gerektiğini söyler — üç ayrı "
        "soruyu yanıtlayan üç ayrı sayı."
    ),
    "Find a part by reference, value or package and centre the view on it. On a dense "
    "board there is otherwise no way to answer “where is R37”.": (
        "Bir parçayı referansından, değerinden ya da kılıfından bulur ve görünümü ona "
        "ortalar. Kalabalık bir kartta “R37 nerede” sorusunun başka yanıtı yoktur."
    ),
    "The board in 3D (Ctrl+3). It is drawn only while its tab is in front: it is the most "
    "expensive view in the window to keep up to date.": (
        "Kart 3D olarak (Ctrl+3). Yalnızca sekmesi öndeyken çizilir: pencerede güncel "
        "tutulması en pahalı görünüm odur."
    ),
    "The mask and finish the board says it has. One that says nothing is drawn "
    "as its material is sold: green and tinned for FR-4, bare copper on phenolic.": (
        "Kartın söylediği maske ve kaplama. Bir şey söylemeyen kart, malzemesinin satıldığı "
        "gibi çizilir: FR-4 yeşil ve kalaylı, pertinaks çıplak bakır."
    ),
    "Every binding, read off this menu bar — plus the board gestures, which are "
    "on no menu and were previously only in the source.": (
        "Her kısayol, bu menü çubuğundan okunarak — artı hiçbir menüde olmayan ve daha "
        "önce yalnızca kaynak kodda bulunan kart hareketleri."
    ),
    "Wakes DRC's current-capacity rule and picks the wire gauge on the build "
    "guide's cut list. Nothing else in the application can set it.": (
        "DRC'nin akım kapasitesi kuralını uyandırır ve montaj rehberinin kesim listesindeki "
        "tel kalınlığını seçer. Uygulamada bunu başka hiçbir şey belirleyemez."
    ),
    "Wakes DRC's creepage rule above the mains threshold. A -12 V rail is an "
    "ordinary value here, which is why it needs its own tick rather than a zero.": (
        "Şebeke eşiğinin üstünde DRC'nin yüzeysel kaçak kuralını uyandırır. -12 V'luk bir "
        "ray burada sıradan bir değerdir; bu yüzden sıfır yerine kendi kutucuğu gerekir."
    ),
    "This board prints its own addresses, so the editor's ruler would repeat them.": (
        "Bu kart kendi adreslerini basıyor, düzenleyicinin cetveli onları tekrarlar."
    ),
    "Column letters and row numbers along the edges of the view.": (
        "Görünümün kenarları boyunca sütun harfleri ve satır numaraları."
    ),
    "Only stripboard has tracks to cut. Board ▸ Design the Board ▸ Kind.": (
        "Yalnızca şeritli kartta kesilecek şerit vardır. Kart ▸ Kartı Tasarla ▸ Tür."
    ),
    # -- the status bar's fixed sentences --------------------------------------
    "Nothing to place: the board is empty.": "Yerleştirilecek bir şey yok: kart boş.",
    "Cancelled before an arrangement was finished; the board is as it was.": (
        "Bir yerleşim tamamlanmadan iptal edildi; kart olduğu gibi kaldı."
    ),
    "Cancelled before a board was tried; nothing changed.": "Hiçbir kart denenmeden iptal edildi; hiçbir şey değişmedi.",
    "Trying boards was cancelled after {count} board(s).": "Kart denemesi {count} karttan sonra iptal edildi.",
    "Select a net in the Nets panel, or a part on the board, then auto-wire.": (
        "Netler panelinden bir net ya da kart üzerinden bir parça seçin, sonra otomatik "
        "kablolayın."
    ),
    "Select a net in the Nets panel, or a part on the board, then redo its wiring.": (
        "Netler panelinden bir net ya da kart üzerinden bir parça seçin, sonra "
        "kablolamasını yeniden yapın."
    ),
    "There is no circuit yet, so there is nothing to wire.": (
        "Henüz devre yok, dolayısıyla kablolanacak bir şey de yok."
    ),
    "No out-of-date wiring: every piece still connects the net it claims.": (
        "Eskimiş kablolama yok: her parçası hâlâ iddia ettiği neti bağlıyor."
    ),
    "Select a part or a conductor on the board first, then copy it.": (
        "Önce kart üzerinden bir parça ya da iletken seçin, sonra kopyalayın."
    ),
    "Select a part or a conductor on the board first, then duplicate it.": (
        "Önce kart üzerinden bir parça ya da iletken seçin, sonra çoğaltın."
    ),
    "There is no block on the clipboard. Copy a part or some copper first.": (
        "Panoda blok yok. Önce bir parça ya da biraz bakır kopyalayın."
    ),
    "That block does not fit on this board.": "O blok bu karta sığmıyor.",
    "There are no parts on this board yet.": "Bu kartta henüz parça yok.",
    "Click a hole to cut the strip there; click a cut again to take it back. "
    "Esc ends.": (
        "Şeridi kesmek için bir deliğe tıklayın; kesiği geri almak için tekrar tıklayın. "
        "Esc bitirir."
    ),
    "This board has never been saved, so there is nothing on disk to reload.": (
        "Bu kart hiç kaydedilmedi, dolayısıyla diskte yeniden yüklenecek bir şey yok."
    ),
    "Click a pin, then the pin it joins. Neither on a net yet? One gets made. "
    "Esc cancels.": (
        "Bir pine, sonra birleşeceği pine tıklayın. Hiçbiri bir nette değilse yeni bir net "
        "oluşturulur. Esc iptal eder."
    ),
    "Select the pins to disconnect in the Nets panel — expand a net to see "
    "them.": (
        "Ayrılacak pinleri Netler panelinden seçin — görmek için bir neti genişletin."
    ),
    "Select one net in the Nets panel first.": "Önce Netler panelinden tek bir net seçin.",
    "Opening the 3D view builds it — this takes a moment.": (
        "3D görünümü açmak onu kurar — bu biraz sürer."
    ),
    # -- dialog titles ---------------------------------------------------------
    "Redo the wiring of the nets whose parts moved?": (
        "Parçaları taşınan netlerin kablolaması yeniden yapılsın mı?"
    ),
    "<b>{names}</b> still carry the copper laid out before a part moved.<p>Auto-wire only "
    "adds, so wiring now leaves that copper in place and puts more beside it. Redoing "
    "their wiring removes it and plans again.</p>": (
        "<b>{names}</b> hâlâ bir parça taşınmadan önce döşenen bakırı taşıyor.<p>Otomatik "
        "Kablola yalnızca ekler; şimdi kablolamak o bakırı yerinde bırakıp yanına yenisini "
        "koyar. Kablolamayı yeniden yapmak onu söküp yeniden planlar.</p>"
    ),
    "Imported with warnings": "Uyarılarla içe aktarıldı",
    "Imported {count} net(s) from {name}": "{name} dosyasından {count} net içe aktarıldı",
    "with warnings:": "uyarılar:",
    "… and {count} more": "… ve {count} tane daha",
    # -- the status bar and the panels' summaries ---------------------------------
    # These were the last English left on a Turkish screen: the menus were translated
    # and the numbers under them were not.
    "done": "bitti",
    "Not on the board: {pins}": "Kartta değil: {pins}",
    "not on the board": "kartta değil",
    "{matched} of {total} nets match · {opens} broken · {shorts} shorted": (
        "{total} netin {matched} tanesi uyuşuyor · {opens} kopuk · {shorts} kısa devre"
    ),
    "{count} not on the board yet": "{count} tanesi henüz kartta değil",
    "…and {count} more": "…ve {count} tane daha",
    "3D view unavailable:": "3D görünüm kullanılamıyor:",
    "locked": "kilitli",
    # -- the selection verbs, spliced into one sentence -----------------------------
    "Select a part on the board first, then {what}.": "Önce kartta bir parça seçin, sonra "
                                                      "{what}.",
    "rotate it": "döndürün",
    "mirror it": "aynalayın",
    "delete it": "silin",
    "lock or unlock it": "kilitleyin ya da kilidini açın",
    "edit its properties": "özelliklerini düzenleyin",
    "change it": "değiştirin",
    "{count} refused: {reasons}": "{count} reddedildi: {reasons}",
    "Rotated {count} part(s)": "{count} parça döndürüldü",
    "Mirrored {count} part(s)": "{count} parça aynalandı",
    "Locked {count} part(s)": "{count} parça kilitlendi",
    "Unlocked {count} part(s)": "{count} parçanın kilidi açıldı",
    "Deleted {count} part(s)": "{count} parça silindi",
    "Disconnected {count} pin(s)": "{count} pin ayrıldı",
    # -- confirmations, with the verb on the button ------------------------------------
    "Delete {count} conductor?": "{count} iletken silinsin mi?",
    "Delete {count} conductors?": "{count} iletken silinsin mi?",
    "Delete {refs}?": "{refs} silinsin mi?",
    "The selected conductor goes with them.": "Seçili iletken de onlarla birlikte silinir.",
    "The {count} selected conductors go with them.": (
        "Seçili {count} iletken de onlarla birlikte silinir."
    ),
    "Other wires and traces are left in place — the checks will point at anything left "
    "dangling.": (
        "Diğer teller ve lehim yolları yerinde kalır — boşta kalan ne varsa denetimler gösterir."
    ),
    "Delete net {name}?": "{name} neti silinsin mi?",
    "{count} conductor(s) already laid for it stay on the board, and Redo Wiring and "
    "Remove Out-of-Date Wiring leave them alone from then on.": (
        "Onun için döşenmiş {count} iletken kartta kalır; Kablolamayı Yeniden Yap ve "
        "Eskimiş Kablolamayı Kaldır artık onlara dokunmaz."
    ),
    "{name} has changes that are not saved.": "{name} üzerinde kaydedilmemiş değişiklikler var.",
    "This board has changes that are not saved.": "Bu kartta kaydedilmemiş değişiklikler var.",
    "Don't Save": "Kaydetme",
    "Saving keeps them; discarding loses them for good.": (
        "Kaydederseniz korunurlar; kaydetmezseniz temelli kaybolurlar."
    ),
    "Discard the unsaved changes in this window and load {name} as it is "
    "on disk?": "Bu penceredeki kaydedilmemiş değişiklikler atılıp {name} diskteki haliyle yüklensin mi?",
    "This cannot be undone: reloading replaces the document, and the undo "
    "history with it.": (
        "Bu geri alınamaz: yeniden yüklemek belgeyi ve onunla birlikte geri alma geçmişini "
        "değiştirir."
    ),
    "Reload": "Yeniden Yükle",
    "Reloaded {name}": "{name} yeniden yüklendi",
    # -- files -------------------------------------------------------------------------
    "Open a board": "Kart aç",
    "Save As": "Farklı Kaydet",
    "Perfboard Studio documents (*.perf)": "Perfboard Studio belgeleri (*.perf)",
    "Import KiCad netlist": "KiCad netlist içe aktar",
    "KiCad netlists (*.net);;All files (*)": "KiCad netlist dosyaları (*.net);;Tüm dosyalar (*)",
    "Loaded {name}": "{name} yüklendi",
    "({count} warning(s))": "({count} uyarı)",
    "Opened with warnings": "Uyarılarla açıldı",
    "{name} loaded, but not all of it was understood:": "{name} yüklendi, ama tamamı anlaşılamadı:",
    "Save failed": "Kaydedilemedi",
    "Could not write {path}: {reason}": "{path} yazılamadı: {reason}",
    "Saved {path}": "Kaydedildi: {path}",
    "Exported {path}": "Dışa aktarıldı: {path}",
    "Exported {first} and {second}": "{first} ve {second} dışa aktarıldı",
    "Could not write the PDF: {reason}": "PDF yazılamadı: {reason}",
    "Could not write {path}. Is the folder writable?": "{path} yazılamadı. Klasör yazılabilir mi?",
    "PDF written": "PDF yazıldı",
    "This machine cannot render 3D off screen, so no PNG was written.": (
        "Bu makine 3D'yi ekran dışında çizemiyor, o yüzden PNG yazılmadı."
    ),
    # -- the progress dialog --------------------------------------------------------------
    "Trying arrangements, and wiring each one to compare them…": (
        "Yerleşimler deneniyor, karşılaştırmak için her biri kablolanıyor…"
    ),
    "Removing the wiring and laying it again…": "Kablolama sökülüp yeniden döşeniyor…",
    "Wiring with every style…": "Her tarzla kablolanıyor…",
    "Wiring…": "Kablolanıyor…",
    "Planning cuts and links…": "Kesikler ve bağlantılar planlanıyor…",
    "Planning jumpers…": "Jumper'lar planlanıyor…",
    "Border, left and right": "Kenar payı, sağ ve sol",
    "Border, top and bottom": "Kenar payı, üst ve alt",
    "Full size · 830 points · 63 columns": "Tam boy · 830 nokta · 63 sütun",
    "Half size · 400 points · 30 columns": "Yarım boy · 400 nokta · 30 sütun",
    "Mini · 170 points · 17 columns, no rails": "Mini · 170 nokta · 17 sütun, raysız",
    "Channel": "Oluk",
    "Narrow part": "Dar kısım",
    "300 mil · standard, a DIP straddles it": "300 mil · standart, DIP üstüne oturur",
    "600 mil · Arduino Nano": "600 mil · Arduino Nano için",
    "700 mil · Raspberry Pi Pico": "700 mil · Raspberry Pi Pico için",
    "900 mil · narrow ESP32 devkit": "900 mil · dar ESP32 geliştirme kartı",
    "1000 mil · ESP32 devkit": "1000 mil · ESP32 geliştirme kartı",
    "900 mil flex · 300 mil for columns 1–39": "900 mil esnek · 1–39. sütunlarda 300 mil",
    "1000 mil flex · 300 mil for columns 1–39": "1000 mil esnek · 1–39. sütunlarda 300 mil",
    "Wide all the way": "Baştan sona geniş",
    " columns": " sütun",
    "How many columns, from column 1, keep the ordinary 0.3 inch channel with their strips moved in to it, so a DIP still fits beside the module.": "1. sütundan başlayarak kaç sütunun, şeritleri ona doğru kaydırılmış olarak olağan 0,3 inçlik oluğu koruduğu; böylece modülün yanına hâlâ bir DIP sığar.",
    "Nothing is soldered on a breadboard: use a jumper or an insulated wire.": "Breadboard'da lehim yapılmaz: jumper ya da izoleli tel kullanın.",
    "Stopping, and keeping the best found so far…": (
        "Durduruluyor; şimdiye kadar bulunan en iyisi tutuluyor…"
    ),
    # -- the board materials, as Board Setup lists them --------------------------------
    "FR-4 — glass epoxy, the green kind. Tolerates heat well.": (
        "FR-4 — cam epoksi, yeşil olan. Isıya iyi dayanır."
    ),
    "FR-2 — phenolic paper (\"pertinaks\"), the brown kind. Pads lift easily.": (
        "FR-2 — fenolik kâğıt (\"pertinaks\"), kahverengi olan. Pedler kolay kalkar."
    ),
    "FR-1 — phenolic paper, as FR-2.": "FR-1 — fenolik kâğıt, FR-2 gibi.",
    # -- the file watcher, the planner and the nets ------------------------------------
    "Still planning — cancel it or wait for it before closing.": (
        "Planlama sürüyor — kapatmadan önce iptal edin ya da bitmesini bekleyin."
    ),
    "{name} changed on disk but could not be read: {problem}": (
        "{name} diskte değişti ama okunamadı: {problem}"
    ),
    "{name} changed on disk, and this window has unsaved edits. "
    "File ▸ Reload from Disk to take the file's version.": (
        "{name} diskte değişti ve bu pencerede kaydedilmemiş düzenlemeler var. "
        "Dosyanın sürümünü almak için Dosya ▸ Diskten Yeniden Yükle."
    ),
    "Reloaded {name}: it changed on disk, and the undo history went with it": (
        "{name} yeniden yüklendi: diskte değişmişti, geri alma geçmişi de onunla gitti"
    ),
    # -- the board's own prose: measuring, picking pins, joining them -----------------
    "{hole} — the same hole.": "{hole} — aynı delik.",
    "holes": "delik",
    "{mm:.2f} mm apart": "{mm:.2f} mm arayla",
    "{steps} step(s) by trace": "lehim yoluyla {steps} adım",
    "Click the first hole.": "İlk deliğe tıklayın.",
    "From {hole} — click the second hole.": "{hole} deliğinden — ikinci deliğe tıklayın.",
    "No component pin at {hole}.": "{hole} deliğinde parça pini yok.",
    "{pin} is already on the list.": "{pin} zaten listede.",
    "{pin} is already on {net}.": "{pin} zaten {net} üzerinde.",
    "{pin} belongs to {net}. Disconnect it there first — a pin can only "
    "be on one net.": (
        "{pin} {net} netine ait. Önce oradan ayır — bir pin yalnızca bir nette olabilir."
    ),
    "{pin} is already the pin you started from.": "{pin} zaten başladığınız pin.",
    "{a} and {b} are both already on {net}.": "{a} ve {b} zaten {net} üzerinde.",
    "{a} is on {net_a} and {b} is on {net_b}. Joining two nets is a change to "
    "the circuit — disconnect one of the pins first.": (
        "{a} {net_a} üzerinde, {b} ise {net_b} üzerinde. İki neti birleştirmek devreyi "
        "değiştirmektir — önce pinlerden birini ayırın."
    ),
    # -- the sheet -----------------------------------------------------------------------
    "not in the design": "tasarımda yok",
    "not placed yet": "henüz yerleştirilmedi",
    # -- custom part: a body off its pins, and the IDC box header ------------------------
    "Body offset along the pins (mm)": "Gövde kayması, pin sırası boyunca (mm)",
    "Body offset across the pins (mm)": "Gövde kayması, pin sırasına dik (mm)",
    "IDC box header (ribbon cable)": "IDC kutu başlık (şerit kablo)",
    # -- custom part: a surface-mount chip on a DIP adapter --------------------------------
    "Surface-mount chip on a DIP adapter": "DIP adaptöründe yüzey montaj çip",
    "Package": "Kılıf",
    "Holes between rows (0 for the usual)": "Sıralar arası delik (olağanı için 0)",
    # -- what a part says about itself (PinoutEditor) -------------------------------------
    "From the package": "Gövdeden",
    "NPN transistor (names B, C, E)": "NPN transistör (adlar B, C, E)",
    "PNP transistor (names B, C, E)": "PNP transistör (adlar B, C, E)",
    "N-channel MOSFET (names G, D, S)": "N kanallı MOSFET (adlar G, D, S)",
    "P-channel MOSFET (names G, D, S)": "P kanallı MOSFET (adlar G, D, S)",
    "Zener diode": "Zener diyot",
    "Fuse or PTC": "Sigorta ya da PTC",
    "What this part is, when its package cannot say. A transistor symbol is "
    "drawn only once its leads are named below, because which leg is the gate "
    "is a fact about the part, not the package.": (
        "Gövdesinin söyleyemediği durumda bu parçanın ne olduğu. Transistör sembolü ancak "
        "bacakları aşağıda adlandırılınca çizilir, çünkü hangi bacağın geyt olduğu gövdenin "
        "değil parçanın bilgisidir."
    ),
    "Pin": "Pin no",
    "What the datasheet calls each lead. Printed on the schematic and in the "
    "soldering guide, so a module's pin reads as GPIO21 rather than 21.": (
        "Veri sayfasının her bacağa verdiği ad. Şemada ve lehim rehberinde basılır; böylece "
        "bir modülün pini 21 değil GPIO21 diye okunur."
    ),
    "Symbol": "Sembol",
    "Pin names": "Pin adları",
    "The package calls this pin {name}.": "Kılıf bu pini {name} olarak adlandırıyor.",
    "Pin names from the catalog's {part}.": "Pin adları katalogdaki {part} parçasından.",
    "These names were typed here and are kept. The catalog's {part} is {pins}.": (
        "Bu adlar burada yazıldı ve korunuyor. Katalogdaki {part}: {pins}."
    ),
    # -- naming the board ------------------------------------------------------------
    "Rena&me Board…": "Kar&tı Yeniden Adlandır…",
    "The board's title, printed on the build guide, on the schematic and on "
    "the project folder. A board is named after its file when first saved.": (
        "Kartın başlığı: montaj rehberine, şemaya ve proje klasörüne basılır. Kart ilk "
        "kaydedildiğinde dosyasının adını alır."
    ),
    "Screw terminal, wires from above (vertical)": "Klemens, tel yukarıdan (dik)",
    # -- parts off the board -------------------------------------------------
    "Wires to a part off the board (panel pot, jack, switch)": (
        "Kart dışındaki parçaya giden teller (panel potu, jak, anahtar)"
    ),
    "Wires": "Tel sayısı",
    "Holes between pads": "Pedler arası delik",
    "Wire length (mm, 0 to cut to fit)": "Tel boyu (mm; ölçüye göre kesmek için 0)",
    "Parts off the board": "Kart dışındaki parçalar",
    "&Mount on the Panel": "&Panele Monte Et",
    "Off the board and wired to it instead — a pot on the panel, a jack in the enclosure. "
    "Its pins become the pads its wires land in.": (
        "Kartın dışına alınır ve karta tellerle bağlanır — paneldeki bir pot, kutudaki bir "
        "jak gibi. Pinleri, tellerinin geldiği pedlere dönüşür."
    ),
    "{ref} has no package this program can build.": (
        "{ref} için bu programın oluşturabileceği bir kılıf yok."
    ),
    "{ref} is off the board now, wired to it. Its wires land where its pins were; the build "
    "guide says where each one goes.": (
        "{ref} artık kartın dışında, karta tellerle bağlı. Telleri pinlerinin olduğu yere "
        "geliyor; hangisinin nereye gittiğini montaj rehberi söylüyor."
    ),
    "Potentiometer (three leads, the middle one the wiper)": (
        "Potansiyometre (üç uç, ortadaki sürgü)"
    ),
    "LED (names A, K)": "LED (adlar A, K)",
    # -- the catalog and modules ---------------------------------------------
    "Transistors": "Transistörler",
    "MOSFETs": "MOSFET'ler",
    "Regulators and references": "Regülatörler ve referanslar",
    "Diodes": "Diyotlar",
    "Protection": "Koruma",
    "Sensors": "Sensörler",
    "ICs": "Entegreler",
    "Modules": "Modüller",
    "Check": "Kontrol et",
    "Source": "Kaynak",
    "Module on header pins (dev board, breakout)": "Pin başlıklı modül (geliştirme kartı, breakout)",
    "Pin columns": "Pin sütunu",
    "Pins per column": "Sütun başına pin",
    "Holes between columns": "Sütunlar arası delik",
    "Holes between pins in a column": "Sütundaki pinler arası delik",
    "Module board width (mm)": "Modül kartının genişliği (mm)",
    "Module board length (mm)": "Modül kartının boyu (mm)",
    "Tallest part on it (mm)": "Üstündeki en uzun parça (mm)",
    "Plugged into female headers": "Dişi başlığa takılı",
    "Board offset across the columns (mm)": "Kartın sütunlara dik kayması (mm)",
    "Board offset along the columns (mm)": "Kartın sütun boyunca kayması (mm)",
    "Pin names, in pin order:": "Pin adları, pin sırasıyla:",
    "One per line, or separated by commas or spaces: 3V3 GND TX RX…": (
        "Her satıra bir tane, ya da virgül veya boşlukla ayrılmış: 3V3 GND TX RX…"
    ),
    "Pin 1 first, then row by row: left to right across the columns, then the "
    "next row down. Leave it empty to number the pins only.": (
        "Önce pin 1, sonra satır satır: sütunlar boyunca soldan sağa, sonra bir alttaki "
        "satır. Boş bırakılırsa pinler yalnız numaralanır."
    ),
    "{names} name(s) for {pins} pin(s).": "{pins} pin için {names} ad.",
    "Sho&w Pin Names": "P&in Adlarını Göster",
    "No room to print:": "Basacak yer yok:",
    "Show Labels on &the Board": "Karttaki &Etiketleri Göster",
    "Show the labels written on the board, on the board and in 3D.": (
        "Karta yazılmış etiketleri kartta ve 3D'de gösterir."
    ),
    "Add La&bel…": "&Etiket Ekle…",
    "Write something on the board — \"MOTOR 24V\" beside the terminal that "
    "takes it. Printed on the 1:1 sheet and in the guide's pictures; drag it "
    "into place, double-click it to change it.": (
        "Karta bir şey yazar — onu alan klemensin yanına \"MOTOR 24V\" gibi. 1:1 çıktıda "
        "ve rehberin resimlerinde basılır; sürükleyerek yerleştirin, değiştirmek için çift "
        "tıklayın."
    ),
    "Board Label": "Kart Etiketi",
    "What to write on the board: MOTOR 24V, CAN →…": "Karta ne yazılacak: MOTOR 24V, CAN →…",
    "Component side (top)": "Parça yüzü (üst)",
    "Solder side (bottom)": "Lehim yüzü (alt)",
    "A label on the solder side is written where the wiring is checked, and reads "
    "the right way round from underneath.": (
        "Lehim yüzündeki etiket, bağlantıların kontrol edildiği yere yazılır ve alttan "
        "bakınca düz okunur."
    ),
    "Edit Label…": "Etiketi Düzenle…",
    "Add Label Here…": "Buraya Etiket Ekle…",
    "Print each part's pin names beside its pins, on the board and in 3D. Turn it off "
    "while placing or wiring a crowded board.": (
        "Her parçanın pin adlarını pinlerinin yanına yazar, kartta ve 3D'de. Kalabalık bir "
        "kartı yerleştirirken ya da kablolarken kapatın."
    ),
    # -- the parts catalog -------------------------------------------------------------
    # What each part is and what to check on the one in hand: ``catalog.CATALOG``'s
    # summaries and checks, shown in the parts list's tooltips. Reached through t() by
    # variable, so ``tests/test_i18n.py`` reads them out of the catalog itself. The
    # datasheet a pinout comes from is a citation and stays as it is written. Four
    # summaries read the same in Turkish ("NPN Darlington, 60 V, 5 A") and are not here.
    "NPN, 45 V, 100 mA, general purpose": "NPN, 45 V, 100 mA, genel amaçlı",
    "NPN, 30 V, 100 mA, general purpose": "NPN, 30 V, 100 mA, genel amaçlı",
    "PNP, 45 V, 100 mA, general purpose": "PNP, 45 V, 100 mA, genel amaçlı",
    "PNP, 30 V, 100 mA, general purpose": "PNP, 30 V, 100 mA, genel amaçlı",
    "NPN, 40 V, 200 mA, general purpose": "NPN, 40 V, 200 mA, genel amaçlı",
    "PNP, 40 V, 200 mA, general purpose": "PNP, 40 V, 200 mA, genel amaçlı",
    "NPN, 40 V, 600 mA, switching (plastic TO-92, sold as PN2222A)": (
        "NPN, 40 V, 600 mA, anahtarlama (plastik TO-92, PN2222A adıyla satılır)"
    ),
    "Check the legs against the datasheet of the part you have before soldering.": (
        "Lehimlemeden önce elinizdeki parçanın bacaklarını veri sayfasıyla karşılaştırın."
    ),
    "The metal-can (TO-18) 2N2222 is pinned differently. Check the legs against the "
    "datasheet of the part you have before soldering.": (
        "Metal kılıflı (TO-18) 2N2222'nin bacak dizilişi farklıdır. Lehimlemeden önce "
        "elinizdeki parçanın bacaklarını veri sayfasıyla karşılaştırın."
    ),
    "The tab is the collector. Check the legs against the datasheet of the part you "
    "have before soldering.": (
        "Tırnak kolektöre bağlıdır. Lehimlemeden önce elinizdeki parçanın bacaklarını veri "
        "sayfasıyla karşılaştırın."
    ),
    "NPN power, 100 V, 3 A": "NPN güç, 100 V, 3 A",
    "NPN power, 100 V, 6 A": "NPN güç, 100 V, 6 A",
    "N-channel, 60 V, 200 mA, small signal": "N kanal, 60 V, 200 mA, küçük sinyal",
    "N-channel, 60 V, 500 mA, small signal": "N kanal, 60 V, 500 mA, küçük sinyal",
    "Pinned the other way round from the 2N7000. Check the legs against the datasheet "
    "of the part you have before soldering.": (
        "Bacak dizilişi 2N7000'in tersidir. Lehimlemeden önce elinizdeki parçanın "
        "bacaklarını veri sayfasıyla karşılaştırın."
    ),
    "N-channel, 100 V, 33 A, 10 V gate": "N kanal, 100 V, 33 A, 10 V geyt",
    "N-channel, 55 V, 49 A, 10 V gate": "N kanal, 55 V, 49 A, 10 V geyt",
    "N-channel, 55 V, 47 A, logic-level gate (on from 5 V)": (
        "N kanal, 55 V, 47 A, lojik seviye geyt (5 V ile iletime geçer)"
    ),
    "N-channel, 100 V, 9.7 A, 10 V gate": "N kanal, 100 V, 9,7 A, 10 V geyt",
    "N-channel, 55 V, 110 A, 10 V gate": "N kanal, 55 V, 110 A, 10 V geyt",
    "P-channel, -100 V, -23 A": "P kanal, -100 V, -23 A",
    "P-channel, -55 V, -74 A": "P kanal, -55 V, -74 A",
    "P-channel, -55 V, -19 A": "P kanal, -55 V, -19 A",
    "The tab is the drain.": "Tırnak drain'e bağlıdır.",
    "The tab is the drain. Not fully on from a 3.3 V or 5 V pin.": (
        "Tırnak drain'e bağlıdır. 3,3 V ya da 5 V'luk bir pinden tam iletime geçmez."
    ),
    "The tab is the drain. A high-side switch: source to the supply.": (
        "Tırnak drain'e bağlıdır. Üst taraf anahtarı: source beslemeye bağlanır."
    ),
    "Linear regulator, +5 V, 1.5 A": "Lineer regülatör, +5 V, 1,5 A",
    "Linear regulator, +9 V, 1.5 A": "Lineer regülatör, +9 V, 1,5 A",
    "Linear regulator, +12 V, 1.5 A": "Lineer regülatör, +12 V, 1,5 A",
    "Linear regulator, -5 V, 1.5 A": "Lineer regülatör, -5 V, 1,5 A",
    "Linear regulator, +5 V, 100 mA": "Lineer regülatör, +5 V, 100 mA",
    "The tab is ground.": "Tırnak toprağa bağlıdır.",
    "The tab is ground. Needs 0.33 uF on the input and 0.1 uF on the output.": (
        "Tırnak toprağa bağlıdır. Girişte 0,33 µF, çıkışta 0,1 µF ister."
    ),
    "NOT pinned like a 7805: the tab is the INPUT.": (
        "Bacak dizilişi 7805 gibi DEĞİL: tırnak GİRİŞE bağlıdır."
    ),
    "Adjustable regulator, +1.25 to +37 V, 1.5 A": (
        "Ayarlı regülatör, +1,25 ile +37 V arası, 1,5 A"
    ),
    "Adjustable regulator, -1.25 to -37 V, 1.5 A": (
        "Ayarlı regülatör, -1,25 ile -37 V arası, 1,5 A"
    ),
    "The tab is the output.": "Tırnak çıkışa bağlıdır.",
    "NOT pinned like an LM317: the tab is the INPUT.": (
        "Bacak dizilişi LM317 gibi DEĞİL: tırnak GİRİŞE bağlıdır."
    ),
    "Adjustable shunt reference, 2.5 to 36 V": "Ayarlı şönt referans, 2,5 ile 36 V arası",
    "Small-signal diode, 100 V, 200 mA": "Küçük sinyal diyodu, 100 V, 200 mA",
    "Rectifier, 1000 V, 1 A": "Doğrultucu, 1000 V, 1 A",
    "Zener, 3.3 V, 0.5 W": "Zener, 3,3 V, 0,5 W",
    "Zener, 5.1 V, 0.5 W": "Zener, 5,1 V, 0,5 W",
    "Zener, 12 V, 0.5 W (a MOSFET gate clamp)": "Zener, 12 V, 0,5 W (MOSFET geyt kırpıcısı)",
    "Zener, 15 V, 0.5 W (a MOSFET gate clamp)": "Zener, 15 V, 0,5 W (MOSFET geyt kırpıcısı)",
    "Polymer PTC (polyfuse), radial, leads 5 mm apart": (
        "Polimer PTC (polyfuse), radyal, bacaklar arası 5 mm"
    ),
    "Its size grows with its hold current: if yours is larger than 8 mm, describe it "
    "as a disc capacitor of its real size and mark it a fuse.": (
        "Boyu tutma akımıyla büyür: sizinki 8 mm'den büyükse gerçek boyunda bir disk "
        "kondansatör olarak tanımlayın ve sigorta olarak işaretleyin."
    ),
    "Temperature sensor, 10 mV per degree C": "Sıcaklık sensörü, derece başına 10 mV",
    "HC-SR501 PIR motion sensor": "HC-SR501 PIR hareket sensörü",
    "Passive infrared motion sensor: OUT goes to 3.3 V when something warm moves, for 5 s to "
    "5 minutes": (
        "Pasif kızılötesi hareket sensörü: sıcak bir şey kıpırdayınca OUT 5 saniye ile 5 dakika "
        "arası 3,3 V'a çıkar"
    ),
    "Feed it 5 to 20 V: below 5 V it does not work. Its two trimmers set how long OUT stays high "
    "and how far it sees, 3 to 7 m, and its jumper whether a new movement starts that time "
    "again (H) or not (L).": (
        "5 ile 20 V arasıyla besleyin: 5 V'un altında çalışmaz. İki trimpotu OUT'un ne kadar "
        "yüksek kalacağını ve ne kadar uzağı gördüğünü (3-7 m), jumper'ı ise yeni bir hareketin "
        "bu süreyi yeniden başlatıp (H) başlatmayacağını (L) ayarlar."
    ),
    "Reflective IR sensor: an IR LED and a phototransistor side by side, seeing 0.2 to "
    "15 mm, best at 2.5": (
        "Yansımalı kızılötesi sensör: yan yana bir IR LED ve bir fototransistör; 0,2 ile 15 "
        "mm arasını görür, en iyi 2,5 mm'de"
    ),
    "Its legs are 5.5 mm apart across and the holes 5.08: bend them in a little. Its "
    "two snap-in clips are for 2.5 mm holes, so cut them off or let it stand on them. "
    "The blue dome is the LED (A, K), which needs its series resistor; the black one is "
    "the phototransistor (C, E).": (
        "Bacakları enine 5,5 mm, delikler 5,08 mm arayla: bacakları biraz içe bükün. İki "
        "geçmeli tırnağı 2,5 mm'lik delikler içindir; kesin ya da parçayı üzerlerinde "
        "durdurun. Mavi kubbe LED'dir (A, K) ve seri direnç ister; siyah olan "
        "fototransistördür (C, E)."
    ),
    "Temperature sensor, 1-Wire, needs a 4.7k pull-up on DQ": (
        "Sıcaklık sensörü, 1-Wire, DQ hattında 4,7k pull-up ister"
    ),
    "Hall-effect switch: its open-collector output pulls low when a magnet comes close": (
        "Hall etkili anahtar: açık kollektörlü çıkışı bir mıknatıs yaklaşınca düşük seviyeye "
        "çeker"
    ),
    "Its output only pulls low: give OUT a pull-up resistor to VCC. Only one pole of a magnet "
    "switches it: if nothing happens, turn the magnet round. Check the legs against the "
    "datasheet of the part you have before soldering.": (
        "Çıkışı yalnızca düşük seviyeye çeker: OUT ile VCC arasına bir pull-up direnci koyun. "
        "Onu mıknatısın yalnızca bir kutbu tetikler: hiçbir şey olmazsa mıknatısı çevirin. "
        "Lehimlemeden önce bacakları elinizdeki parçanın datasheet'iyle karşılaştırın."
    ),
    "Linear Hall-effect sensor: about 2.5 V with no field, about 1.8 mV per gauss at 5 V": (
        "Doğrusal Hall etkili sensör: alan yokken yaklaşık 2,5 V, 5 V'ta gauss başına yaklaşık "
        "1,8 mV"
    ),
    "Timer": "Zamanlayıcı",
    "Switches": "Anahtarlar",
    # Catalog names that describe the part; a part NUMBER has no entry and stays as printed.
    "Tactile switch 6x6 mm": "Tact buton 6×6 mm",
    "Tactile switch 12x12 mm": "Tact buton 12×12 mm",
    "PTC resettable fuse": "PTC kendini sıfırlayan sigorta",
    "Pololu A4988 carrier": "Pololu A4988 taşıyıcı kartı",
    "Pololu DRV8825 carrier": "Pololu DRV8825 taşıyıcı kartı",
    "Power in": "Güç girişi",
    "Connectors": "Konnektörler",
    "Sound": "Ses",
    "Trimmers and inductors": "Trimpotlar ve bobinler",
    "Bourns 3296W trimmer": "Bourns 3296W trimpot",
    "Potentiometer 16 mm, panel mount": "Potansiyometre 16 mm, panele takılan",
    "A panel pot off the board on its three wires: CCW end, wiper, CW end": (
        "Kartın dışında, üç teliyle bağlanan bir panel potansiyometresi: CCW ucu, orta uç, CW "
        "ucu"
    ),
    "Seen from the shaft with its tags at the bottom, they are CCW, W and CW from the left. If "
    "it turns the wrong way, swap the CCW and CW wires, not the wiper. Put its value, printed "
    "as B10K or A10K, in the value: B is linear, A is the log taper a volume control wants.": (
        "Milden bakıldığında, uçları aşağıdayken soldan CCW, W ve CW'dir. Ters yöne dönüyorsa "
        "orta ucu değil, CCW ile CW tellerini değiştirin. Üzerinde B10K ya da A10K diye yazan "
        "değerini değer alanına girin: B doğrusal, A ise ses kontrolünün istediği logaritmik "
        "eğridir."
    ),
    "Multi-turn trimmer potentiometer, 25 turns, adjusted from the top": (
        "Çok turlu trimpot, 25 tur, üstten ayarlanır"
    ),
    "Its resistance is printed on it in three digits: 103 is 10 kohm, 502 is 5 kohm. Put "
    "that in the value.": (
        "Direnci üzerinde üç rakamla yazar: 103, 10 kohm; 502, 5 kohm demektir. Bunu "
        "değere yazın."
    ),
    "Bourns 78F101J axial inductor": "Bourns 78F101J eksenel bobin",
    "100 uH RF choke, 165 mA, laid flat like a resistor": (
        "100 µH RF şok bobini, 165 mA, direnç gibi yatırılır"
    ),
    "A larger inductance in this series is a larger body: measure yours.": (
        "Bu serinin daha büyük endüktanslısı daha büyük gövdelidir: sizinkini ölçün."
    ),
    "GL5528 photoresistor (LDR)": "GL5528 fotodirenç (LDR)",
    "Light-dependent resistor: 10 to 20 kohm at 10 lux, 1 Mohm in the dark": (
        "Işığa bağımlı direnç: 10 lüks ışıkta 10 ile 20 kohm, karanlıkta 1 Mohm"
    ),
    "Its legs are 3 mm apart: bend each a quarter of a millimetre in to the holes drawn. "
    "Either way round works.": (
        "Bacakları 3 mm arayla durur: çizilen deliklere girmesi için her birini çeyrek "
        "milimetre içe bükün. İki yönde de takılabilir."
    ),
    "Passive buzzer 12 mm": "Pasif buzzer 12 mm",
    "Sounds only when driven with a tone, 12 mm across, legs 7.6 mm apart": (
        "Yalnızca bir tonla sürülünce öter, 12 mm çapında, bacaklar arası 7,6 mm"
    ),
    "A PASSIVE buzzer is silent on DC: drive it with a square wave from a pin (tone() on "
    "an Arduino). Its board shows underneath, which is how to tell it from an active one.": (
        "PASİF buzzer DC'de ses çıkarmaz: bir pinden kare dalgayla sürün (Arduino'da "
        "tone()). Altında kartı görünür; aktif olandan böyle ayırt edilir."
    ),
    "4x4 membrane keypad (on a header)": "4x4 membran tuş takımı (header üzerinde)",
    "Sixteen keys in four rows and four columns. Its cable plugs into this 8-pin header: "
    "C4 C3 C2 C1 R4 R3 R2 R1 from pin 1": (
        "Dört satır ve dört sütunda on altı tuş. Kablosu bu 8 pinli header'a takılır: "
        "1. pinden C4 C3 C2 C1 R4 R3 R2 R1"
    ),
    "Seen from the front its leftmost lead is R1 and its rightmost C4. Other makers' keypads "
    "are usually wired the same: test one key with a meter before trusting a clone.": (
        "Önden bakınca en soldaki ucu R1, en sağdaki C4'tür. Başka üreticilerin tuş "
        "takımları da çoğu zaman aynı bağlanır: bir kopyaya güvenmeden önce bir tuşu "
        "multimetreyle deneyin."
    ),
    "The standard indicator LED, any colour; legs 2.54 mm apart": (
        "Standart gösterge LED'i, her renk; bacaklar 2.54 mm arayla"
    ),
    "The small indicator LED, any colour; legs 2.54 mm apart": (
        "Küçük gösterge LED'i, her renk; bacaklar 2.54 mm arayla"
    ),
    "The longer leg is the anode; the flat on the rim is on the cathode's side. It needs a "
    "resistor in series: about 330 ohm from 5 V.": (
        "Uzun bacak anottur; kenardaki düz taraf katot tarafıdır. Seri bir direnç ister: "
        "5 V beslemede yaklaşık 330 ohm."
    ),
    "RGB LED 5 mm, common cathode (R K G B)": "RGB LED 5 mm, ortak katot (R K G B)",
    "RGB LED 5 mm, common anode (R A G B)": "RGB LED 5 mm, ortak anot (R A G B)",
    "RGB LED 5 mm, common cathode, Kingbright (R K B G)": (
        "RGB LED 5 mm, ortak katot, Kingbright (R K B G)"
    ),
    "RGB LED 5 mm, common anode, Kingbright (R A B G)": (
        "RGB LED 5 mm, ortak anot, Kingbright (R A B G)"
    ),
    "Red, green and blue in one lens, the three cathodes on the longest leg": (
        "Tek mercekte kırmızı, yeşil ve mavi; üç katot en uzun bacakta"
    ),
    "Red, green and blue in one lens, the three anodes on the longest leg": (
        "Tek mercekte kırmızı, yeşil ve mavi; üç anot en uzun bacakta"
    ),
    "Red, blue and green in one lens, the three cathodes on the longest leg": (
        "Tek mercekte kırmızı, mavi ve yeşil; üç katot en uzun bacakta"
    ),
    "Red, blue and green in one lens, the three anodes on the longest leg": (
        "Tek mercekte kırmızı, mavi ve yeşil; üç anot en uzun bacakta"
    ),
    "Makers do not agree where green and blue go, so before soldering touch a 3 V coin cell "
    "across the longest leg and each of the others (+ to the longest on a common anode, - "
    "on a common cathode) and see which colour lights. Each colour needs its own resistor. "
    "The legs leave the lens 1.27 mm apart: fan them out to the four holes.": (
        "Üreticiler yeşille mavinin yerinde anlaşmıyor; lehimlemeden önce 3 V'luk bir düğme "
        "pili en uzun bacakla diğerlerinin her biri arasına tutun (ortak anotta + en uzun "
        "bacağa, ortak katotta -) ve hangi rengin yandığına bakın. Her renk kendi direncini "
        "ister. Bacaklar mercekten 1.27 mm arayla çıkar: dört deliğe açarak yerleştirin."
    ),
    "SA56-11 7-segment digit (common anode)": "SA56-11 7 segmentli tek hane (ortak anot)",
    "SC56-11 7-segment digit (common cathode)": "SC56-11 7 segmentli tek hane (ortak katot)",
    "CA56-12 4-digit 7-segment (common anode)": (
        "CA56-12 4 haneli 7 segmentli gösterge (ortak anot)"
    ),
    "CC56-12 4-digit 7-segment (common cathode)": (
        "CC56-12 4 haneli 7 segmentli gösterge (ortak katot)"
    ),
    "One 0.56 inch digit, common anode, decimal point at the right": (
        "Tek 0.56 inç hane, ortak anot, ondalık nokta sağda"
    ),
    "One 0.56 inch digit, common cathode, decimal point at the right": (
        "Tek 0.56 inç hane, ortak katot, ondalık nokta sağda"
    ),
    "Four 0.56 inch digits, lit in turn: one common anode per digit": (
        "Dört 0.56 inç hane, sırayla yakılır: her hanenin kendi ortak anodu"
    ),
    "Four 0.56 inch digits, lit in turn: one common cathode per digit": (
        "Dört 0.56 inç hane, sırayla yakılır: her hanenin kendi ortak katodu"
    ),
    "Pin 1 is at the bottom left with the digit upright and its decimal point at the bottom "
    "right. Each segment needs its own resistor. Unbranded 0.56 inch digits are usually "
    "pinned the same, but not always: light one segment with a 3 V coin cell before "
    "soldering.": (
        "Hane dik dururken ve ondalık noktası sağ altta iken 1. pin sol alttadır. Her segment "
        "kendi direncini ister. Markasız 0.56 inç haneler çoğu zaman aynı bağlanır ama her "
        "zaman değil: lehimlemeden önce 3 V'luk bir düğme pille bir segmenti yakıp deneyin."
    ),
    "The digits share their segment pins, so they are lit one at a time, faster than the eye "
    "can follow: a resistor on each segment pin, and each digit's DIG pin switched in turn, "
    "through a transistor, since one digit carries all its segments' current. Unbranded "
    "four-digit displays are usually pinned the same, but not always: light one segment with "
    "a 3 V coin cell before soldering.": (
        "Haneler segment pinlerini paylaşır, bu yüzden gözün seçemeyeceği hızda tek tek "
        "yakılır: her segment pinine bir direnç, ve her hanenin DIG pini sırayla, bir "
        "transistör üzerinden anahtarlanır, çünkü bir hane bütün segmentlerinin akımını "
        "taşır. Markasız dört haneli göstergeler çoğu zaman aynı bağlanır ama her zaman "
        "değil: lehimlemeden önce 3 V'luk bir düğme pille bir segmenti yakıp deneyin."
    ),
    "IR receiver for 38 kHz remote controls, 2.5 to 5.5 V": (
        "38 kHz uzaktan kumandalar için IR alıcı, 2,5 ile 5,5 V arası"
    ),
    "The VS1838B in kits is usually pinned the same, OUT, GND, VCC from the left with the "
    "dome towards you, but not always: check yours.": (
        "Setlerdeki VS1838B'nin dizilişi de çoğu zaman aynıdır, kubbe size bakarken soldan "
        "OUT, GND, VCC; ama her zaman değil: sizinkini kontrol edin."
    ),
    "Accelerometer and gyroscope, three axes each, on I2C": (
        "İvmeölçer ve jiroskop, her biri üç eksenli, I2C üzerinden"
    ),
    "VCC takes 3.3 to 5 V: the board has its own 3.3 V regulator. XDA and XCL are for a "
    "second sensor and can stay open. Sellers give the board as 20 to 21.2 by 15.5 to 16.4 "
    "mm: where the header sits on it and how tall its parts stand are estimates.": (
        "VCC 3.3 ile 5 V arası alır: kartın kendi 3.3 V regülatörü vardır. XDA ve XCL ikinci "
        "bir sensör içindir, boş kalabilir. Satıcılar kartı 20-21.2 x 15.5-16.4 mm verir: "
        "header'ın kart üzerindeki yeri ve parçaların yüksekliği tahmindir."
    ),
    "Quad 2-input NAND gate": "Dörtlü 2 girişli NAND kapısı",
    "Hex inverter": "Altılı evirici",
    "Quad 2-input AND gate": "Dörtlü 2 girişli AND kapısı",
    "Hex inverter with Schmitt-trigger inputs: debouncing, slow edges, oscillators": (
        "Schmitt tetikli girişli altılı evirici: buton sıçraması, yavaş kenarlar, osilatörler"
    ),
    "Quad 2-input OR gate": "Dörtlü 2 girişli OR kapısı",
    "Quad 2-input XOR gate": "Dörtlü 2 girişli XOR kapısı",
    "3-to-8 line decoder, the chosen output goes low": (
        "3'ten 8'e kod çözücü, seçilen çıkış lojik 0'a iner"
    ),
    "8-channel analogue multiplexer: one common pin to any of eight": (
        "8 kanallı analog çoklayıcı: bir ortak pin sekizinden birine"
    ),
    "Quad 2-input NAND gate, 3 to 18 V": "Dörtlü 2 girişli NAND kapısı, 3 ile 18 V arası",
    "Quad 2-input NAND with Schmitt-trigger inputs, 3 to 18 V": (
        "Schmitt tetikli girişli dörtlü 2 girişli NAND, 3 ile 18 V arası"
    ),
    "Dual D flip-flop with set and reset, 3 to 18 V": (
        "Set ve reset girişli ikili D flip-flop, 3 ile 18 V arası"
    ),
    "14-stage binary counter with its own oscillator, 3 to 18 V": (
        "Kendi osilatörü olan 14 kademeli ikili sayıcı, 3 ile 18 V arası"
    ),
    "Quad analogue switch, 3 to 18 V": "Dörtlü analog anahtar, 3 ile 18 V arası",
    "Dual low-noise op-amp for audio, for a split supply": (
        "Ses için düşük gürültülü ikili op-amp, simetrik besleme için"
    ),
    "The classic single op-amp, for a split supply": (
        "Klasik tekli op-amp, simetrik besleme için"
    ),
    "Quad comparator, open-collector outputs, single supply": (
        "Dörtlü karşılaştırıcı, açık kollektör çıkışlı, tek besleme"
    ),
    "Comparator with an open-collector output and its emitter on a pin": (
        "Açık kollektör çıkışlı, emiteri de bir pine çıkarılmış karşılaştırıcı"
    ),
    "Tie every unused input to the supply or to ground: a CMOS input left open picks up "
    "noise, draws current and switches at random.": (
        "Kullanılmayan her girişi beslemeye ya da toprağa bağlayın: boşta bırakılan bir CMOS "
        "girişi gürültü toplar, akım çeker ve rastgele konum değiştirir."
    ),
    "An output is chosen only while G1 is high and G2A and G2B are both low: tie them so, or "
    "every output stays high. The outputs are not in order round the package: Y0 is pin 15 "
    "and Y7 pin 7.": (
        "Bir çıkış yalnızca G1 lojik 1, G2A ile G2B ikisi de lojik 0 iken seçilir: onları "
        "böyle bağlayın, yoksa bütün çıkışlar 1'de kalır. Çıkışlar kılıfın çevresinde sırayla "
        "dizilmez: Y0 15. pin, Y7 7. pindir."
    ),
    "VEE (pin 7) goes to GND unless the signals swing below ground, and E (pin 6) low turns "
    "the switch on. The channels are not in order round the package: A0 is pin 13.": (
        "Sinyaller toprağın altına inmiyorsa VEE (7. pin) GND'ye gider; E (6. pin) lojik 0 "
        "iken seçilen kanal iletime geçer. Kanallar kılıfın çevresinde sırayla dizilmez: A0 "
        "13. pindir."
    ),
    "SET and RESET are active high: tie both low on a flip-flop that should clock. Wire "
    "Q-bar back to D and it divides its clock by two.": (
        "SET ve RESET lojik 1'de etkindir: saatle çalışması gereken flip-flopta ikisini de "
        "0'a bağlayın. Q-bar'ı D'ye geri bağlarsanız saatini ikiye böler."
    ),
    "An RC or a crystal on pins 9, 10 and 11 makes the clock (TI's figures 12 and 13). Q1 "
    "to Q3 and Q11 are not brought out: Q4 is the first output. RESET is active high: tie it "
    "low to count.": (
        "9, 10 ve 11. pinlere bağlanan bir RC ya da kristal saati üretir (TI'nin 12. ve 13. "
        "şekilleri). Q1-Q3 ve Q11 dışarı çıkarılmamıştır: ilk çıkış Q4'tür. RESET lojik 1'de "
        "etkindir: saymak için 0'a bağlayın."
    ),
    "A switch is on while its CTL pin is high. The signal has to stay between VSS and VDD.": (
        "Bir anahtar CTL pini lojik 1 iken iletimdedir. Sinyal VSS ile VDD arasında "
        "kalmalıdır."
    ),
    "Not a rail-to-rail part, and it wants about 10 V across it at least: on one 5 V supply "
    "the LM358 is the one to use.": (
        "Rail-to-rail değildir ve uçları arasında en az 10 V kadar ister: tek 5 V beslemede "
        "kullanılacak olan LM358'dir."
    ),
    "Pins 1 and 5 are for a 10k offset-trim pot and can stay open; pin 8 is not connected. "
    "It needs a split supply of about +-5 V or more.": (
        "1. ve 5. pinler 10k'lık ofset ayar trimpotu içindir, boş kalabilir; 8. pin bağlı "
        "değildir. Yaklaşık +-5 V ya da daha büyük simetrik besleme ister."
    ),
    "VCC is pin 3 and GND pin 12, and OUT1 is pin 2, not 1. The outputs only pull down: "
    "each one needs a pull-up resistor.": (
        "VCC 3. pin, GND 12. pindir; OUT1 de 1. değil 2. pindir. Çıkışlar yalnızca aşağı "
        "çeker: her biri bir pull-up direnci ister."
    ),
    "For a logic output put pin 1 (the emitter) on ground and a pull-up on pin 7 (the "
    "collector). V- is pin 4: on one supply, ground it too.": (
        "Lojik çıkış için 1. pini (emiter) toprağa, 7. pine (kollektör) bir pull-up koyun. "
        "V- 4. pindir: tek beslemede onu da toprağa bağlayın."
    ),
    "16x2 character LCD (HD44780)": "16x2 karakter LCD (HD44780)",
    "Two lines of 16 characters, 5 V, on a 16-pin header": (
        "16 karakterlik iki satır, 5 V, 16 pinli header üzerinde"
    ),
    "VO sets the contrast: a 10k pot across VDD and VSS with its wiper on VO. A and K are "
    "the backlight. A few modules put those two before pin 1: count from the pin marked 1. "
    "On an I2C backpack it is a different part.": (
        "Kontrastı VO ayarlar: VDD ile VSS arasına bir 10k pot, orta ucu VO'ya. A ve K arka "
        "ışıktır. Bazı modüller bu ikisini 1 numaralı pinden önceye koyar: 1 yazan pinden "
        "sayın. I2C sırt kartlı olanı başka bir parçadır."
    ),
    "Displays": "Ekranlar",
    "Ultrasonic distance sensor, 2 cm to 4 m, 5 V; stands on its edge": (
        "Ultrasonik mesafe sensörü, 2 cm ile 4 m arası, 5 V; kenarı üzerinde dik durur"
    ),
    "ECHO is a 5 V output: put a divider between it and a 3.3 V pin. The transducers "
    "stand 12 mm out in front of the board and its header behind it, as photographs of one "
    "show; how high the board stands on its pins is an estimate.": (
        "ECHO 5 V'luk bir çıkıştır: 3,3 V'luk bir pine bağlamadan önce araya bir bölücü "
        "koyun. Bir kartın fotoğraflarında görüldüğü gibi dönüştürücüler kartın 12 mm "
        "önünde, header'ı ise arkasında durur; kartın pinlerinin üzerinde ne kadar "
        "yüksekte durduğu tahmindir."
    ),
    "128 x 64 OLED on I2C, pins printed GND, VCC, SCL, SDA": (
        "I2C ile bağlanan 128 × 64 OLED, pinlerinde GND, VCC, SCL, SDA yazar"
    ),
    "128 x 64 OLED on I2C, pins printed VCC, GND, SCL, SDA": (
        "I2C ile bağlanan 128 × 64 OLED, pinlerinde VCC, GND, SCL, SDA yazar"
    ),
    "Read the four names printed on yours: this board is sold with VCC and GND either way "
    "round, and the wrong way round kills it. Choose the entry with your order. The header "
    "is 1.45 mm in from the board's edge, measured on a photograph of one; how tall it "
    "stands in its socket is an estimate.": (
        "Sizinkinin üzerinde yazan dört adı okuyun: bu kart VCC ve GND iki sırayla da "
        "satılır ve ters bağlanırsa yanar. Sizinkiyle aynı sıradaki girişi seçin. Header "
        "kartın kenarından 1,45 mm içeridedir, bir kartın fotoğrafından ölçüldü; soketinde ne "
        "kadar yükseldiği tahmindir."
    ),
    "Pololu DRV8833 carrier": "Pololu DRV8833 taşıyıcı kartı",
    "Two DC motors or one stepper, 2.7 to 10.8 V, 1.2 A per channel (2 A peak), rows "
    "10.16 mm apart": (
        "İki DC motor ya da bir step motor, 2,7 ile 10,8 V arası, kanal başına 1,2 A (tepe "
        "2 A), sıralar arası 10,16 mm"
    ),
    "VMM is the motor supply after the board's reverse-protection MOSFET: an output, not a "
    "second input. AISEN and BISEN are joined to GND on the board until the traces are cut "
    "for sense resistors. The height of what is on the board is an estimate, and so is its "
    "colour; the pins, the rows and the board outline are measured.": (
        "VMM, kartın ters kutup koruma MOSFET'inden sonraki motor beslemesidir: ikinci bir "
        "giriş değil, bir çıkıştır. AISEN ve BISEN, akım algılama dirençleri için yollar "
        "kesilene kadar kart üzerinde GND'ye bağlıdır. Kartın üzerindekilerin yüksekliği "
        "ve rengi tahmindir; pinler, sıralar ve kart çevresi ölçülmüştür."
    ),
    "SparkFun TB6612FNG motor driver": "SparkFun TB6612FNG motor sürücüsü",
    "Two DC motors, 2.5 to 13.5 V, 1 A each (3.2 A peak), rows 15.24 mm apart": (
        "İki DC motor, 2,5 ile 13,5 V arası, motor başına 1 A (tepe 3,2 A), sıralar arası "
        "15,24 mm"
    ),
    "STBY is pulled low inside the chip: drive it high or neither motor turns. VCC is the "
    "logic's supply, 2.7 to 5.5 V; VM is the motors'. The height of what is on the board is "
    "an estimate, and so is its colour; the pins, the rows and the board outline are "
    "measured.": (
        "STBY entegrenin içinde aşağı çekilidir: yükseğe sürün, yoksa iki motor da dönmez. "
        "VCC lojiğin beslemesidir, 2,7 ile 5,5 V arası; VM motorlarınkidir. Kartın "
        "üzerindekilerin yüksekliği ve rengi tahmindir; pinler, sıralar ve kart çevresi "
        "ölçülmüştür."
    ),
    "nRF24L01+ module": "nRF24L01+ modülü",
    "2.4 GHz radio on SPI, 1.9 to 3.6 V, the board with its antenna printed on it": (
        "SPI ile bağlanan 2,4 GHz telsiz, 1,9 ile 3,6 V arası, anteni kartına basılı olan"
    ),
    "VCC is 3.3 V at most -- 5 V kills it -- though its inputs take 5 V logic. The version "
    "with an amplifier and an antenna socket has these pins on a longer board. Its crystal "
    "stands 3.6 mm, the tallest thing on it.": (
        "VCC en çok 3,3 V'tur -- 5 V onu yakar -- ama girişleri 5 V lojiği kaldırır. "
        "Yükselteçli ve anten soketli sürümünde aynı pinler daha uzun bir karttadır. "
        "Kristali 3,6 mm yükselir, üzerindeki en uzun parça odur."
    ),
    "ESP-01 (ESP8266 module)": "ESP-01 (ESP8266 modülü)",
    "Adafruit INA219 (original, 4 holes)": "Adafruit INA219 (orijinal, 4 delikli)",
    "Wi-Fi on an ESP8266, 3.3 V: serial, two GPIOs, enable and reset on 8 pins": (
        "ESP8266 ile Wi-Fi, 3,3 V: 8 pinde seri port, iki GPIO, etkinleştirme ve reset"
    ),
    "3.3 V only. EN (CH_PD) must be high for it to run, and IO0 low as it starts puts it "
    "in download mode (Ai-Thinker's table 2.3). The ESP-01S is pinned the same, on another "
    "board: it is drawn as the block.": (
        "Yalnızca 3,3 V. Çalışması için EN (CH_PD) yüksekte olmalıdır; açılırken IO0 "
        "düşükteyse yükleme kipine geçer (Ai-Thinker'ın tablo 2.3'ü). ESP-01S'in dizilişi "
        "de aynıdır ama kartı başkadır: düz bir blok olarak çizilir."
    ),
    "LM2596 buck module": "LM2596 voltaj düşürücü modül",
    "Step-down converter on the LM2596: up to 40 V in, from 1.25 V out, set by its "
    "trimmer": (
        "LM2596'lı voltaj düşürücü: girişte en çok 40 V, çıkışta 1,25 V'tan başlayarak, "
        "trimpotuyla ayarlanır"
    ),
    "Its pads are 39.5 x 17.15 mm apart, not on the 2.54 mm grid: stand it on pins bent "
    "about 0.6 mm to the holes drawn, or wire it. Set the output with the trimmer before "
    "anything is connected to it; its input capacitor's rating, often 35 V, is its real "
    "limit.": (
        "Pedleri arası 39,5 × 17,15 mm'dir, 2,54 mm ızgarada değildir: çizilen deliklere "
        "yaklaşık 0,6 mm bükülen pinlerin üzerine oturtun ya da kabloyla bağlayın. Çıkışa "
        "bir şey bağlamadan önce gerilimi trimpotla ayarlayın; asıl sınırı giriş "
        "kondansatörünün değeridir, çoğu zaman 35 V."
    ),
    "Songle SRD-05VDC-SL-C relay": "Songle SRD-05VDC-SL-C röle",
    "Songle SRD-12VDC-SL-C relay": "Songle SRD-12VDC-SL-C röle",
    "SPDT relay, 12 V coil of 400 ohm, contacts 10 A at 125 V AC": (
        "SPDT röle, 400 ohm'luk 12 V bobin, kontaklar 125 V AC'de 10 A"
    ),
    "SPDT relay, 5 V coil of 70 ohm, contacts 10 A at 125 V AC": (
        "SPDT röle, 70 ohm'luk 5 V bobin, kontaklar 125 V AC'de 10 A"
    ),
    "Its legs are off the 2.54 mm grid and bend to the holes drawn: about 0.5 mm for COM, "
    "0.9 mm for a coil leg, 1.1 mm for a contact leg. With the coil off, NC reads shut to "
    "COM: check that with a meter before soldering.": (
        "Bacakları 2,54 mm ızgarada değildir, çizilen deliklere bükülür: COM yaklaşık "
        "0,5 mm, bir bobin bacağı 0,9 mm, bir kontak bacağı 1,1 mm. Bobin enerjisizken NC "
        "COM'a kısa devre okur: lehimlemeden önce bunu multimetreyle doğrulayın."
    ),
    "9 V battery clip": "9 V pil klipsi",
    "PP3 snap on two leads, for a 9 V battery": "İki kablolu PP3 başlığı, 9 V pil için",
    "Red is +. If both leads of yours are one colour, find + with a meter on the battery "
    "before soldering.": (
        "Kırmızı kablo +'dır. Sizinkinin iki kablosu da aynı renkteyse, lehimlemeden önce "
        "pil takılıyken +'yı multimetreyle bulun."
    ),
    "AA battery holder": "AA pil yuvası",
    "Two to four AA or AAA cells in series, on two leads": (
        "Seri bağlı iki ile dört AA ya da AAA pil, iki kablolu"
    ),
    "Red is + and black is -. With no colours, measure across it with the cells in.": (
        "Kırmızı +, siyah -'dir. Renk yoksa piller takılıyken uçlarını ölçün."
    ),
    "DC barrel jack 5.5 x 2.1 mm, panel mount": "DC jak 5,5 × 2,1 mm, panele takılan",
    "On the case, wired to the board from its centre pin and its sleeve": (
        "Kutunun üzerinde durur; karta merkez piminden ve gövdesinden kabloyla bağlanır"
    ),
    "Centre-positive is the usual way and not a rule: the symbol on the adapter says "
    "which. A third lug, if yours has one, is a switch and stays unconnected here.": (
        "Merkezin + olması en yaygın olanıdır ama kural değildir: adaptörün üzerindeki "
        "sembol hangisi olduğunu söyler. Sizinkinde üçüncü bir uç varsa o bir anahtardır "
        "ve burada boş kalır."
    ),
    "Power in, 2-way screw terminal": "Güç girişi, 2'li klemens",
    "Two wires in under screws, named + and -": "Vidayla sıkılan iki kablo girişi, + ve - adlı",
    "Print + and - beside it: the terminal itself does not say.": (
        "Yanına + ve - yazın: klemensin kendisi bunu söylemez."
    ),
    "Power in, 2-pin header": "Güç girişi, 2 pinli header",
    "A power lead. Its cable plugs into this 2-pin header: + - from pin 1": (
        "Bir güç kablosu. Bu 2 pinli header'a takılır: 1. pinden + -"
    ),
    "Print + and - beside it: the header itself does not say.": (
        "Yanına + ve - yazın: header'ın kendisi bunu söylemez."
    ),
    "Hobby servo (on a header)": "Hobi servosu (header üzerinde)",
    "KY-023 joystick module (on a header)": "KY-023 joystick modülü (header üzerinde)",
    "Two-axis joystick that is also a switch when pressed. Its cable plugs into this 5-pin "
    "header: GND +5V VRx VRy SW from pin 1": (
        "Bastırınca anahtar da olan iki eksenli joystick. Kablosu bu 5 pinli header'a takılır: "
        "1. pinden GND +5V VRx VRy SW"
    ),
    "Feed +5V from the board's own logic supply: on a 3.3 V board, 3.3 V, or the two pots read "
    "past the top of its ADC. Match each lead to the name printed beside the module's pins, "
    "not to its place: sellers' boards are not all wired in the same order.": (
        "+5V'u kartın kendi mantık beslemesinden verin: 3,3 V'luk bir kartta 3,3 V; yoksa iki "
        "potansiyometre ADC'nin üst sınırını aşar. Her kabloyu yerine göre değil, modülün "
        "pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "KY-040 rotary encoder module (on a header)": "KY-040 döner enkoder modülü (header üzerinde)",
    "Rotary encoder that is also a switch when pressed. Its cable plugs into this 5-pin "
    "header: CLK DT SW + GND from pin 1": (
        "Bastırınca anahtar da olan döner enkoder. Kablosu bu 5 pinli header'a takılır: 1. "
        "pinden CLK DT SW + GND"
    ),
    "+ only feeds its pull-ups: give it the board's logic voltage. Match each lead to the name "
    "printed beside the module's pins, not to its place: sellers' boards are not all wired in "
    "the same order.": (
        "+ yalnızca pull-up dirençlerini besler: kartın mantık gerilimini verin. Her kabloyu "
        "yerine göre değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların "
        "kartları aynı sırayla bağlanmamıştır."
    ),
    "LCD1602 with I2C backpack (on a header)": "I2C arka kartlı LCD1602 (header üzerinde)",
    "16x2 character LCD driven over I2C by a PCF8574. Its cable plugs into this 4-pin header: "
    "GND VCC SDA SCL from pin 1": (
        "Bir PCF8574 ile I2C üzerinden sürülen 16x2 karakter LCD. Kablosu bu 4 pinli header'a "
        "takılır: 1. pinden GND VCC SDA SCL"
    ),
    "It answers at 0x27 with a PCF8574 or 0x3F with a PCF8574A: try both if it stays blank, and "
    "turn its contrast trimmer before deciding it is dead. Match each lead to the name printed "
    "beside the module's pins, not to its place: sellers' boards are not all wired in the same "
    "order.": (
        "PCF8574 ile 0x27'de, PCF8574A ile 0x3F'de yanıt verir: ekran boş kalırsa ikisini de "
        "deneyin ve bozuk olduğuna karar vermeden önce kontrast trimpotunu çevirin. Her kabloyu "
        "yerine göre değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların "
        "kartları aynı sırayla bağlanmamıştır."
    ),
    "MAX7219 8x8 LED matrix module (on a header)": "MAX7219 8x8 LED matris modülü (header üzerinde)",
    "8x8 LED matrix driven by a MAX7219. Its cable plugs into this 5-pin header: VCC GND DIN CS "
    "CLK from pin 1": (
        "Bir MAX7219 ile sürülen 8x8 LED matris. Kablosu bu 5 pinli header'a takılır: 1. pinden "
        "VCC GND DIN CS CLK"
    ),
    "It has a header at each end: the cable goes on the one marked DIN, the other is its output "
    "to the next matrix. Match each lead to the name printed beside the module's pins, not to "
    "its place: sellers' boards are not all wired in the same order.": (
        "İki ucunda da bir header vardır: kablo DIN yazan uca takılır, diğeri sonraki matrise "
        "giden çıkışıdır. Her kabloyu yerine göre değil, modülün pinlerinin yanında yazan ada "
        "göre bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "TM1637 4-digit display module (on a header)": "TM1637 4 haneli gösterge modülü (header üzerinde)",
    "Four-digit 7-segment display driven by a TM1637. Its cable plugs into this 4-pin header: "
    "CLK DIO VCC GND from pin 1": (
        "Bir TM1637 ile sürülen dört haneli 7 segment gösterge. Kablosu bu 4 pinli header'a "
        "takılır: 1. pinden CLK DIO VCC GND"
    ),
    "CLK and DIO are not interchangeable. Match each lead to the name printed beside the "
    "module's pins, not to its place: sellers' boards are not all wired in the same order.": (
        "CLK ve DIO birbirinin yerine kullanılamaz. Her kabloyu yerine göre değil, modülün "
        "pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "WS2812B LED strip (on a header)": "WS2812B LED şerit (header üzerinde)",
    "Addressable RGB LED strip or ring. Its cable plugs into this 3-pin header: +5V DIN GND from "
    "pin 1": (
        "Adreslenebilir RGB LED şerit ya da halka. Kablosu bu 3 pinli header'a takılır: 1. "
        "pinden +5V DIN GND"
    ),
    "Its cable goes on the end its arrows point away from, DIN in. Adafruit puts a 300 to 500 "
    "ohm resistor in DIN and 1000 uF across +5V and GND at the strip. Match each lead to the "
    "name printed beside the module's pins, not to its place: sellers' boards are not all wired "
    "in the same order.": (
        "Kablo, okların uzaklaştığı uca takılır: DIN girişi. Adafruit DIN'e 300-500 ohm bir "
        "direnç, şeridin ucunda +5V ile GND arasına 1000 uF koyar. Her kabloyu yerine göre "
        "değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı "
        "sırayla bağlanmamıştır."
    ),
    "DS3231 RTC module, ZS-042 (on a header)": "DS3231 RTC modülü, ZS-042 (header üzerinde)",
    "Real-time clock with a coin cell, on I2C. Its cable plugs into this 6-pin header: GND VCC "
    "SDA SCL SQW 32K from pin 1": (
        "Düğme pilli, I2C'li gerçek zamanlı saat. Kablosu bu 6 pinli header'a takılır: 1. "
        "pinden GND VCC SDA SCL SQW 32K"
    ),
    "Many ZS-042 boards charge their coin cell: fit an LIR2032, or take off the charging diode "
    "before fitting a CR2032. Match each lead to the name printed beside the module's pins, not "
    "to its place: sellers' boards are not all wired in the same order.": (
        "Birçok ZS-042 kartı düğme pilini şarj eder: LIR2032 takın ya da CR2032 takmadan önce "
        "şarj diyotunu sökün. Her kabloyu yerine göre değil, modülün pinlerinin yanında yazan "
        "ada göre bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "HC-05 Bluetooth module, ZS-040 (on a header)": (
        "HC-05 Bluetooth modülü, ZS-040 (header üzerinde)"
    ),
    "Bluetooth serial module, master or slave, 3.3 V logic. Its cable plugs into this "
    "6-pin header: STATE RXD TXD GND VCC EN from pin 1": (
        "Ana ya da bağımlı çalışan, 3,3 V mantıklı Bluetooth seri modülü. Kablosu bu 6 pinli "
        "header'a takılır: 1. pinden STATE RXD TXD GND VCC EN"
    ),
    "TXD goes to the controller's RX and RXD to its TX. RXD is 3.3 V logic: from a 5 V "
    "board's TX, bring it down through a divider of 1k and 2k. EN and STATE can be left "
    "unwired. Match each lead to the name printed beside the module's pins, not to its "
    "place: sellers' boards are not all wired in the same order.": (
        "TXD denetleyicinin RX'ine, RXD de TX'ine gider. RXD 3,3 V mantıktır: 5 V'luk bir "
        "kartın TX'inden 1k ve 2k'lık bir bölücüyle düşürün. EN ve STATE boş bırakılabilir. "
        "Her kabloyu yerine göre değil, modülün pinlerinin yanında yazan ada göre bağlayın: "
        "satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "HC-06 Bluetooth module (on a header)": (
        "HC-06 Bluetooth modülü (header üzerinde)"
    ),
    "Bluetooth serial module, slave only, 3.3 V logic. Its cable plugs into this 4-pin "
    "header: VCC GND TXD RXD from pin 1": (
        "Yalnızca bağımlı çalışan, 3,3 V mantıklı Bluetooth seri modülü. Kablosu bu 4 pinli "
        "header'a takılır: 1. pinden VCC GND TXD RXD"
    ),
    "TXD goes to the controller's RX and RXD to its TX. RXD is 3.3 V logic: from a 5 V "
    "board's TX, bring it down through a divider of 1k and 2k. Match each lead to the "
    "name printed beside the module's pins, not to its place: sellers' boards are not all "
    "wired in the same order.": (
        "TXD denetleyicinin RX'ine, RXD de TX'ine gider. RXD 3,3 V mantıktır: 5 V'luk bir "
        "kartın TX'inden 1k ve 2k'lık bir bölücüyle düşürün. Her kabloyu yerine göre değil, "
        "modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı "
        "sırayla bağlanmamıştır."
    ),
    "MAX485 RS-485 module (on a header)": (
        "MAX485 RS-485 modülü (header üzerinde)"
    ),
    "TTL to RS-485 transceiver module, 5 V. Its cable plugs into this 8-pin header: RO RE "
    "DE DI VCC B A GND from pin 1": (
        "5 V'luk TTL'den RS-485'e alıcı-verici modülü. Kablosu bu 8 pinli header'a takılır: "
        "1. pinden RO RE DE DI VCC B A GND"
    ),
    "RE is on when low and DE when high: join them and drive both from one pin to switch "
    "between listening and sending. A and B are the bus, on the module's screw terminal "
    "too: A goes to A and B to B along it. Match each lead to the name printed beside the "
    "module's pins, not to its place: sellers' boards are not all wired in the same "
    "order.": (
        "RE düşükken, DE yüksekken açıktır: ikisini birleştirip tek pinden sürün, böylece "
        "dinleme ile gönderme arasında geçiş yapılır. A ve B hattır, modülün vidalı "
        "klemensinde de vardır: hat boyunca A A'ya, B B'ye gider. Her kabloyu yerine göre "
        "değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı "
        "sırayla bağlanmamıştır."
    ),
    "GY-BMP280 pressure sensor module (on a header)": (
        "GY-BMP280 basınç sensörü modülü (header üzerinde)"
    ),
    "BMP280 pressure and temperature sensor, I2C or SPI, 3.3 V only. Its cable plugs into "
    "this 6-pin header: VCC GND SCL SDA CSB SDO from pin 1": (
        "I2C ya da SPI ile çalışan, yalnızca 3,3 V'luk BMP280 basınç ve sıcaklık sensörü. "
        "Kablosu bu 6 pinli header'a takılır: 1. pinden VCC GND SCL SDA CSB SDO"
    ),
    "It has no regulator: 3.3 V only. For I2C leave CSB unwired; its address is 0x76 with "
    "SDO unwired, 0x77 with SDO to VCC. Match each lead to the name printed beside the "
    "module's pins, not to its place: sellers' boards are not all wired in the same "
    "order.": (
        "Regülatörü yoktur: yalnızca 3,3 V. I2C için CSB'yi boş bırakın; adresi SDO boşken "
        "0x76, SDO VCC'ye bağlıyken 0x77'dir. Her kabloyu yerine göre değil, modülün "
        "pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "GY-BME280 sensor module, 4-pin (on a header)": (
        "GY-BME280 sensör modülü, 4 pinli (header üzerinde)"
    ),
    "BME280 pressure, humidity and temperature sensor on I2C, with a 3.3 V regulator for "
    "3.3 or 5 V. Its cable plugs into this 4-pin header: VIN GND SCL SDA from pin 1": (
        "I2C ile çalışan BME280 basınç, nem ve sıcaklık sensörü; 3,3 V regülatörü sayesinde "
        "3,3 ya da 5 V ile beslenir. Kablosu bu 4 pinli header'a takılır: 1. pinden VIN GND "
        "SCL SDA"
    ),
    "The six-pin GY-BME280-3.3 is another board, with no regulator: check which one you "
    "have before giving it 5 V. Match each lead to the name printed beside the module's "
    "pins, not to its place: sellers' boards are not all wired in the same order.": (
        "Altı pinli GY-BME280-3.3 başka bir karttır ve regülatörü yoktur: 5 V vermeden önce "
        "hangisine sahip olduğunuzu kontrol edin. Her kabloyu yerine göre değil, modülün "
        "pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "GY-BME280-3.3 sensor module, 6-pin (on a header)": (
        "GY-BME280-3.3 sensör modülü, 6 pinli (header üzerinde)"
    ),
    "BME280 pressure, humidity and temperature sensor, I2C or SPI, 3.3 V only. Its cable "
    "plugs into this 6-pin header: VCC GND SCL SDA CSB SDO from pin 1": (
        "I2C ya da SPI ile çalışan, yalnızca 3,3 V'luk BME280 basınç, nem ve sıcaklık "
        "sensörü. Kablosu bu 6 pinli header'a takılır: 1. pinden VCC GND SCL SDA CSB SDO"
    ),
    "It has no regulator: 3.3 V only. For I2C tie CSB to VCC; its address is 0x76 with "
    "SDO to GND, 0x77 with SDO to VCC. Match each lead to the name printed beside the "
    "module's pins, not to its place: sellers' boards are not all wired in the same "
    "order.": (
        "Regülatörü yoktur: yalnızca 3,3 V. I2C için CSB'yi VCC'ye bağlayın; adresi SDO "
        "GND'ye bağlıyken 0x76, VCC'ye bağlıyken 0x77'dir. Her kabloyu yerine göre değil, "
        "modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı "
        "sırayla bağlanmamıştır."
    ),
    "1-channel 5 V relay module (on a header)": (
        "1 kanallı 5 V röle modülü (header üzerinde)"
    ),
    "A Songle SRD-05VDC relay and its driver on a small module. Its cable plugs into this 3-pin "
    "header: VCC GND IN from pin 1": (
        "Küçük bir modül üzerinde Songle SRD-05VDC rölesi ve sürücüsü. Kablosu bu 3 pinli "
        "header'a takılır: 1. pinden VCC GND IN"
    ),
    "Most of these boards switch on when IN is pulled LOW. What the relay switches goes "
    "to the module's own screw terminals, not to the perfboard. Mains there needs proper "
    "insulation and spacing and is not a perfboard job. Match each lead to the name "
    "printed beside the module's pins, not to its place: sellers' boards are not all "
    "wired in the same order.": (
        "Bu kartların çoğu IN düşük çekildiğinde çeker. Rölenin anahtarladığı hat perfboard'a "
        "değil, modülün kendi vidalı klemenslerine gider. Orada şebeke gerilimi uygun yalıtım "
        "ve aralık ister; bu bir perfboard işi değildir. Her kabloyu yerine göre "
        "değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı "
        "sırayla bağlanmamıştır."
    ),
    "A 2.50 mm wire-to-board header for a crimped JST XH plug, from above. On a 2.54 mm "
    "board it goes in up to 4 pins": (
        "Sıkma uçlu JST XH fiş için 2,50 mm aralıklı, kablo-kart başlığı; fiş üstten "
        "takılır. 2,54 mm'lik bir karta 4 pine kadar oturur"
    ),
    "A 2.50 mm wire-to-board header for a crimped JST XH plug, from the side. On a 2.54 "
    "mm board it goes in up to 4 pins": (
        "Sıkma uçlu JST XH fiş için 2,50 mm aralıklı, kablo-kart başlığı; fiş yandan "
        "takılır. 2,54 mm'lik bir karta 4 pine kadar oturur"
    ),
    "Its pins are 2.50 mm apart and the holes 2.54: press it in square and solder the "
    "two end pins first. The plug goes in one way round, so turned half round its first "
    "wire lands on the last pin.": (
        "Pinleri 2,50 mm, delikler 2,54 mm arayla: dik bastırın ve önce iki uçtaki pini "
        "lehimleyin. Fiş tek yönde takılır, bu yüzden ters çevrilirse ilk kablosu son pine "
        "gelir."
    ),
    "A 2.54 mm wire-to-board header for a crimped Molex KK 254 or KF2510 plug, from "
    "above": (
        "Sıkma uçlu Molex KK 254 ya da KF2510 fiş için 2,54 mm aralıklı, kablo-kart "
        "başlığı; fiş üstten takılır"
    ),
    "KF2510 headers are KK 254 clones and take the same plugs. The plug goes in one way "
    "round, so turned half round its first wire lands on the last pin.": (
        "KF2510 başlıklar KK 254 kopyalarıdır ve aynı fişleri alır. Fiş tek yönde takılır, "
        "bu yüzden ters çevrilirse ilk kablosu son pine gelir."
    ),
    "JST XH connector, 2-pin, top entry": (
        "JST XH konnektör, 2 pinli, üstten girişli"
    ),
    "JST XH connector, 2-pin, side entry": (
        "JST XH konnektör, 2 pinli, yandan girişli"
    ),
    "JST XH connector, 3-pin, top entry": (
        "JST XH konnektör, 3 pinli, üstten girişli"
    ),
    "JST XH connector, 3-pin, side entry": (
        "JST XH konnektör, 3 pinli, yandan girişli"
    ),
    "JST XH connector, 4-pin, top entry": (
        "JST XH konnektör, 4 pinli, üstten girişli"
    ),
    "JST XH connector, 4-pin, side entry": (
        "JST XH konnektör, 4 pinli, yandan girişli"
    ),
    "Molex KK 254 connector, 2-pin": (
        "Molex KK 254 konnektör, 2 pinli"
    ),
    "Molex KK 254 connector, 3-pin": (
        "Molex KK 254 konnektör, 3 pinli"
    ),
    "Molex KK 254 connector, 4-pin": (
        "Molex KK 254 konnektör, 4 pinli"
    ),
    "Molex KK 254 connector, 5-pin": (
        "Molex KK 254 konnektör, 5 pinli"
    ),
    "Molex KK 254 connector, 6-pin": (
        "Molex KK 254 konnektör, 6 pinli"
    ),
    "Molex KK 254 connector, 8-pin": (
        "Molex KK 254 konnektör, 8 pinli"
    ),
    "JST PH is 2.0 mm a pin and does not go into a 0.1 in board's holes. A JST XH (2.5 "
    "mm) does, up to 4 pins.": (
        "JST PH 2,0 mm aralıklıdır ve 0,1 inçlik bir kartın deliklerine oturmaz. JST XH "
        "(2,5 mm) 4 pine kadar oturur."
    ),
    "JST ZH is 1.5 mm a pin and does not go into a 0.1 in board's holes. A JST XH (2.5 "
    "mm) does, up to 4 pins.": (
        "JST ZH 1,5 mm aralıklıdır ve 0,1 inçlik bir kartın deliklerine oturmaz. JST XH "
        "(2,5 mm) 4 pine kadar oturur."
    ),
    "JST SH is 1.0 mm a pin, a surface-mount part that does not go into a 0.1 in "
    "board's holes. A JST XH (2.5 mm) does, up to 4 pins.": (
        "JST SH 1,0 mm aralıklı, yüzey montajlı bir parçadır ve 0,1 inçlik bir kartın "
        "deliklerine oturmaz. JST XH (2,5 mm) 4 pine kadar oturur."
    ),
    "JST VH is 3.96 mm a pin, which no row of 0.1 in holes matches. For power, a 5.08 "
    "mm screw terminal or a JST XH does the job.": (
        "JST VH 3,96 mm aralıklıdır; 0,1 inçlik deliklerin hiçbir sırası buna denk gelmez. "
        "Güç için 5,08 mm'lik bir vidalı klemens ya da JST XH aynı işi görür."
    ),
    "Micro SD card module (on a header)": "Micro SD kart modülü (header üzerinde)",
    "Micro SD card socket on SPI, with a 3.3 V regulator. Its cable plugs into this 6-pin "
    "header: GND VCC MISO MOSI SCK CS from pin 1": (
        "SPI üzerinden çalışan, 3,3 V regülatörlü micro SD kart yuvası. Kablosu bu 6 pinli "
        "header'a takılır: 1. pinden GND VCC MISO MOSI SCK CS"
    ),
    "Its MISO is driven even when CS is high, so it shares the SPI bus badly with other parts. "
    "Match each lead to the name printed beside the module's pins, not to its place: sellers' "
    "boards are not all wired in the same order.": (
        "MISO'su CS yüksekken bile sürülür; bu yüzden SPI hattını başka parçalarla iyi "
        "paylaşamaz. Her kabloyu yerine göre değil, modülün pinlerinin yanında yazan ada göre "
        "bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "A hobby servo such as the SG90. Its cable plugs into this 3-pin header: PWM + - from "
    "pin 1": (
        "SG90 gibi bir hobi servosu. Kablosu bu 3 pinli header'a takılır: 1. pinden PWM + -"
    ),
    "Turned round, PWM and - swap and the servo does nothing. Feed it from its own 5 V, "
    "not from a board's regulator pin.": (
        "Ters takılırsa PWM ile - yer değiştirir ve servo hiçbir şey yapmaz. Servoyu bir "
        "kartın regülatör pininden değil, kendi 5 V'undan besleyin."
    ),
    "Active buzzer 12 mm": "Aktif buzzer 12 mm",
    "Beeps on DC, 12 mm across and 9.5 mm tall, legs 7.6 mm apart": (
        "DC verilince öter, 12 mm çapında ve 9,5 mm yüksekliğinde, bacaklar arası 7,6 mm"
    ),
    "An ACTIVE buzzer is sealed underneath; a PASSIVE one shows its board there and "
    "needs a tone, not DC. The longer leg, under the + on top, is +.": (
        "AKTİF buzzer'ın altı kapalıdır; PASİF olanın altında kartı görünür ve DC değil "
        "bir ton ister. Üstteki + işaretinin altındaki uzun bacak +'dır."
    ),
    "Momentary push button, legs 6.5 x 4.5 mm": (
        "Basılı tutulduğunda kapanan buton, bacaklar arası 6,5 × 4,5 mm"
    ),
    "Momentary push button, legs 12.5 x 5.0 mm": (
        "Basılı tutulduğunda kapanan buton, bacaklar arası 12,5 × 5,0 mm"
    ),
    "The two legs on one side are the switched pair; the two straight across are "
    "one strip. A meter on continuity says which: across reads shut before the "
    "button is pressed.": (
        "Aynı yandaki iki bacak butonun açıp kapadığı çifttir; tam karşıdaki iki bacak "
        "tek bir metal şerittir. Süreklilik ölçen bir multimetre hangisi olduğunu "
        "söyler: karşılıklı bacaklar butona basmadan da kısa devre okur."
    ),
    "Dual op-amp, single supply": "Çift op-amp, tek besleme",
    "Dual comparator, open-collector outputs": "Çift karşılaştırıcı, açık kolektör çıkışlı",
    "High-speed optocoupler, 10 Mbit/s": "Yüksek hızlı optokuplör, 10 Mbit/s",
    "Optocoupler, transistor output": "Optokuplör, transistör çıkışlı",
    "CAN transceiver, 5 V, 1 Mbit/s": "CAN alıcı-verici, 5 V, 1 Mbit/s",
    "RS-485 transceiver, half duplex, 5 V": "RS-485 alıcı-verici, yarı çift yönlü, 5 V",
    "8-bit shift register, latched outputs": "8 bit kaydırmalı yazmaç, mandallı çıkışlar",
    "Seven Darlington sinks, 50 V, 500 mA, with flyback diodes": (
        "Yedi Darlington akım çekici, 50 V, 500 mA, serbest geçiş diyotlu"
    ),
    "Dual H-bridge, 600 mA, with clamp diodes": "Çift H köprüsü, 600 mA, kırpma diyotlu",
    "The four GND pins are also its heatsink: solder them to a copper area.": (
        "Dört GND pini aynı zamanda soğutucusudur: bir bakır alana lehimleyin."
    ),
    "CAN controller, SPI": "CAN denetleyici, SPI",
    "Octal bus transceiver (74HCT245 for 3.3 V in, 5 V out)": (
        "Sekizli veri yolu alıcı-vericisi (3,3 V giriş, 5 V çıkış için 74HCT245)"
    ),
    "8-bit AVR, the Arduino Uno's": "8 bit AVR, Arduino Uno'nunki",
    "Low-dropout regulator, +3.3 V, 800 mA": "Düşük düşümlü (LDO) regülatör, +3,3 V, 800 mA",
    "NOT pinned like a 7805: GND, OUT, IN, and the tab is the output. It needs 10 uF on "
    "the output to stay stable. The LM1117T-3.3 is pinned the same.": (
        "Bacak dizilişi 7805 gibi DEĞİL: GND, OUT, IN; tırnak çıkışa bağlıdır. Kararlı "
        "kalması için çıkışta 10 µF ister. LM1117T-3.3'ün dizilişi de aynıdır."
    ),
    "Dual JFET-input op-amp, low noise, for a split supply": (
        "Çift JFET girişli op-amp, düşük gürültülü, simetrik besleme için"
    ),
    "Not a rail-to-rail part: on one low supply its inputs and its output cannot come "
    "near either rail. The LM358 is the single-supply one.": (
        "Besleme hatlarına kadar çalışan (rail-to-rail) bir parça değildir: tek ve düşük "
        "bir beslemede girişleri de çıkışı da iki hatta da yaklaşamaz. Tek besleme için "
        "olanı LM358'dir."
    ),
    "Audio power amplifier, 0.3 to 1 W, gain 20 to 200": (
        "Ses güç yükselteci, 0,3 ile 1 W arası, kazanç 20 ile 200 arası"
    ),
    "Pins 1 and 8 are both GAIN: left open the gain is 20, and 10 uF between them makes "
    "it 200.": (
        "1 ve 8 numaralı pinlerin ikisi de GAIN'dir: boş bırakılırsa kazanç 20'dir, "
        "aralarına 10 µF konursa 200 olur."
    ),
    "8-bit AVR, 8 kB flash, five I/O pins": "8 bit AVR, 8 kB flash, beş G/Ç pini",
    "Real-time clock, I2C, with battery backup, 5 V": "Gerçek zamanlı saat, I2C, pil yedekli, 5 V",
    "X1 and X2 take a 32.768 kHz crystal made for 12.5 pF. With no coin cell, VBAT goes "
    "to GND.": (
        "X1 ve X2'ye 12,5 pF için yapılmış 32,768 kHz'lik bir kristal bağlanır. Düğme pil "
        "yoksa VBAT GND'ye bağlanır."
    ),
    "Quad op-amp, single supply": "Dörtlü op-amp, tek besleme",
    "VCC is pin 4 and GND pin 11, not the corners.": (
        "VCC 4, GND 11 numaralı pindir; köşelerdeki pinler değil."
    ),
    "Eight Darlington sinks, 50 V, 500 mA, with flyback diodes": (
        "Sekiz Darlington akım çekici, 50 V, 500 mA, serbest geçiş diyotlu"
    ),
    "LED display driver: eight 7-segment digits or an 8 x 8 matrix, serial in": (
        "LED gösterge sürücüsü: sekiz 7 segmentli hane ya da 8 × 8 matris, seri girişli"
    ),
    "Both GND pins have to be wired. A resistor from ISET to V+, 9.53k or more, sets the "
    "segment current.": (
        "İki GND pini de bağlanmalıdır. ISET ile V+ arasındaki direnç (9,53k ya da daha "
        "büyük) segment akımını belirler."
    ),
    "NPN, 45 V, 800 mA, switching": "NPN, 45 V, 800 mA, anahtarlama",
    "PNP, 45 V, 800 mA, switching": "PNP, 45 V, 800 mA, anahtarlama",
    "Low-dropout regulator, +3.3 V, 250 mA, 1.6 uA quiescent": (
        "Düşük düşümlü (LDO) regülatör, +3,3 V, 250 mA, 1,6 µA boşta akım"
    ),
    "NOT pinned like a 78L05: GND, IN, OUT. Its input is 6 V at most, and it needs 1 uF "
    "on both sides.": (
        "Bacak dizilişi 78L05 gibi DEĞİL: GND, IN, OUT. Girişi en çok 6 V olabilir ve iki "
        "tarafında da 1 µF ister."
    ),
    "EEPROM, 256 kbit (32 kB), I2C": "I2C EEPROM bellek, 256 kbit (32 kB)",
    "WP to VSS lets it be written; A0-A2 set its address.": (
        "WP VSS'ye bağlıyken yazılabilir; A0-A2 adresini belirler."
    ),
    "8-bit shift register, parallel in, serial out": (
        "8 bit kaydırmalı yazmaç, paralel giriş, seri çıkış"
    ),
    "Pin 7 is QH inverted. The output to read, and to chain the next one from, is pin 9.": (
        "7 numaralı pin QH'nin tersidir. Okunacak çıkış, bir sonrakini zincirleyeceğiniz "
        "çıkış da 9 numaralı pindir."
    ),
    "Decade counter with ten decoded outputs": "Onluk sayıcı, on çözülmüş çıkışlı",
    "The outputs are not in order round the package: Q0 is pin 3.": (
        "Çıkışlar kılıf etrafında sırayla dizilmez: Q0, 3 numaralı pindir."
    ),
    "8-bit I/O expander, I2C (the chip on an LCD's I2C backpack)": (
        "8 bit G/Ç genişletici, I2C (LCD'lerin I2C sırt kartındaki entegre)"
    ),
    "The PCF8574A is pinned the same and answers at another address (0x38-0x3F, not "
    "0x20-0x27).": (
        "PCF8574A'nın dizilişi aynıdır, başka bir adreste yanıt verir (0x20-0x27 değil, "
        "0x38-0x3F)."
    ),
    "8-channel 10-bit ADC, SPI": "8 kanallı 10 bit ADC, SPI",
    "16-bit I/O expander, I2C": "16 bit G/Ç genişletici, I2C",
    "RESET has no pull-up of its own: tie it to VDD or the chip stays in reset. GPA7 and "
    "GPB7 are outputs only.": (
        "RESET'in kendi pull-up'ı yoktur: VDD'ye bağlayın, yoksa entegre resette kalır. "
        "GPA7 ve GPB7 yalnızca çıkıştır."
    ),
    "ESP32-WROOM-32 dev board, 38 pins, rows 25.4 mm apart": (
        "ESP32-WROOM-32 geliştirme kartı, 38 pin, sıralar arası 25,4 mm"
    ),
    "ESP32-C3 dev board, 30 pins, rows 22.86 mm apart": (
        "ESP32-C3 geliştirme kartı, 30 pin, sıralar arası 22,86 mm"
    ),
    "ATmega328P board, 30 pins, rows 15.24 mm apart": (
        "ATmega328P kartı, 30 pin, sıralar arası 15,24 mm"
    ),
    "ATmega328P board, 24 pins, rows 15.24 mm apart: 5 V at 16 MHz or 3.3 V at 8 MHz": (
        "ATmega328P kartı, 24 pin, sıralar 15,24 mm arayla: 16 MHz'de 5 V ya da 8 MHz'de "
        "3,3 V"
    ),
    "A4 and A5 (I2C) and A6 and A7 are on two pairs of pads inside the RAW row, off the "
    "0.1 inch grid: wire them on their own. The six pads at the end are its FTDI "
    "programming header. RAW is the regulator's input and VCC its output, 5 V or 3.3 V "
    "by the version. Clones share the 24 header pins; A4–A7 and the FTDI pads may sit "
    "elsewhere, so wire those from the board in your hand. The height of what is on the "
    "board is an estimate, and so is its colour; the pins, the rows and the board outline "
    "are measured.": (
        "A4 ve A5 (I2C) ile A6 ve A7, RAW sırasının içindeki iki çift pedde ve 0,1 inçlik "
        "ızgaranın dışındadır: bunları ayrıca kablolayın. Uçtaki altı ped FTDI programlama "
        "header'ıdır. RAW regülatörün girişi, VCC çıkışıdır; sürüme göre 5 V ya da 3,3 V. "
        "Klonlarda 24 header pini aynıdır; A4–A7 ve FTDI pedleri başka yerde olabilir, "
        "bu yüzden bunları elinizdeki karta bakarak kablolayın. Kartın üzerindekilerin yüksekliği ve rengi tahmindir; pinler, sıralar ve kart "
        "çerçevesi ölçülmüştür."
    ),
    "Four channels between two logic levels, both ways: 12 pins, rows 10.16 mm apart": (
        "İki mantık seviyesi arasında iki yönlü dört kanal: 12 pin, sıralar 10,16 mm arayla"
    ),
    "HV takes the higher supply and LV the lower (5 V and 3.3 V, say), with GND; then "
    "HV1 is LV1 at the other level, and so on for all four. Each channel is a BSS138 "
    "with a 10k pull-up to each side, so a rising edge is only as quick as that 10k "
    "makes it. The height of what is on the board is an estimate, and so is its colour; "
    "the pins, the rows and the board outline are measured.": (
        "HV yüksek beslemeye, LV düşük beslemeye bağlanır (örneğin 5 V ve 3,3 V), GND ile "
        "birlikte; böylece HV1, LV1'in öbür seviyedeki karşılığıdır, dört kanalın hepsinde "
        "de böyle. Her kanal, iki yanında birer 10k pull-up olan bir BSS138'dir; yükselen "
        "kenar ancak o 10k'nın izin verdiği kadar hızlıdır. Kartın üzerindekilerin "
        "yüksekliği ve rengi tahmindir; pinler, sıralar ve kart çerçevesi ölçülmüştür."
    ),
    "Current, voltage and power on I2C, through a 0.1 ohm shunt: up to 26 V and ±3.2 A": (
        "I2C üzerinden akım, gerilim ve güç, 0,1 ohm'luk şönt üzerinden: en çok 26 V ve "
        "±3,2 A"
    ),
    "The board prints pin 1 as VIN: it is VCC, the logic supply, 3 to 5 V. The current "
    "to measure goes in at VIN+ and out at VIN-, on these pins or on the terminal "
    "block, which carries the same two. Its address is 0x40 until A0 or A1 is bridged "
    "on the back, and the two STEMMA QT sockets carry the same I2C. The height of what "
    "is on the board is an estimate, and so is its colour; the pins, the rows and the "
    "board outline are measured.": (
        "Kart 1. pinin yanına VIN yazar: bu pin VCC'dir, 3-5 V'luk mantık beslemesi. "
        "Ölçülecek akım VIN+ pininden girer, VIN- pininden çıkar; bu pinlerde ya da aynı "
        "ikisini taşıyan klemenste. Arkadaki A0 ya da A1 köprülenene kadar adresi 0x40'tır; "
        "iki STEMMA QT soketi de aynı I2C hattını taşır. Kartın üzerindekilerin yüksekliği "
        "ve rengi tahmindir; pinler, sıralar ve kart çerçevesi ölçülmüştür."
    ),
    "VCC is the logic supply, 3 to 5 V. The current to measure goes in at VIN+ and out "
    "at VIN-, on these pins or on the terminal block, which carries the same two. Its "
    "address is 0x40 until A0 or A1 is bridged. Clones such as the purple CJMCU-219 "
    "usually keep this header order; measure your board's size and header position "
    "before placing. The height of what is on the board is an estimate, and so is its "
    "colour; the pins, the rows and the board outline are measured.": (
        "VCC, 3-5 V'luk mantık beslemesidir. Ölçülecek akım VIN+ pininden girer, VIN- "
        "pininden çıkar; bu pinlerde ya da aynı ikisini taşıyan klemenste. A0 ya da A1 "
        "köprülenene kadar adresi 0x40'tır. Mor CJMCU-219 gibi klonlar genellikle bu header "
        "sırasını korur; yerleştirmeden önce kartınızın boyutunu ve header'ın yerini ölçün. "
        "Kartın üzerindekilerin yüksekliği ve rengi tahmindir; pinler, sıralar ve kart "
        "çerçevesi ölçülmüştür."
    ),
    "RP2040 board, 40 pins, rows 17.78 mm apart": "RP2040 kartı, 40 pin, sıralar arası 17,78 mm",
    "ESP8266 board, 16 pins, rows 22.86 mm apart": (
        "ESP8266 kartı, 16 pin, sıralar arası 22,86 mm"
    ),
    "Stepper motor driver, 8-35 V, 1 A per coil (2 A with cooling), rows 12.7 mm apart": (
        "Step motor sürücüsü, 8-35 V, bobin başına 1 A (soğutmayla 2 A), sıralar arası 12,7 mm"
    ),
    "Set the current limit with the trimmer before a motor is connected. The red and green "
    "StepStick boards sold as A4988 have these pins and not this layout. The height of what "
    "is on the board is an estimate, and so is its colour; the pins, the rows and the board "
    "outline are measured.": (
        "Motor bağlanmadan önce akım sınırını trimerle ayarlayın. A4988 adıyla satılan kırmızı "
        "ve yeşil StepStick kartlarında bu pinler var, bu yerleşim yok. Kartın üstündekilerin "
        "yüksekliği tahmindir, rengi de öyle; pinler, sıralar ve kart çevresi ölçülmüştür."
    ),
    "Stepper motor driver, 8.2-45 V, 1.5 A per coil (2.2 A with cooling), rows 12.7 mm "
    "apart": (
        "Step motor sürücüsü, 8,2-45 V, bobin başına 1,5 A (soğutmayla 2,2 A), sıralar arası "
        "12,7 mm"
    ),
    "Set the current limit with the trimmer before a motor is connected. The height of what "
    "is on the board is an estimate, and so is its colour; the pins, the rows and the board "
    "outline are measured.": (
        "Motor bağlanmadan önce akım sınırını trimerle ayarlayın. Kartın üstündekilerin "
        "yüksekliği tahmindir, rengi de öyle; pinler, sıralar ve kart çevresi ölçülmüştür."
    ),
    "ESP32-C3 board, 14 pins, rows 15.24 mm apart": (
        "ESP32-C3 kartı, 14 pin, sıralar arası 15,24 mm"
    ),
    "The USB-C socket stands about 1.8 mm past the end of the board. The height of what is "
    "on the board is an estimate, and so is its colour; the pins, the rows and the board "
    "outline are measured.": (
        "USB-C soketi kartın ucundan yaklaşık 1,8 mm taşar. Kartın üstündekilerin yüksekliği "
        "tahmindir, rengi de öyle; pinler, sıralar ve kart çevresi ölçülmüştür."
    ),
    "Humidity and temperature sensor, 20-90 %RH, 0-50 degrees C, single wire": (
        "Nem ve sıcaklık sensörü, %20-90 bağıl nem, 0-50 derece, tek hat"
    ),
    "Humidity and temperature sensor, 0-100 %RH, -40 to 80 degrees C, single wire": (
        "Nem ve sıcaklık sensörü, %0-100 bağıl nem, -40 ile 80 derece arası, tek hat"
    ),
    "Also sold on a small board with three pins, in more than one order: on one of those, "
    "go by what the board itself has printed beside each pin.": (
        "Üç pinli küçük bir kart üzerinde de satılır ve pin sırası birden fazladır: öyle "
        "birindeyse her pinin yanında kartın kendi üstünde yazana göre bağlayın."
    ),
    "KiCad's AM2302 symbol calls pin 3 GND; Aosong's datasheet says it is not connected, "
    "and so does this. Also sold on a small board with three pins: on one of those, go by "
    "what the board itself has printed.": (
        "KiCad'in AM2302 sembolü 3. pine GND der; Aosong'un veri sayfası bağlı olmadığını "
        "söyler, burada da öyle. Üç pinli küçük bir kart üzerinde de satılır: öyle "
        "birindeyse kartın kendi üstünde yazana göre bağlayın."
    ),
    "The height of what is on the board is an estimate, and so is its colour; the "
    "pins, the rows and the board outline are measured.": (
        "Kartın üstündekilerin yüksekliği tahmindir, rengi de öyle; pinler, sıralar ve "
        "kart çevresi ölçülmüştür."
    ),
    "Clones called 'ESP32 DevKit' come with 30 or 38 pins and more than one row "
    "spacing: count your pins and measure across the rows. The height of what is on "
    "the board is an estimate, and so is its colour; the pins, the rows and the board "
    "outline are measured.": (
        "'ESP32 DevKit' adıyla satılan klonlar 30 ya da 38 pinli ve birden çok sıra "
        "aralığıyla gelir: pinlerinizi sayın ve sıralar arasını ölçün. Kartın "
        "üstündekilerin yüksekliği tahmindir, rengi de öyle; pinler, sıralar ve kart "
        "çevresi ölçülmüştür."
    ),
    "The 6-pin ICSP header, if fitted, stands taller. The height of what is on the "
    "board is an estimate, and so is its colour; the pins, the rows and the board "
    "outline are measured.": (
        "6 pinli ICSP başlığı takılıysa daha yüksekte durur. Kartın üstündekilerin "
        "yüksekliği tahmindir, rengi de öyle; pinler, sıralar ve kart çevresi ölçülmüştür."
    ),
    # -- the step bar (ui/workflow.py) -----------------------------------------
    "Circuit": "Devre",
    "Placement": "Yerleşim",
    "Wiring": "Kablolama",
    "Checks": "Kontrol",
    "Build": "Montaj",
    "Menus: File, Edit, View and the rest. Alt opens them too.": (
        "Menüler: Dosya, Düzen, Görünüm ve diğerleri. Alt tuşu da açar."
    ),
    "Not saved": "Kaydedilmedi",
    "Drawing &Tools": "Çi&zim Araçları",
    "R&otate": "Dö&ndür",
    "Fl&ip": "&Çevir",
    "&Place on the Board": "Karta &Yerleştir",
    "Float the &Panel": "Paneli Ayı&r",
    "Back to the &Window": "Pencereye &Geri Al",
    "Zoom In": "Yakınlaştır",
    "Zoom Out": "Uzaklaştır",
    "Search Commands…": "Komut Ara…",
    "Search or run a command…": "Komut arayın ya da çalıştırın…",
    "Every command by its name, and any part or net (Ctrl+K).": (
        "Her komut adıyla; her parça ve net de (Ctrl+K)."
    ),
    "Type a command, a part or a net…": "Bir komut, parça ya da net yazın…",
    "Part on the board": "Karttaki parça",
    "Part in the design": "Tasarımdaki parça",
    "Properties": "Özellikler",
    "{count} selected": "{count} seçili",
    "{count} pins": "{count} pin",
    "Placing a part": "Parça yerleştiriliyor",
    "Click the board where pin 1 goes. Esc cancels.": (
        "1. pinin gideceği yere tıklayın. Esc iptal eder."
    ),
    "{cols} × {rows} holes": "{cols} × {rows} delik",
    "More": "Diğer",
    "Everything a right-click on the selection offers.": (
        "Seçimde sağ tıklamanın sunduğu her şey."
    ),
    "Connect": "Bağla",
    "Rearrange": "Yeniden Diz",
    # What an accepting button says, rather than OK.
    "Use This Board": "Bu Kartı Kullan",
    "Use This Part": "Bu Parçayı Kullan",
    "Create Project": "Projeyi Oluştur",
    "Move the Parts": "Parçaları Taşı",
    "Redo Their Wiring…": "Kablolamalarını Yeniden Yap…",
    "Wire Beside It": "Eskisinin Yanına Kablola",
    "3D": "3D",
    "Everything the three checks found, worst first (Ctrl+7).": (
        "Üç denetimin bulduğu her şey, en ciddisi önce (Ctrl+7)."
    ),
    "No problems": "Sorun yok",
    "{count} to wire": "{count} kablolanacak",
    "Matches the circuit: {matched} of {total} nets": "Devreyle uyuşan net: {matched}/{total}",
    "Select and move parts. Esc comes back to it from any tool.": (
        "Parçaları seçin ve taşıyın. Esc her araçtan buraya döner."
    ),
    "Show": "Göster",
    "What the board shows: the connections still missing, hole addresses, pin names, values.": (
        "Kartta görünenler: eksik bağlantılar, delik adresleri, pin adları, değerler."
    ),
    "Save the board (Ctrl+S).": "Kartı kaydedin (Ctrl+S).",
    "Add a Part…": "Parça Ekle…",
    "Choose a Board…": "Kart Seç…",
    "Connect the Pins": "Pinleri Bağla",
    # -- a net's class and state in the Nets panel -------------------------------------
    "signal": "sinyal",
    "ground": "toprak",
    "power": "güç",
    "not placed": "yerleşmedi",
    "Connect {pin} to {net}": "{pin} pinini {net} netine bağla",
    "Connect {pin} to a Net by Name…": "{pin} pinini adıyla bir nete bağla…",
    # -- empty panels (ui/emptystate.py): what will be here, and how it gets here ------
    "No nets yet": "Henüz net yok",
    "Join two pins with Connect, on the schematic or the board. Pins joined together make "
    "a net.": (
        "İki pini Bağla ile birleştirin, şemada ya da kartta. Birbirine bağlı pinler bir net "
        "olur."
    ),
    "No parts yet": "Henüz parça yok",
    "Parts you add show up here with their values. It becomes your shopping list.": (
        "Eklediğiniz parçalar değerleriyle burada görünür. Alışveriş listeniz olur."
    ),
    "Draw your circuit here": "Devrenizi buraya çizin",
    "Add parts from the Library, then join their pins with Connect. The board comes later.": (
        "Kütüphaneden parça ekleyin, sonra pinlerini Bağla ile birleştirin. Kart sonra gelir."
    ),
    "Open an Example…": "Örnek Aç…",
    "The guide writes itself": "Rehber kendini yazar",
    "Once parts are on the board, this becomes the soldering order, one step at a time.": (
        "Parçalar karta yerleşince burası lehimleme sırası olur, adım adım."
    ),
    "{count} part is waiting for a board": "{count} parça bir kart bekliyor",
    "{count} parts are waiting for a board": "{count} parça bir kart bekliyor",
    "The blue button at the top right takes them there: Choose a Board, then Place on the "
    "Board.": (
        "Sağ üstteki mavi düğme onları oraya götürür: önce Kart Seç, sonra Karta Yerleştir."
    ),
    "The board comes after the circuit": "Kart devreden sonra gelir",
    "Draw the circuit on the schematic first (Ctrl+2). The next step then finds a board you "
    "can buy.": (
        "Önce devreyi şemada çizin (Ctrl+2). Sonraki adım satın alabileceğiniz bir kart bulur."
    ),
    "Or drag a part here from the Library.": "Ya da Kütüphaneden buraya bir parça sürükleyin.",
    # -- the empty board --------------------------------------------------------------
    "{count} part(s) are in the design: {catalog} known from the catalog, {kicad} "
    "matched by their KiCad footprint, {guess} guessed from their reference — check "
    "those. Next: choose a board and place them.": (
        "{count} parça tasarımda: {catalog} tanesi katalogdan tanındı, {kicad} tanesi "
        "KiCad kılıfından eşleşti, {guess} tanesi referansından tahmin edildi — onları "
        "kontrol edin. Sıradaki: bir kart seçip parçaları yerleştirin."
    ),
    # -- help (ui/helpcards.py): F1, What's This and the glossary say one text -----------
    "Help for What's Under the &Pointer": "İmlecin Altındakinin &Yardımı",
    "What's &This?": "Bu &Nedir?",
    "&Glossary…": "&Sözlük…",
    "Point at a panel or a tool and press F1 to read what it is.": (
        "Bir panelin ya da aracın üzerine gelip F1'e basın; ne olduğunu okuyun."
    ),
    "Then click on anything to read what it is.": (
        "Sonra herhangi bir şeye tıklayın; ne olduğunu okuyun."
    ),
    "The words this window and the build guide use, explained.": (
        "Bu pencerenin ve montaj rehberinin kullandığı kelimeler, açıklamalarıyla."
    ),
    "Help": "Yardım",
    "Help ▸ Glossary explains the words. Ctrl+/ lists the shortcuts.": (
        "Yardım ▸ Sözlük kelimeleri açıklar. Ctrl+/ kısayolları listeler."
    ),
    "Point at a panel or a tool and press F1 to read what it is. Shift+F1 lets you click "
    "on anything instead. Help ▸ Glossary explains the words; Ctrl+/ lists the keyboard "
    "shortcuts.": (
        "Bir panelin ya da aracın üzerine gelip F1'e basın; ne olduğunu okuyun. Shift+F1 "
        "ile bunun yerine herhangi bir şeye tıklayabilirsiniz. Yardım ▸ Sözlük kelimeleri "
        "açıklar; Ctrl+/ klavye kısayollarını listeler."
    ),
    "Glossary": "Sözlük",
    "Find a word…": "Kelime ara…",
    "Word": "Kelime",
    "What it means": "Anlamı",
    "The next step": "Sıradaki adım",
    "The board's tools": "Kartın araçları",
    "Tools that work on the board, one at a time; Esc goes back to Select. A button with a "
    "small triangle in its corner holds more than one tool of its kind: hold it or right-click "
    "it to pick another, and it keeps the last one picked.": (
        "Kart üzerinde çalışan araçlar, her seferinde biri; Esc Seç'e döner. Köşesinde küçük bir "
        "üçgen olan düğme aynı türden birden çok aracı taşır: başka birini seçmek için basılı "
        "tutun ya da sağ tıklayın; düğme son seçileni hatırlar."
    ),
    "The schematic's tools": "Şemanın araçları",
    "Tools that work on the schematic, one at a time; Esc goes back to Select. A button with a "
    "small triangle in its corner holds more than one tool of its kind: hold it or right-click "
    "it to pick another.": (
        "Şema üzerinde çalışan araçlar, her seferinde biri; Esc Seç'e döner. Köşesinde küçük bir "
        "üçgen olan düğme aynı türden birden çok aracı taşır: başka birini seçmek için basılı "
        "tutun ya da sağ tıklayın."
    ),
    "How the board is shown": "Kartın nasıl gösterildiği",
    "What the board shows, which side is up and how near it is. Nothing here changes the board.": (
        "Kartta neyin göründüğü, hangi yüzün üstte olduğu ve ne kadar yakın olduğu. Buradaki "
        "hiçbir şey kartı değiştirmez."
    ),
    "How the schematic is shown": "Şemanın nasıl gösterildiği",
    "How near the schematic is, and fitting it to the window. Nothing here changes the "
    "circuit.": (
        "Şemanın ne kadar yakın olduğu ve pencereye sığdırılması. Buradaki hiçbir şey devreyi "
        "değiştirmez."
    ),
    "The guide's tools": "Rehberin araçları",
    "The first step not ticked off yet, shown on the board; every tick cleared; and the guide "
    "written out to files to print or keep beside the bench. Nothing here changes the board.": (
        "Henüz işaretlenmemiş ilk adım, kartta gösterilir; bütün işaretlerin kaldırılması; ve "
        "yazdırmak ya da tezgâhın yanında tutmak için rehberin dosyalara yazılması. Buradaki "
        "hiçbir şey kartı değiştirmez."
    ),
    "What the selection can do": "Seçimle neler yapılabilir",
    "What can be done to the selected parts, right where they are. The last button holds "
    "everything a right-click offers.": (
        "Seçili parçalarla, tam bulundukları yerde yapılabilecekler. Son düğme sağ tıklamanın "
        "sunduğu her şeyi taşır."
    ),
    "Always the one thing to do next, from drawing the circuit to opening the build guide. "
    "Pressing it is the whole workflow; the menus hold the same commands.": (
        "Her zaman yapılacak sıradaki tek şey: devreyi çizmekten montaj rehberini açmaya "
        "kadar. Ona basmak iş akışının tamamıdır; menüler aynı komutları içerir."
    ),
    "Every part you can add. Drag one onto the circuit or the board, or pick it and click "
    "where it goes. The filter finds a part by name, value or package.": (
        "Ekleyebileceğiniz bütün parçalar. Birini devreye ya da karta sürükleyin veya "
        "seçip gideceği yere tıklayın. Süzgeç bir parçayı adından, değerinden ya da "
        "kılıfından bulur."
    ),
    "What is in this design, with values: the list to buy from. Click one to find it on "
    "the board or the sheet.": (
        "Bu tasarımdaki parçalar, değerleriyle: alışveriş listesi. Birine tıklayın; kartta "
        "ya da şemada bulunsun."
    ),
    "A net is a group of pins that must all be joined, like GND or +5V. The last column "
    "counts the connections in it still to wire; double-click a net to wire just that one.": (
        "Net, hepsi birbirine bağlanması gereken bir pin grubudur: GND ya da +5V gibi. Son "
        "sütun, içinde henüz kablolanmamış bağlantıları sayar; yalnızca o neti kablolamak "
        "için nete çift tıklayın."
    ),
    "What the three checks found. The circuit check (ERC) looks at the circuit itself, the "
    "board check (DRC) at whether the board can be built, and Matches circuit (LVS) at "
    "whether the copper joins what the circuit says. Click a row to see it on the board.": (
        "Üç denetimin bulduğu her şey. Devre denetimi (ERC) devrenin kendisine, kart "
        "denetimi (DRC) kartın yapılıp yapılamayacağına, devreyle uyum (LVS) ise bakırın "
        "devrenin söylediğini bağlayıp bağlamadığına bakar. Kartta görmek için bir satıra "
        "tıklayın."
    ),
    "The board from the parts side (Ctrl+1). Flip shows the solder side, where the traces "
    "and bare wires are. A hole is named like C7: column letter, row number.": (
        "Kart, parça yüzünden (Ctrl+1). Çevir, lehim yollarının ve çıplak tellerin "
        "bulunduğu lehim yüzünü gösterir. Bir delik C7 gibi adlandırılır: sütun harfi, "
        "satır numarası."
    ),
    "The circuit as a drawing (Ctrl+2): the parts, and what connects to what. Clicking a "
    "symbol selects the same part on the board.": (
        "Devrenin çizimi (Ctrl+2): parçalar ve neyin neye bağlandığı. Bir sembole tıklamak "
        "aynı parçayı kartta da seçer."
    ),
    "The board as it will look, parts and all (Ctrl+3). Drag to turn it: it is the "
    "quickest way to see a part that stands too tall or too close.": (
        "Kartın, parçalarıyla birlikte bitince nasıl görüneceği (Ctrl+3). Döndürmek için "
        "sürükleyin: fazla yüksek ya da fazla yakın duran bir parçayı görmenin en hızlı "
        "yolu budur."
    ),
    "The soldering order, one step at a time: lowest parts first, ICs last. Tick a step as "
    "you finish it and the next one lights up on the board and in 3D.": (
        "Lehimleme sırası, adım adım: önce en alçak parçalar, entegreler en son. "
        "Bitirdiğiniz adımı işaretleyin; sıradaki kartta ve 3D'de yanar."
    ),
    "Solder trace": "Lehim yolu",
    "A line of solder joining neighbouring pads on the underside. It only goes straight "
    "from pad to pad: solder bridges the 0.6 mm gap to the next pad, not the 1.7 mm "
    "diagonal one.": (
        "Alt yüzde komşu pedleri birleştiren bir lehim çizgisi. Yalnızca pedden pede düz "
        "gider: lehim yandaki pede olan 0,6 mm boşluğu kapatır, çaprazdaki 1,7 mm boşluğu "
        "kapatmaz."
    ),
    "Reinforced solder trace": "Telli lehim yolu",
    "Solder over a bare wire laid along the pads: about ten times less resistance, and "
    "long runs stop lifting pads. For power and ground.": (
        "Pedler boyunca yatırılmış çıplak bir telin üzerine lehim: yaklaşık on kat az "
        "direnç ve uzun yollar pedleri kaldırmaz. Güç ve toprak için."
    ),
    "Bare wire": "Çıplak tel",
    "Uninsulated wire on the underside, soldered at its two ends. It may not cross other "
    "copper.": (
        "Alt yüzde yalıtımsız tel, iki ucundan lehimlenir. Başka bakırın üzerinden geçemez."
    ),
    "Insulated wire": "İzoleli tel",
    "Wire with insulation, on the underside. It can cross anything; stripping its ends is "
    "the cost.": (
        "Alt yüzde izoleli tel. Her şeyin üzerinden geçebilir; bedeli uçlarını soymaktır."
    ),
    "Jumper over the parts": "Parçaların üstünden jumper",
    "An insulated wire on the parts' side, hopping over everything below. It takes room a "
    "part would use, so no part may stand on it.": (
        "Parça yüzünde, alttaki her şeyin üstünden atlayan izoleli tel. Bir parçanın "
        "kullanacağı yeri kaplar; bu yüzden üstünde parça duramaz."
    ),
    "Click a pin, then the pin it joins. They become one net: the one either pin is on "
    "already, or a new one.": (
        "Bir pine, sonra bağlanacağı pine tıklayın. İkisi tek bir net olur: pinlerden "
        "birinin zaten bulunduğu net ya da yeni bir net."
    ),
    "Lays solder traces, wires and jumpers for every connection still missing, in the "
    "style chosen under Wiring. It only adds: after moving parts, Redo All Wiring starts "
    "again from nothing.": (
        "Eksik her bağlantı için, Kablolama altında seçilen tarzda lehim yolları, teller "
        "ve jumperlar döşer. Yalnızca ekler: parçaları taşıdıktan sonra Bütün Kablolamayı "
        "Yeniden Yap sıfırdan başlar."
    ),
    "Moves the unlocked parts so their connections get shorter and more of them can be "
    "solder traces. It shows the result before applying it.": (
        "Kilitsiz parçaları, bağlantıları kısalsın ve daha çoğu lehim yolu olabilsin diye "
        "taşır. Sonucu uygulamadan önce gösterir."
    ),
    "Missing connections": "Eksik bağlantılar",
    "Dashed lines between pins the circuit joins and the board does not yet — KiCad calls "
    "them the ratsnest. They go as the wiring is laid.": (
        "Devrenin bağladığı ama kartın henüz bağlamadığı pinler arasındaki kesikli "
        "çizgiler — KiCad bunlara ratsnest der. Kablolama döşendikçe kaybolurlar."
    ),
    "Turns the board over to the solder side and back, mirrored exactly as it is with the "
    "board in your hand.": (
        "Kartı lehim yüzüne çevirir ve geri getirir; kart elinizdeyken nasılsa tam öyle "
        "aynalanmış olarak."
    ),
    "A group of pins that must all be joined: GND, +5V, OUT.": (
        "Hepsi birbirine bağlanması gereken pin grubu: GND, +5V, OUT."
    ),
    "A part's leg, numbered as its datasheet numbers it.": (
        "Parçanın bacağı; datasheet'te nasıl numaralandıysa öyle numaralanır."
    ),
    "Pin (leg)": "Pin (bacak)",
    "Pad": "Ped",
    "The copper ring round a hole, where a joint is soldered.": (
        "Deliğin etrafındaki, lehimin yapıldığı bakır halka."
    ),
    "Hole address": "Delik adresi",
    "A hole named by its column letter and row number, like C7.": (
        "Sütun harfi ve satır numarasıyla adlandırılan delik, C7 gibi."
    ),
    "A part's body and leg spacing: TO-220, DIP-8, a 5 mm LED.": (
        "Parçanın gövdesi ve bacak aralığı: TO-220, DIP-8, 5 mm LED."
    ),
    "A part's short name on the board and in the guide: R1, C3, U2.": (
        "Parçanın kartta ve rehberdeki kısa adı: R1, C3, U2."
    ),
    "What to buy: 10k, 100nF, NE555.": "Ne alınacağı: 10k, 100nF, NE555.",
    "A line of solder joining neighbouring pads, straight steps only.": (
        "Komşu pedleri birleştiren lehim çizgisi; yalnızca düz adımlar."
    ),
    "A solder trace laid over a bare wire, for power and ground.": (
        "Çıplak bir telin üzerine çekilen lehim yolu; güç ve toprak için."
    ),
    "Uninsulated wire on the underside. It may not cross other copper.": (
        "Alt yüzde yalıtımsız tel. Başka bakırın üzerinden geçemez."
    ),
    "Wire with insulation, on the underside. It may cross anything.": (
        "Alt yüzde izoleli tel. Her şeyin üzerinden geçebilir."
    ),
    "An insulated wire on the parts' side, over everything below.": (
        "Parça yüzünde, alttaki her şeyin üstünden geçen izoleli tel."
    ),
    "Bent leg": "Bükülen bacak",
    "A part's own leg folded to a nearby hole: the cheapest connection.": (
        "Parçanın kendi bacağının yakındaki bir deliğe bükülmesi: en ucuz bağlantı."
    ),
    "Parts side": "Parça yüzü",
    "The side the parts stand on.": "Parçaların durduğu yüz.",
    "Solder side": "Lehim yüzü",
    "The side the joints, traces and bare wires are on.": (
        "Lehim noktalarının, lehim yollarının ve çıplak tellerin bulunduğu yüz."
    ),
    "Stripboard": "Şeritli kart",
    "A board whose rows are joined strips of copper, cut where they must stop.": (
        "Satırları birleşik bakır şeritlerden oluşan, durması gereken yerde kesilen kart."
    ),
    "Breadboard": "Lehimsiz breadboard",
    "A plug-in board for trying a circuit with no solder.": (
        "Bir devreyi lehimsiz denemek için takmalı kart."
    ),
    "Rail": "Ray",
    "A long run for power or ground; on a breadboard, the edge rows.": (
        "Güç ya da toprak için uzun hat; breadboard'da kenar sıraları."
    ),
    "Checks the circuit itself — power, polarity, pins left open — before any board.": (
        "Devrenin kendisini denetler — besleme, kutup, boşta pinler — daha kart yokken."
    ),
    "Checks the board can be built: nothing overlaps, sits too close or hangs off the edge.": (
        "Kartın yapılabildiğini denetler: çakışan, fazla yakın duran ya da kenardan taşan "
        "bir şey yok."
    ),
    "Checks the copper joins exactly what the circuit says: nothing missing, nothing extra.": (
        "Bakırın tam olarak devrenin söylediğini bağladığını denetler: eksik yok, fazla "
        "yok."
    ),
    "Pins the circuit joins and the board does not yet, drawn as dashed lines (the "
    "ratsnest).": (
        "Devrenin bağladığı ama kartın henüz bağlamadığı pinler, kesikli çizgilerle "
        "(ratsnest)."
    ),
    "Netlist": "Netlist (devre listesi)",
    "A circuit as a list of parts and what connects to what; KiCad writes one as a .net "
    "file.": (
        "Parçaların ve neyin neye bağlandığının listesi olarak bir devre; KiCad bunu .net "
        "dosyası olarak yazar."
    ),
    "Phenolic": "Pertinaks",
    "The brown paper-based board. Its pads lift easily, so the guide solders it cooler.": (
        "Kahverengi, kâğıt tabanlı kart. Pedleri kolay kalkar; bu yüzden rehber onu daha "
        "düşük sıcaklıkta lehimletir."
    ),
    # -- Home (ui/home.py): the page before there is a board ---------------------------
    # The sentences speak to the builder as "siz"; the buttons are command names and keep
    # the bare form, except the first door, which is an invitation with "your" in it.
    "Design it on screen. Solder it from the guide.": (
        "Ekranda tasarlayın. Rehberden lehimleyin."
    ),
    "Draw the circuit. The app picks a board you can buy, lays the parts out and wires "
    "them, then writes the soldering steps for you.": (
        "Devreyi çizin. Uygulama satın alabileceğiniz bir kart seçer, parçaları dizer ve "
        "kablolar, sonra lehimleme adımlarını sizin için yazar."
    ),
    "Draw Your First Circuit": "İlk Devrenizi Çizin",
    "New Circuit": "Yeni Devre",
    "Open…": "Aç…",
    "A board you saved (.perf).": "Kaydettiğiniz bir kart (.perf).",
    "Import from KiCad…": "KiCad'den İçe Aktar…",
    "New here?": "Yeni misiniz?",
    "Take the 1-minute tour": "1 dakikalık turu başlatın",
    "Opens a circuit that is already drawn and walks through it: board, placement, wiring, "
    "checks, guide.": (
        "Önceden çizilmiş bir devreyi açar ve adım adım üzerinden geçer: kart, yerleşim, "
        "kablolama, kontrol, rehber."
    ),
    "Start the Tour": "Turu Başlat",
    # -- the tour (ui/tour.py): the five presses of the next button ----------------------
    "Getting Started T&our": "&Başlangıç Turu",
    "This copy has no examples to tour.": "Bu kopyada tur için örnek yok.",
    "Skip Tour": "Turu Geç",
    "Finish": "Bitir",
    "The circuit is already drawn. This blue button is always your next step. Press it: "
    "Choose a Board.": (
        "Devre zaten çizili. Bu mavi düğme her zaman sıradaki adımınızdır. Basın: Kart Seç."
    ),
    "Every board you can buy was tried with this circuit; the one chosen is the smallest that "
    "wires well. Next: Place on the Board.": (
        "Satın alabileceğiniz her kart bu devreyle denendi; seçilen, iyi kablolanan en "
        "küçüğüdür. Sıradaki: Karta Yerleştir."
    ),
    "The parts are arranged for you. Drag any of them if you like. Next: Auto-wire.": (
        "Parçalar sizin için dizildi. İsterseniz herhangi birini sürükleyin. Sıradaki: "
        "Otomatik Kablola."
    ),
    "Wired: solder traces first, a wire only where solder can't go. The checks ran by "
    "themselves; what they found is below. Next: open the build guide.": (
        "Kablolandı: önce lehim yolu, lehimin gidemediği yerde tel. Denetimler kendiliğinden "
        "çalıştı; bulduklarını aşağıda görürsünüz. Sıradaki: montaj rehberini açın."
    ),
    "This is what you build from: the soldering order, lowest parts first. Tick a step and "
    "the next one lights up on the board. That's the whole app.": (
        "Kuracağınız şey bu: lehimleme sırası, önce en alçak parçalar. Bir adımı işaretleyin, "
        "sıradaki kartta yanar. Uygulamanın hepsi bu."
    ),
    "Welcome back": "Tekrar hoş geldiniz",
    "Recent": "Son açılanlar",
    "Enter opens the highlighted one.": "Enter seçili olanı açar.",
    "Each opens as an untitled copy. Nothing you change touches the original.": (
        "Her biri adsız bir kopya olarak açılır. Yaptığınız değişiklik aslına dokunmaz."
    ),
    "Show All Examples": "Bütün Örnekleri Göster",
    "Start here": "Buradan başlayın",
    "Start on the home page": "Açılışta ana sayfayı göster",
    # What each example is, in words.
    "A 555 blinker, drawn and not built": "Çizilmiş, kurulmamış 555 flaşör",
    "555 LED flasher": "555 LED flaşör",
    "Adjustable supply (LM317)": "Ayarlı güç kaynağı (LM317)",
    "Arduino I/O shield": "Arduino giriş/çıkış kartı",
    "Guitar booster pedal": "Gitar booster pedalı",
    "Arduino Nano relay switch": "Arduino Nano röle anahtarı",
    "ATmega328 relay controller": "ATmega328 röle kontrolcüsü",
    # -- the welcome dialog --------------------------------------------------------
    "Examples": "Örnekler",
    "Start on the sheet: add parts and join their pins. The board comes after.": (
        "Şemadan başlayın: parçaları ekleyin ve pinlerini bağlayın. Kart ondan sonra gelir."
    ),
    "A circuit drawn in KiCad: its parts and connections come in as the design.": (
        "KiCad'de çizilmiş bir devre: parçaları ve bağlantıları tasarım olarak gelir."
    ),
    # -- the board dialogs' pictures and their one line of numbers -----------------
    "Show Problems": "Sorunları Göster",
    "Open the Build Guide": "Montaj Rehberini Aç",
    "Save the Board…": "Kartı Kaydet…",
    "Take It to Perfboard…": "Perfboard'a Taşı…",
    "no parts yet": "henüz parça yok",
    # Real plurals (i18n.counted): English has two forms, Turkish the singular after a number.
    "{parts} part on a {size} board": "{size} kart üzerinde {parts} parça",
    "{parts} parts on a {size} board": "{size} kart üzerinde {parts} parça",
    "{parts} part, drawn and not yet placed": "{parts} parça, çizilmiş ama henüz yerleşmemiş",
    "{parts} parts, drawn and not yet placed": "{parts} parça, çizilmiş ama henüz yerleşmemiş",
    "power and ground drawn as {count} rail symbol": "güç ve toprak {count} ray simgesi olarak çizildi",
    "power and ground drawn as {count} rail symbols": "güç ve toprak {count} ray simgesi olarak çizildi",
    "{count} problem": "{count} sorun",
    "{count} problems": "{count} sorun",
    "{count} pin not wired yet": "{count} pin henüz bağlanmadı",
    "{count} pins not wired yet": "{count} pin henüz bağlanmadı",
    "{count} part": "{count} parça",
    "{count} parts": "{count} parça",
    "{count} net": "{count} net",
    "{count} nets": "{count} net",
    "nothing to place": "yerleştirilecek parça yok",
    "{placed}/{total} on the board": "{placed}/{total} kartta",
    "nothing to wire yet": "henüz bağlanacak bir şey yok",
    "{count} connection to wire": "{count} bağlantı kaldı",
    "{count} connections to wire": "{count} bağlantı kaldı",
    "all wired": "hepsi bağlı",
    "nothing to check yet": "henüz denetlenecek bir şey yok",
    "{count} error": "{count} hata",
    "{count} errors": "{count} hata",
    "{count} warning": "{count} uyarı",
    "{count} warnings": "{count} uyarı",
    "guide ready": "rehber hazır",
    "What the board is: its parts and what joins them. Drawn on the sheet, or by placing "
    "parts on the board and connecting their pins. The circuit check (ERC) runs as it is "
    "drawn: a chip with no supply is an error before any board is chosen.": (
        "Kartın ne olduğu: parçaları ve onları neyin birleştirdiği. Şemada çizilir ya da "
        "parçalar karta konup pinleri bağlanarak girilir. Devre denetimi (ERC) devre "
        "çizilirken çalışır: beslemesi olmayan bir entegre, daha kart seçilmeden hatadır."
    ),
    "Which perfboard it goes on. Chosen before the parts go down, while the size is "
    "still free: every stock size is tried with your circuit laid out on it.": (
        "Devrenin hangi delikli karta gideceği. Parçalar yerleşmeden, boyut hâlâ serbestken "
        "seçilir: satılan her boy, devreniz üzerine gerçekten yerleştirilerek denenir."
    ),
    "Where each part goes. Arranged for you, then yours to move.": (
        "Her parçanın nereye gideceği. Sizin için dizilir, sonra istediğiniz gibi taşırsınız."
    ),
    "What joins the pins on the board: solder traces, wires and jumpers. Auto-wire lays "
    "them; the board's tools lay them by hand.": (
        "Karttaki pinleri neyin birleştirdiği: lehim yolları, teller ve jumper'lar. "
        "Otomatik Kablola bunları döşer; kartın araçlarıyla elle döşenir."
    ),
    "Whether it can be built as drawn (the board check, DRC) and whether the board matches "
    "the circuit (LVS).": (
        "Çizildiği gibi kurulup kurulamayacağı (kart denetimi, DRC) ve kartın devreyle "
        "aynı olup olmadığı (LVS)."
    ),
    "The soldering guide, step by step, with the board in 3D beside it.": (
        "Adım adım lehimleme rehberi, yanında kartın 3D görünümüyle."
    ),
    # -- what the engine says it did (ui/engine_text.py) ---------------------------
    "Place {parts} part(s) and {links} connection(s)": "{parts} parça ve {links} bağlantı yerleştir",
    "Place and arrange {count} part(s) from the schematic": "Şemadaki {count} parçayı karta yerleştir ve diz",
    "Place {count} part(s) on the board": "{count} parçayı karta yerleştir",
    "Place {ref} at {hole}": "{ref} parçasını {hole} deliğine yerleştir",
    "Move {count} component(s)": "{count} parçayı taşı",
    "Rotate {count} component(s)": "{count} parçayı döndür",
    "Mirror {count} component(s)": "{count} parçayı aynala",
    "Update {count} component(s)": "{count} parçayı güncelle",
    "Lock {count} component(s)": "{count} parçayı kilitle",
    "Unlock {count} component(s)": "{count} parçanın kilidini aç",
    "Delete {count} component(s) and {conductors} conductor(s)": "{count} parçayı ve {conductors} iletkeni sil",
    "Delete {count} component(s)": "{count} parçayı sil",
    "Move {count} symbol(s) on the sheet": "Şemada {count} sembolü taşı",
    "Move {count} symbols on the sheet": "Şemada {count} sembolü taşı",
    "Move {ref} on the sheet": "{ref} sembolünü şemada taşı",
    "Add {ref} to the sheet at ({x}, {y})": "{ref} sembolünü şemaya ekle ({x}, {y})",
    "Move {ref} to {hole}": "{ref} parçasını {hole} deliğine taşı",
    "Rotate {ref} to {degrees} degrees": "{ref} parçasını {degrees} dereceye döndür",
    "Unmirror {ref}": "{ref} parçasının aynalamasını kaldır",
    "Mirror {ref}": "{ref} parçasını aynala",
    "Take {ref} off the board": "{ref} parçasını karttan kaldır",
    "Paste {parts} part(s) and {links} connection(s)": "{parts} parça ve {links} bağlantı yapıştır",
    "Paste {parts} part(s)": "{parts} parça yapıştır",
    "Paste {links} connection(s)": "{links} bağlantı yapıştır",
    "{what} at {hole}": "{hole} deliğine {what}",
    "Auto-place {count} component(s)": "{count} parçayı otomatik yerleştir",
    "Auto-place (no change)": "Otomatik yerleşim (değişiklik yok)",
    "Add {count} imported part(s)": "İçe aktarılan {count} parçayı ekle",
    "Add {count} part(s) to the schematic": "Şemaya {count} parça ekle",
    "Add {ref} {value} to the schematic": "Şemaya {ref} {value} ekle",
    "Add {ref} to the schematic": "Şemaya {ref} ekle",
    "Delete {ref} and its {count} connection(s)": "{ref} parçasını ve {count} bağlantısını sil",
    "Turn {count} symbol(s) on the sheet": "Şemada {count} sembolü döndür",
    "Flip {count} symbol(s) on the sheet": "Şemada {count} sembolü çevir",
    "Lay {count} symbol(s) out automatically": "{count} sembolü otomatik diz",
    "Lay the whole sheet out automatically": "Bütün şemayı otomatik diz",
    "Wire {a} onto the wire from {b} to {c}": "{a} pinini {b}–{c} teline bağla",
    "Wire {a} to {b}": "{a} pinini {b} pinine tel ile bağla",
    "Rub out {count} wire(s) on the sheet and {branches} branch(es) off it": "Şemadaki {count} teli ve ondan çıkan {branches} dalı sil",
    "Rub out {count} wire(s) on the sheet": "Şemadaki {count} teli sil",
    "Rub out the wire from {a} to {b} and {branches} branch(es) off it": "{a}–{b} telini ve ondan çıkan {branches} dalı sil",
    "Rub out the wire from {a} to {b}": "{a}–{b} telini sil",
    "Draw a {shape} on the sheet": "Şemaya bir {shape} çiz",
    "Write “{text}” on the sheet": "Şemaya “{text}” yaz",
    "Edit a note on the sheet": "Şemadaki bir notu düzenle",
    "Delete {count} note(s) from the sheet": "Şemadan {count} notu sil",
    "Import netlist ({count} nets)": "Netlist içe aktar ({count} net)",
    "Add {netclass} net {name} with {count} pin(s)": "{count} pinli {netclass} neti {name} ekle",
    "Add {netclass} net {name}": "{netclass} neti {name} ekle",
    "Rename net {old} to {new}": "{old} netinin adını {new} yap",
    "Update net {name}": "{name} netini güncelle",
    "Make {name} a {netclass} net": "{name} netini {netclass} neti yap",
    "Delete net {name} ({count} conductor(s) keep their copper)": "{name} netini sil ({count} iletken bakırını korur)",
    "Delete net {name}": "{name} netini sil",
    "Connect {count} pins to {net}": "{count} pini {net} netine bağla",
    "Disconnect {count} pins from {net}": "{count} pini {net} netinden ayır",
    "Disconnect {pin} from {net}": "{pin} pinini {net} netinden ayır",
    "Add {kind} {start} to {end}": "{start} → {end} arası {kind} ekle",
    "Add {kind}": "{kind} ekle",
    "Add {count} conductor(s)": "{count} iletken ekle",
    "Reroute conductor {id}": "{id} iletkenini yeniden döşe",
    "Delete {kind} {id}": "{id} iletkenini ({kind}) sil",
    "Delete {count} conductor(s)": "{count} iletkeni sil",
    "Remove {count} stale conductor(s)": "Eskimiş {count} iletkeni kaldır",
    "Replace {removed} conductor(s) with {added}": "{removed} iletkeni {added} iletkenle değiştir",
    "Route {net} ({count} connection)": "{net} netini kablola ({count} bağlantı)",
    "Route {net} ({count} connections)": "{net} netini kablola ({count} bağlantı)",
    "Autoroute {nets} nets ({count} connection)": "{nets} neti otomatik kablola ({count} "
                                                  "bağlantı)",
    "Autoroute {nets} nets ({count} connections)": "{nets} neti otomatik kablola ({count} "
                                                   "bağlantı)",
    "Autoroute (no matching nets)": "Otomatik kablolama (eşleşen net yok)",
    "Autoroute (no netlist imported)": "Otomatik kablolama (netlist yok)",
    "Re-route {count} net(s)": "{count} neti yeniden kablola",
    "Re-route {net}": "{net} netini yeniden kablola",
    "Autoroute stripboard: {cuts} cut(s), {links} link(s)": "Şeritli kartı otomatik kablola: {cuts} "
                                                            "kesim, {links} köprü",
    "Cut track at {hole}": "{hole} deliğinde şeridi kes",
    "Cut {cuts} track(s) and fit {links} link(s)": "{cuts} şerit kes, {links} köprü tak",
    "Autoroute breadboard: {count} jumper(s)": "Breadboard'u otomatik kablola: {count} "
                                               "jumper",
    "Fit {count} jumper(s)": "{count} jumper tak",
    "Remove cut {id}": "{id} kesimini kaldır",
    "Set board to {cols}x{rows} {material}": "Kartı {cols} × {rows} {material} yap",
    "Use a {cols}x{rows} {material} board": "{cols} × {rows} {material} kart kullan",
    "Use a {points}-point breadboard": "{points} noktalı breadboard kullan",
    "Use a {points}-point solderable breadboard": "{points} noktalı lehimlenebilir breadboard kullan",
    "Use a {preset} board": "{preset} kart kullan",
    '{ref}: {hole} -> {to}, turned to {degrees} deg': '{ref}: {hole} → {to}, {degrees}° konumuna döndürüldü',
    '{ref}: {hole} -> {to}': '{ref}: {hole} → {to}',
    '... and {count} more': '... ve {count} tane daha',
    '{pin} ({net}) and {pin_b} ({net_b}) share the strip through {hole} and there is no free hole between them to cut. Move one of the parts.': '{pin} ({net}) ile {pin_b} ({net_b}), {hole} deliğinden geçen şeridi paylaşıyor ve aralarında kesilecek boş delik yok. Parçalardan birini taşıyın.',
    '{pin} ({net}) and {pin_b} ({net_b}) are in one clip, {hole} and {hole_b}: the breadboard joins them and nothing can be cut. Move one of the parts.': '{pin} ({net}) ile {pin_b} ({net_b}) aynı klipste, {hole} ve {hole_b}: breadboard onları birleştiriyor ve hiçbir şey kesilemez. Parçalardan birini taşıyın.',
    '{count} pin(s) of {net} could not be found on the board: the part is not placed, its footprint is not in the library, or the netlist names a pin the footprint does not have. Nothing was linked to them.': "{net} netinin {count} pini kartta "
                                                                                                                                                                                                                 "bulunamadı: parça yerleştirilmemiş, "
                                                                                                                                                                                                                 "kılıf kütüphanede yok ya da netlist "
                                                                                                                                                                                                                 "kılıfında olmayan bir pin adlandırıyor. "
                                                                                                                                                                                                                 "Onlara hiçbir şey bağlanmadı.",
    '{count} part(s) of {net} stand where the breadboard has no hole, so nothing was linked to them. Move them onto the holes.': "{net} netinin {count} parçası breadboard'un deliği olmayan bir yerinde duruyor, bu yüzden onlara hiçbir şey bağlanmadı. Onları deliklerin üzerine taşıyın.",
    '{pin} is in the {edge} {sign} rail at {hole}, which is for {netclass}, and this is a pin no net declares. Move the part off the rail.': '{pin}, {hole} deliğinde, {edge} {sign} rayında; bu ray {netclass} içindir, bu pin ise hiçbir netin bildirmediği bir pin. Parçayı raydan çıkarın.',
    '{pin} is in the {edge} {sign} rail at {hole}, which is for {netclass}, and this is a {netclass_b} net. Move the part off the rail.': '{pin}, {hole} deliğinde, {edge} {sign} rayında; bu ray {netclass} içindir, bu ise bir {netclass_b} neti. Parçayı raydan çıkarın.',
    'Part of {net} (at {holes}) cannot be reached: every hole of its clip already has a lead in it. Move a part so its clip has a hole free for a jumper.': '{net} netinin bir bölümüne ({holes}) ulaşılamıyor: klipsinin her deliğinde zaten bir bacak var. Klipste jumper için bir delik boşalsın diye bir parçayı taşıyın.',
    'No route found from {hole} to {to}. No wire is allowed by the current crossing policy, so only a solder trace was tried.': '{hole} ile {to} arasında yol bulunamadı. Geçerli kesişme ayarı tele izin vermiyor, bu yüzden yalnızca lehim yolu denendi.',
    'No route found from {hole} to {to}. Every strategy was blocked — try moving a part, or allow a top jumper.': "{hole} ile {to} arasında yol bulunamadı. Her yol tıkalıydı — bir parçayı taşımayı ya da üst yüz jumper'a izin vermeyi deneyin.",
    '{hole} has no pad to solder to — a mounting bore or an edge-connector finger is there. Move the part.': '{hole} deliğinde lehimlenecek ped yok — orada bir montaj deliği ya da kenar konnektörü parmağı var. Parçayı taşıyın.',
    'Endpoint is outside the board.': 'Uç kartın dışında.',
    'Start and end are the same hole.': 'Başlangıç ve bitiş aynı delik.',
    'The router found no route.': "Kablolama aracı bir yol bulamadı.",
    'Skipped {count} unconnected nets': '{count} bağlantısız net atlandı',
    'Skipped {count} unconnected net': '{count} bağlantısız net atlandı',
    "A printed legend needs at least one run, such as A-Z or 1-60.": (
        "Basılı bir numaralandırmanın en az bir dizisi olmalı, örneğin A-Z ya da 1-60."
    ),
    '"{piece}" is not a run: it needs a first label, as in A-Z.': (
        '"{piece}" bir dizi değil: bir ilk etiketle başlamalı, örneğin A-Z.'
    ),
    "{first}–{last} cannot be printed: it counts backwards.": (
        "{first}–{last} basılamaz: geriye doğru sayıyor."
    ),
    "{first}–{last} cannot be printed: a run is capital letters to capital letters (A–Z) "
    "or a number to a number (1–60), one kind to a run.": (
        "{first}–{last} basılamaz: bir dizi ya büyük harften büyük harfe (A–Z) ya da "
        "sayıdan sayıya (1–60) gider, ikisini karıştırmadan."
    ),
    # -- refusals, said where they are shown (engine_text) ---------------------------
    'Move refused: {reason}': 'Taşıma reddedildi: {reason}',
    # -- DRC and LVS findings, said where they are shown (engine_text) --------------
    '{ref} uses footprint "{footprint_id}", which is not in the library and cannot be generated, so it cannot be drawn or built.': "{ref} \"{footprint_id}\" kılıfını "
                                                                                                                                   "kullanıyor; bu kılıf kütüphanede yok ve "
                                                                                                                                   "üretilemiyor, bu yüzden ne çizilebilir "
                                                                                                                                   "ne yapılabilir.",
    'Component {ref} (anchored at {hole}) and {ref_b} (anchored at {hole_b}) have overlapping body outlines.': '{ref} ({hole} deliğinde) ile {ref_b} ({hole_b} deliğinde) parçalarının gövdeleri üst üste biniyor.',
    'Component {ref} (anchored at {hole}) and {ref_b} (anchored at {hole_b}) have overlapping bodies.': '{ref} ({hole} deliğinde) ile {ref_b} ({hole_b} deliğinde) parçalarının gövdeleri üst üste biniyor.',
    'Component {ref} (anchored at {hole}) and {ref_b} (anchored at {hole_b}) are {mm} mm apart, closer than the {mm_b} mm body clearance this design asks for.': '{ref} ({hole} deliğinde) ile {ref_b} ({hole_b} deliğinde) arasında {mm} mm var; bu tasarımın istediği {mm_b} mm gövde aralığından az.',
    'Component {ref} (anchored at {hole}) has a pin under the body of {ref_b} (anchored at {hole_b}).': '{ref} parçasının ({hole} deliğinde) bir bacağı {ref_b} parçasının ({hole_b} deliğinde) gövdesinin altında kalıyor.',
    'Component {ref} is {whole} off the board: {count} of its {total} pin hole(s) fall outside the {cols}x{rows} grid (e.g. {hole}).': '{ref} {whole} kartın dışında: {total} pin deliğinden {count} tanesi {cols}x{rows} ızgaranın dışına düşüyor (ör. {hole}).',
    'Component {ref} (anchored at {hole}) hangs {mm} mm past the {edges} of the board: its pins are in holes but part of its body is over nothing. {advice}': '{ref} ({hole} deliğinde) kartın {edges} {mm} mm taşıyor: pinleri deliklerde ama gövdesinin bir kısmı boşlukta. {advice}',
    'The part is larger than the board in that direction.': 'Parça o yönde karttan büyük.',
    'Moving it {count} hole(s) in from the {edges} clears it; a part overhanging on purpose -- a TO-220 reaching a heatsink off the edge -- can stay.': '{edges} {count} delik içeri almak sorunu çözer; bilerek taşan bir parça -- kart dışındaki soğutucuya uzanan bir TO-220 gibi -- kalabilir.',
    'Screw terminal {ref} (anchored at {hole}) takes its wires in from the {side}, and {names} {verb} in front of the entries ({ref_b} {mm} mm from them; a wire needs {mm_b} mm clear to go in straight). Turn {ref_c} to face a clear side -- a board edge is best -- or move what is in the way.': "{ref} klemensi ({hole} deliğinde) "
                                                                                                                                                                                                                                                                                                      "tellerini {side} taraftan alıyor ve "
                                                                                                                                                                                                                                                                                                      "girişlerin önünde {names} {verb} "
                                                                                                                                                                                                                                                                                                      "({ref_b} onlara {mm} mm uzakta; bir "
                                                                                                                                                                                                                                                                                                      "telin düz girmesi için {mm_b} mm boşluk "
                                                                                                                                                                                                                                                                                                      "gerekir). {ref_c} parçasını boş bir "
                                                                                                                                                                                                                                                                                                      "tarafa çevirin -- en iyisi kart kenarı "
                                                                                                                                                                                                                                                                                                      "-- ya da yoldakini taşıyın.",
    'Screw terminal {ref} (anchored at {hole}) stands on the {on} edge{plural} of the board but takes its wires in from the {side}: every wire has to come in from outside and double back over the board to reach it. Turn {ref_b} so its entries face the {edge} edge.': "{ref} klemensi ({hole} deliğinde) "
                                                                                                                                                                                                                                                                           "kartın {on} kenar{plural} duruyor ama "
                                                                                                                                                                                                                                                                           "tellerini {side} taraftan alıyor: her "
                                                                                                                                                                                                                                                                           "tel dışarıdan gelip kartın üstünden "
                                                                                                                                                                                                                                                                           "geri dönerek ona ulaşmak zorunda. "
                                                                                                                                                                                                                                                                           "{ref_b} parçasını girişleri {edge} "
                                                                                                                                                                                                                                                                           "kenara bakacak şekilde çevirin.",
    'Hole {hole} has more than one component pin landing on it: {names}.': '{hole} deliğine birden fazla parça pini düşüyor: {names}.',
    '{ref} ({archetype}, at {hole}) sits {mm} mm from {ref_b} ({archetype_b}, at {hole_b}), inside the {mm_b} mm heat clearance. An electrolytic loses roughly half its rated life for every 10 °C it runs hotter — move it, turn the tab away, or expect to replace it.': "{ref} ({archetype}, {hole} deliğinde) "
                                                                                                                                                                                                                                                                           "{ref_b} parçasına ({archetype_b}, "
                                                                                                                                                                                                                                                                           "{hole_b} deliğinde) {mm} mm uzakta; "
                                                                                                                                                                                                                                                                           "{mm_b} mm ısı mesafesinin içinde. Bir "
                                                                                                                                                                                                                                                                           "elektrolitik her 10 °C daha sıcak "
                                                                                                                                                                                                                                                                           "çalıştığında ömrünün kabaca yarısını "
                                                                                                                                                                                                                                                                           "kaybeder — onu taşıyın, soğutucu "
                                                                                                                                                                                                                                                                           "sırtını öbür yana çevirin ya da "
                                                                                                                                                                                                                                                                           "değiştirmeyi göze alın.",
    '{ref} ({footprint}, at {hole}) stands {mm} mm above the board, over the {mm_b} mm of clear height this build declares. Lay it down, choose a lower-profile part, or raise the limit if the case turned out to be deeper.': "{ref} ({footprint}, {hole} deliğinde) "
                                                                                                                                                                                                                                "karttan {mm} mm yükseliyor; bu yapının "
                                                                                                                                                                                                                                "belirttiği {mm_b} mm boş yüksekliğin "
                                                                                                                                                                                                                                "üstünde. Yatırın, daha alçak bir parça "
                                                                                                                                                                                                                                "seçin ya da kutu daha derin çıktıysa "
                                                                                                                                                                                                                                "sınırı yükseltin.",
    '{ref} ({mm} mm tall) sits under {ref_b}, whose board is {mm_b} mm up: fit it first; it cannot be reached afterwards without lifting the module.': "{ref} ({mm} mm boyunda) {ref_b} "
                                                                                                                                                       "modülünün altında kalıyor ve modülün "
                                                                                                                                                       "kartı {mm_b} mm yukarıda: önce onu "
                                                                                                                                                       "takın, çünkü sonradan modülü çıkarmadan "
                                                                                                                                                       "ona ulaşılamaz.",
    '{ref} extends under the {mm} mm screw head of mounting hole {mount} at {hole}. The screw cannot be fitted without pressing on the part.': '{ref}, {hole} deliğindeki {mount} montaj deliğinin {mm} mm vida başının altına uzanıyor. Vida parçaya bastırmadan takılamaz.',
    "Pin {pin_no} of {ref} (net '{net}') is not connected to anything: no conductor touches it and it shares no hole with another pin.": "{ref} parçasının {pin_no}. pini ('{net}' neti) hiçbir şeye bağlı değil: ona hiçbir iletken değmiyor ve başka bir pinle delik paylaşmıyor.",
    '{ref} pin {pin_no} sits at {hole}, where mounting hole {mount} has removed the pad. There is nothing there to solder to — move the part, or move the mounting hole.': "{ref} pin {pin_no}, {hole} deliğinde; "
                                                                                                                                                                           "orada {mount} montaj deliği pedi "
                                                                                                                                                                           "götürmüş. Lehimlenecek bir şey yok — "
                                                                                                                                                                           "parçayı ya da montaj deliğini taşıyın.",
    '{ref} pin {pin_no} sits at {hole}, which is part of edge connector {connector}. A finger is solid copper with no hole through it, so the lead cannot be fitted there — move the part, or shorten the connector.': "{ref} pin {pin_no}, {hole} deliğinde; "
                                                                                                                                                                                                                       "burası {connector} kenar konnektörünün "
                                                                                                                                                                                                                       "parçası. Parmak deliksiz düz bakırdır, "
                                                                                                                                                                                                                       "bacak oraya takılamaz — parçayı taşıyın "
                                                                                                                                                                                                                       "ya da konnektörü kısaltın.",
    '{ref} pin {pin_no} is at {hole}, where the breadboard has no hole — move the part onto the holes.': "{ref} pin {pin_no}, {hole} konumunda; "
                                                                                                         "breadboard'ın orada deliği yok — "
                                                                                                         "parçayı deliklerin üstüne taşıyın.",
    '{ref} pin {pin_no} sits at {hole}, where the track has been cut. The cut took the pad with it, so there is nothing there to solder to — move the part, or move the cut.': "{ref} pin {pin_no}, {hole} deliğinde, "
                                                                                                                                                                               "şeridin kesildiği yerde. Kesim pedi de "
                                                                                                                                                                               "götürdü, lehimlenecek bir şey yok — "
                                                                                                                                                                               "parçayı ya da kesimi taşıyın.",
    '{ref} pin {pin_no} is in the {rail} {sign} rail at {hole}, which is for {railclass}, and it is on {netwhat}. It works, but the board then says {sign_b} over it — move the part off the rail.': "{ref} pin {pin_no}, {hole} deliğinde, "
                                                                                                                                                                                                     "{rail} {sign} rayında; bu ray "
                                                                                                                                                                                                     "{railclass} için, pin ise {netwhat}. "
                                                                                                                                                                                                     "Çalışır ama kartın üstünde {sign_b} "
                                                                                                                                                                                                     "yazar — parçayı raydan çıkarın.",
    'Conductor {wire} is {whole} off the board: {count} of its {total} hole(s) fall outside the {cols}x{rows} grid (e.g. {hole}).': '{wire} iletkeni {whole} kartın dışında: {total} deliğinden {count} tanesi {cols}x{rows} ızgaranın dışına düşüyor (ör. {hole}).',
    'Conductor {wire} ({kind}) and conductor {wire_b} ({kind_b}) cross each other near {hole} on the {face} side, between holes rather than at one. Neither kind can cross: on perfboard they would touch and short. Reroute one of them, or make it an insulated wire — which may cross — or let the router lay an insulated hop just over the crossing.': "{wire} ({kind}) ile {wire_b} ({kind_b}) "
                                                                                                                                                                                                                                                                                                                                                            "iletkenleri {hole} yakınında, {face} "
                                                                                                                                                                                                                                                                                                                                                            "üzerinde, bir delikte değil delikler "
                                                                                                                                                                                                                                                                                                                                                            "arasında kesişiyor. İkisi de kesişemez: "
                                                                                                                                                                                                                                                                                                                                                            "perfboard'da birbirine değip kısa devre "
                                                                                                                                                                                                                                                                                                                                                            "yaparlar. Birini yeniden kablolayın, "
                                                                                                                                                                                                                                                                                                                                                            "izoleli tele çevirin — o kesişebilir — "
                                                                                                                                                                                                                                                                                                                                                            "ya da kablolama aracının kesişmenin "
                                                                                                                                                                                                                                                                                                                                                            "hemen üstüne izoleli bir köprü atmasına "
                                                                                                                                                                                                                                                                                                                                                            "izin verin.",
    'Conductor {wire} ({kind}) and conductor {wire_b} ({kind_b}) both occupy hole {hole} on the {face} side without being part of the same electrical net — this is a physical short. Reroute one of them, or replace it with an insulated conductor that can safely cross.': "{wire} ({kind}) ve {wire_b} ({kind_b}) "
                                                                                                                                                                                                                                                                              "iletkenleri {face} üzerinde aynı {hole} "
                                                                                                                                                                                                                                                                              "deliğini kullanıyor ama aynı elektrik "
                                                                                                                                                                                                                                                                              "netinde değiller — bu fiziksel bir kısa "
                                                                                                                                                                                                                                                                              "devre. Birini yeniden kablolayın ya da "
                                                                                                                                                                                                                                                                              "güvenle kesişebilen izoleli bir "
                                                                                                                                                                                                                                                                              "iletkenle değiştirin.",
    'Solder trace {wire} has an invalid path: {reason}': '{wire} lehim yolunun güzergâhı geçersiz: {reason}',
    'Conductor {wire} is a {kind} on the {face} side; on a solderless breadboard nothing is soldered and nothing runs underneath — use a jumper wire.': "{wire} iletkeni {face} üzerinde bir "
                                                                                                                                                        "{kind}; lehimsiz breadboard'da hiçbir "
                                                                                                                                                        "şey lehimlenmez ve altından bir şey "
                                                                                                                                                        "geçmez — bir atlama teli kullanın.",
    "Pure solder trace {wire} spans {count} pads on {board_material} (phenolic) board — beyond the {limit}-pad threshold. Phenolic pads lift under sustained soldering heat far more readily than FR-4; add a wire spine ('solder-trace-wired') or split the run.": "Saf lehim yolu {wire}, {board_material} "
                                                                                                                                                                                                                                                                    "(pertinaks) kartta {count} ped boyunca "
                                                                                                                                                                                                                                                                    "uzanıyor — {limit} pedlik eşiğin "
                                                                                                                                                                                                                                                                    "ötesinde. Pertinaks pedler uzun süren "
                                                                                                                                                                                                                                                                    "lehim ısısında FR-4'ten çok daha kolay "
                                                                                                                                                                                                                                                                    "kalkar; telli lehim yoluna çevirin "
                                                                                                                                                                                                                                                                    "('solder-trace-wired') ya da yolu bölün.",
    "Pure solder trace {wire} spans {count} pads, beyond the {limit}-pad feasibility threshold. Long pure-solder runs are mechanically unreliable and hard to reflow evenly; consider a wire spine ('solder-trace-wired').": "Saf lehim yolu {wire} {count} ped "
                                                                                                                                                                                                                             "boyunca uzanıyor; {limit} pedlik "
                                                                                                                                                                                                                             "uygulanabilirlik eşiğinin ötesinde. "
                                                                                                                                                                                                                             "Uzun saf lehim yolları mekanik olarak "
                                                                                                                                                                                                                             "güvenilmez ve eşit eritilmesi zordur; "
                                                                                                                                                                                                                             "telli lehim yolunu düşünün "
                                                                                                                                                                                                                             "('solder-trace-wired').",
    "{wirekind} {wire} is AWG {awg}{why}, {dia} mm of copper, and this board's holes are drilled {drill} mm: its ends will not go through them. Lap-solder it onto the pad faces instead, or bring this current onto the board on a terminal rated for it.": "{wirekind} {wire} AWG {awg}{why}, {dia} "
                                                                                                                                                                                                                                                             "mm bakır; bu kartın delikleri {drill} "
                                                                                                                                                                                                                                                             "mm delinmiş: uçları deliklerden geçmez. "
                                                                                                                                                                                                                                                             "Bunun yerine pedlerin yüzeyine "
                                                                                                                                                                                                                                                             "yatırarak lehimleyin ya da bu akımı "
                                                                                                                                                                                                                                                             "karta ona uygun bir klemensle getirin.",
    'Lead bend on {ref} pin {pin_no} spans {count} holes ({hole} to {hole_b}), beyond the {limit}-hole reliability threshold. A long bent lead is mechanically fragile — use a wire instead.': "{ref} pin {pin_no} üzerindeki bacak "
                                                                                                                                                                                               "bükme {count} delik boyunca uzanıyor "
                                                                                                                                                                                               "({hole}–{hole_b}); {limit} deliklik "
                                                                                                                                                                                               "güvenilirlik eşiğinin ötesinde. Uzun "
                                                                                                                                                                                               "bükülmüş bir bacak mekanik olarak "
                                                                                                                                                                                               "kırılgandır — bunun yerine tel kullanın.",
    'Conductor {wire} is soldered at {hole}, where mounting hole {mount} has removed the pad.': '{wire} iletkeni {hole} deliğinde lehimli; orada {mount} montaj deliği pedi götürmüş.',
    'Conductor {wire} is soldered at {hole}, which is part of edge connector {connector} and has no hole through it.': '{wire} iletkeni {hole} deliğinde lehimli; burası {connector} kenar konnektörünün parçası ve deliği yok.',
    'Conductor {wire} ends at {hole}, where the breadboard has no hole.': "{wire} iletkeni {hole} konumunda bitiyor; breadboard'ın orada deliği yok.",
    'Conductor {wire} is soldered at {hole}, where the track has been cut and the pad is gone.': '{wire} iletkeni {hole} deliğinde lehimli; orada şerit kesilmiş ve ped yok.',
    'Top jumper {wire} passes under {ref}, which is {height} and covers {hole}. Solder the jumper before fitting {ref_b}, or the part has to come off to reach it.': "Üst yüz jumper {wire}, {ref} altından "
                                                                                                                                                                     "geçiyor; o {height} ve {hole} deliğini "
                                                                                                                                                                     "örtüyor. Jumper'ı {ref_b} takılmadan "
                                                                                                                                                                     "önce lehimleyin, yoksa ona ulaşmak için "
                                                                                                                                                                     "parçayı sökmek gerekir.",
    '{wirekind} {wire} lies across {hole}, where {soldered} is soldered on another net. The netlist joins a wire only at its ends, but bare copper resting on a solder joint is a short at the bench. Route it clear of {hole_b}, or use insulated wire, which may pass over.': "{wirekind} {wire}, {hole} deliğinin "
                                                                                                                                                                                                                                                                                "üstünden geçiyor; orada başka bir nette "
                                                                                                                                                                                                                                                                                "{soldered} lehimli. Netlist bir teli "
                                                                                                                                                                                                                                                                                "yalnızca uçlarından bağlar ama bir "
                                                                                                                                                                                                                                                                                "lehim noktasına yaslanan çıplak bakır "
                                                                                                                                                                                                                                                                                "tezgâhta kısa devredir. Onu {hole_b} "
                                                                                                                                                                                                                                                                                "deliğinden uzak geçirin ya da üstten "
                                                                                                                                                                                                                                                                                "geçebilen izoleli tel kullanın.",
    'Solder trace {wire} passes through {hole}, whose orthogonal neighbour {hole_b} belongs to a different net (~{mm} mm of copper-to-copper gap {direction} on this board). Dragging solder along the trace risks bridging the two nets — the most common way a perfboard build fails. Verify clearance between {hole_c} and {hole_d} before soldering.': "Lehim yolu {wire}, {hole} deliğinden "
                                                                                                                                                                                                                                                                                                                                                           "geçiyor; dik komşusu {hole_b} başka bir "
                                                                                                                                                                                                                                                                                                                                                           "nete ait (bu kartta {direction} "
                                                                                                                                                                                                                                                                                                                                                           "bakırdan bakıra ~{mm} mm boşluk). "
                                                                                                                                                                                                                                                                                                                                                           "Lehimi yol boyunca sürüklemek iki neti "
                                                                                                                                                                                                                                                                                                                                                           "köprüleme riski taşır — perfboard "
                                                                                                                                                                                                                                                                                                                                                           "yapımının en sık bozulma yolu. "
                                                                                                                                                                                                                                                                                                                                                           "Lehimlemeden önce {hole_c} ile {hole_d} "
                                                                                                                                                                                                                                                                                                                                                           "arasındaki boşluğu ölçün.",
    "High voltage: net '{net}' ({volts} V) conductor {wire} runs through {hole}, directly next to {hole_b} on a different net. 2.54 mm hole spacing is near the practical creepage limit above {limit} V — increase clearance (skip a row/column) or reroute before building.": "Yüksek gerilim: '{net}' neti ({volts} "
                                                                                                                                                                                                                                                                                "V) iletkeni {wire}, {hole} deliğinden "
                                                                                                                                                                                                                                                                                "geçiyor ve başka bir netteki {hole_b} "
                                                                                                                                                                                                                                                                                "deliğinin hemen yanında. 2.54 mm delik "
                                                                                                                                                                                                                                                                                "aralığı {limit} V üstünde pratik yüzey "
                                                                                                                                                                                                                                                                                "kaçağı sınırına yakın — mesafeyi "
                                                                                                                                                                                                                                                                                "artırın (bir satır ya da sütun atlayın) "
                                                                                                                                                                                                                                                                                "ya da yapmadan önce yeniden kablolayın.",
    'Conductor(s) {wires} form an isolated island at {holes} with no component pin attached -- likely a stray solder trace, wire or bridge left over from editing.': 'Hiçbir parça pinine bağlı olmayan kopuk bir bakır adası: {wires}, {holes} üzerinde -- büyük olasılıkla düzenlemeden kalmış başıboş bir lehim yolu, tel ya da köprü.',
    'CRITICAL SHORT (power tied to ground): {where} ties together schematic nets {netnames} -- pins {pins}. This is almost certainly a solder bridge; separate the pads and re-measure isolation before applying power.': "KRİTİK KISA DEVRE (güç toprağa bağlı): "
                                                                                                                                                                                                                          "{where} şemadaki {netnames} netlerini "
                                                                                                                                                                                                                          "birleştiriyor -- pinler {pins}. Bu "
                                                                                                                                                                                                                          "neredeyse kesinlikle bir lehim köprüsü; "
                                                                                                                                                                                                                          "gücü vermeden önce pedleri ayırın ve "
                                                                                                                                                                                                                          "yalıtımı yeniden ölçün.",
    'SHORT: {where} ties together schematic nets {netnames} -- pins {pins}. This is almost certainly a solder bridge; separate the pads and re-measure isolation before applying power.': "KISA DEVRE: {where} şemadaki {netnames} "
                                                                                                                                                                                          "netlerini birleştiriyor -- pinler "
                                                                                                                                                                                          "{pins}. Bu neredeyse kesinlikle bir "
                                                                                                                                                                                          "lehim köprüsü; gücü vermeden önce "
                                                                                                                                                                                          "pedleri ayırın ve yalıtımı yeniden "
                                                                                                                                                                                          "ölçün.",
    "Net '{net}' references pin(s) {pins}, but component(s) {refs} are not placed on the board.": "'{net}' netinin bağlandığı {refs} henüz kartta yerleştirilmedi (pinler: {pins}).",
    "Net '{net}' references pin(s) {pins} on component(s) {refs}, whose footprint could not be resolved.": "'{net}' netinin bağlandığı {refs} için "
                                                                                                           "kılıf bulunamadı (pinler: {pins}).",
    "Net '{net}' is unrouted: all {count} of its pins are present on the board but none of them are connected to each other yet.": "'{net}' neti henüz kablolanmadı: "
                                                                                                                                   "{count} pininin hepsi kartta ama "
                                                                                                                                   "hiçbiri henüz birbirine bağlı değil.",
    "Net '{net}' is open: its pins are split across {count} separate physical connections instead of one -- {groups}.": "'{net}' neti açık: pinleri tek bir bağlantı yerine {count} ayrı fiziksel bağlantıya bölünmüş -- {groups}.",
    'entirely': 'tamamen',
    'partly': 'kısmen',
    'stands': 'duruyor',
    'stand': 'duruyor',
    'along the row': 'satır boyunca',
    'down the column': 'sütun boyunca',
    '{edge} edge, said from it': '{edge} kenarından',
    '{edges} edges, said from them': '{edges} kenarlarından',
    'on the edge: one': 'ında',
    'on the edge: several': 'larında',
    '{mm} mm tall': '{mm} mm yüksekliğinde',
    'a part whose height is not known': 'yüksekliği bilinmeyen bir parça',
    'on no net': 'hiçbir nette değil',
    'on a {netclass} net': 'bir {netclass} netinde',
    '(the gauge the cut list names for {amps} A)': '(kesim listesinin {amps} A için verdiği kalınlık)',
    'the end of {kind} {wire}': '{kind} {wire} ucu',
    'the physical connection at {hole}': '{hole} deliğindeki fiziksel bağlantı',
    'an unaddressable physical connection': 'adreslenemeyen bir fiziksel bağlantı',
    'and': 've',
    'near {hole}': '{hole} yakınında',
    'not connected to any other pin in this net': 'bu netteki başka hiçbir pine bağlı değil',
    'an unaddressable connection': 'adreslenemeyen bir bağlantı',
    "Net '{net}' declares {amps} A but solder trace {wire} ({buildup} buildup{spine}) has an estimated cross-section of {area} mm² (~{cap} A capacity at {density} A/mm²) — inadequate. Estimated resistance ~{mohm} mΩ over {length} mm, giving a ~{mv} mV drop at rated current.{recommendation}": "'{net}' neti {amps} A bildiriyor ama {wire} lehim yolunun ({buildup}{spine}) tahmini kesiti {area} mm² ({density} A/mm² ile ~{cap} A kapasite) — yetersiz. Tahmini direnç {length} mm boyunca ~{mohm} mΩ; anma akımında ~{mv} mV düşüm demek.{recommendation}",
    "Net '{net}' declares {amps} A but {wirelabel} {wire} {stated} {area} mm² (~{cap} A capacity at {density} A/mm²) — inadequate.{gauge_advice}": "'{net}' neti {amps} A bildiriyor ama {wirelabel} {wire} {stated} {area} mm² ({density} A/mm² ile ~{cap} A kapasite) — yetersiz.{gauge_advice}",
    'No hookup wire up to AWG {awg} carries that: split it across parallel runs, or bring this current onto the board on a terminal rated for it.': "AWG {awg} dahil hiçbir bağlantı teli "
                                                                                                                                                    "bunu taşımaz: birkaç paralel hatta "
                                                                                                                                                    "bölün ya da bu akımı karta ona uygun "
                                                                                                                                                    "bir klemensle getirin.",
    'Use AWG {awg} or heavier.': "AWG {awg} ya da daha kalın kullanın.",
    "Use AWG {awg} or heavier. AWG {awg_b} is {dia} mm of copper and will not go through this board's {drill} mm holes, so it has to be lap-soldered onto the pads or the current brought in on a terminal.": "AWG {awg} ya da daha kalın kullanın. "
                                                                                                                                                                                                              "AWG {awg_b} {dia} mm bakırdır ve bu "
                                                                                                                                                                                                              "kartın {drill} mm deliklerinden geçmez; "
                                                                                                                                                                                                              "pedlerin üstüne yatırılarak "
                                                                                                                                                                                                              "lehimlenmeli ya da akım bir klemensle "
                                                                                                                                                                                                              "getirilmeli.",
    'light buildup': 'az lehim',
    'normal buildup': 'normal lehim',
    'heavy buildup': 'bol lehim',
    ' + {mm} mm {material} spine': " + {mm} mm {material} tel",
    ' Adding a wire spine typically cuts this resistance by roughly an order of magnitude.': " Telli lehim yoluna çevirmek bu direnci "
                                                                                             "genellikle kabaca on kat düşürür.",
    'is AWG {awg},': 'AWG {awg},',
    'would be cut in AWG {awg}, the heaviest gauge this tool names,': 'bu aracın bildiği en kalın kalınlık olan AWG {awg} ile kesilirdi,',
    '{ref} is locked.': '{ref} kilitli.',
    'A component with ref "{ref}" is on the board.': '"{ref}" referanslı bir parça zaten kartta.',
    'A schematic part with ref "{ref}" is already in the design. Place that one instead, or give this a different reference.': '"{ref}" referanslı bir parça tasarımda zaten var. Onu yerleştirin ya da buna başka bir referans verin.',
    'A component with ref "{ref}" already exists.': '"{ref}" referanslı bir parça zaten var.',
    'Pin 1 of {ref} at {hole} is outside the {cols}x{rows} board.': '{ref} parçasının 1. pini {hole} deliğine düşüyor; bu delik {cols}x{rows} kartın dışında.',
    'Renaming to "{ref}" would put {pins} on two nets at once, because something already wired those pins under that reference.': '"{ref}" olarak adlandırmak {pins} pinlerini aynı anda iki nete koyar; o referansla bu pinlere zaten bağlantı yapılmış.',
    '{pin} already belongs to net "{net}". Disconnect it from there first -- a pin can only be on one net.': '{pin} zaten "{net}" netinde. Önce oradan ayır — bir pin yalnızca bir nette olabilir.',
    '{pin} is already on net "{net}".': '{pin} zaten "{net}" netinde.',
    'A net called "{name}" already exists.': '"{name}" adlı bir net zaten var.',
    'A net needs a name.': 'Bir netin adı olmalı.',
    'A part needs a reference designator.': 'Bir parçanın referansı olmalı.',
    'A component needs a non-empty reference.': 'Bir parçanın boş olmayan bir referansı olmalı.',
    '{a} and {b} are not on one net, so there is no connection between them to draw.': '{a} ile {b} aynı nette değil; aralarında çizilecek bir bağlantı yok.',
    'A wire has to go between two different pins.': 'Bir tel iki farklı pin arasında olmalı.',
    '{a} is an end of that wire already; a branch has to come from another pin.': '{a} zaten o telin bir ucu; dal başka bir pinden çıkmalı.',
    'No wire is drawn from {a} to {b} to branch off.': '{a} ile {b} arasında dal alınacak çizili bir tel yok.',
    'The wire from {a} to {b} no longer joins one net, so it is not drawn and nothing can branch off it.': '{a}–{b} teli artık tek bir neti birleştirmiyor; çizilmiyor ve ondan dal alınamaz.',
    'The track at {hole} is already cut.': '{hole} deliğindeki şerit zaten kesik.',
    'There is already a mounting hole at {hole}.': '{hole} deliğinde zaten bir montaj deliği var.',
    'A breadboard has no tracks to cut; its clips are fixed.': "Breadboard'da kesilecek şerit yok; klipsleri sabittir.",
    '{listed} would fall outside a {cols}x{rows} board.': '{listed}, {cols}x{rows} bir kartın dışında kalır.',
    'A board needs a name; it cannot be blank.': 'Kartın bir adı olmalı; boş bırakılamaz.',
    'A text note needs something in it.': 'Bir yazı notunun içinde bir şey olmalı.',
    'A label with nothing in it is an invisible thing on the board that still has to be found to be deleted.': 'İçi boş bir etiket, kartta görünmeyen ama silinmek için yine de bulunması gereken bir şeydir.',
    'Net "{name}" does not have pin(s) {pins}.': '"{name}" netinde {pins} yok.',
    "Drill 4 corner mounting holes ({mm} mm)": "Köşelere 4 montaj deliği del ({mm} mm)",
    "Drill {mm} mm mounting hole at {hole}": "{hole} deliğine {mm} mm montaj deliği del",
    "Drill {count} mounting holes": "{count} montaj deliği del",
    "Remove mounting hole {id}": "{id} montaj deliğini kaldır",
    "Add {count}-finger edge connector on the {edge} edge": "{edge} kenara {count} parmaklı kenar konnektörü ekle",
    "Remove edge connector {id}": "{id} kenar konnektörünü kaldır",
    "Limit build height to {mm} mm": "Montaj yüksekliğini {mm} mm ile sınırla",
    "Remove the build height limit": "Montaj yüksekliği sınırını kaldır",
    "Judge parts by their bodies, {mm} mm apart": "Parçaları gövdelerine göre ölç ({mm} mm aralık)",
    "Judge parts by their courtyards": "Parçaları güvenlik paylarına göre ölç",
    "Name the board {name}": "Karta {name} adını ver",
    "Write “{text}” on the board at {hole}": "Karta, {hole} deliğine “{text}” yaz",
    "Edit a label on the board": "Karttaki bir etiketi düzenle",
    "Delete {count} label(s) from the board": "Karttan {count} etiketi sil",
    "Delete {ref}": "{ref} parçasını sil",
    "Update {ref}": "{ref} parçasını güncelle",
    'Placement unchanged ({movable} movable part, {moves} moves tried) — nothing found would be cheaper to build than the board you have ({cost} against {other})': 'Yerleşim değişmedi ({movable} taşınabilir parça, {moves} hamle denendi) — elinizdeki karttan daha ucuza kurulacak bir düzen bulunamadı (sizinki {cost}, en iyi aday {other})',
    'Placement unchanged ({movable} movable parts, {moves} moves tried) — nothing found would be cheaper to build than the board you have ({cost} against {other})': 'Yerleşim değişmedi ({movable} taşınabilir parça, {moves} hamle denendi) — elinizdeki karttan daha ucuza kurulacak bir düzen bulunamadı (sizinki {cost}, en iyi aday {other})',
    'Placement unchanged ({movable} movable part, {moves} moves tried)': 'Yerleşim değişmedi ({movable} taşınabilir parça, {moves} hamle denendi)',
    'Placement unchanged ({movable} movable parts, {moves} moves tried)': 'Yerleşim değişmedi ({movable} taşınabilir parça, {moves} hamle denendi)',
    '{count} part placed': '{count} parça yerleşti',
    '{count} parts placed': '{count} parça yerleşti',
    "{count} turned": "{count} tanesi döndü",
    "~{mm} mm less connection length": "bağlantı uzunluğu ~{mm} mm kısaldı",
    "~{mm} mm more connection length": "bağlantı uzunluğu ~{mm} mm uzadı",
    "about the same connection length": "bağlantı uzunluğu hemen hemen aynı",
    '{count} overlap cleared': '{count} çakışma giderildi',
    '{count} overlaps cleared': '{count} çakışma giderildi',
    '{count} part brought back over the board': '{count} parça kartın üstüne geri getirildi',
    '{count} parts brought back over the board': '{count} parça kartın üstüne geri getirildi',
    '{count} blocked wire entry cleared': 'kapalı {count} tel girişi açıldı',
    '{count} blocked wire entries cleared': 'kapalı {count} tel girişi açıldı',
    '{count} terminal turned to face their edge': '{count} klemens kenarına bakacak şekilde döndü',
    '{count} terminals turned to face their edge': '{count} klemens kenarına bakacak şekilde döndü',
    '{count} hot pair moved apart': 'ısınan {count} parça çifti birbirinden uzaklaştırıldı',
    '{count} hot pairs moved apart': 'ısınan {count} parça çifti birbirinden uzaklaştırıldı',
    '{count} part moved out from under a module': '{count} parça bir modülün altından çıkarıldı',
    '{count} parts moved out from under a module': '{count} parça bir modülün altından çıkarıldı',
    '{count} part moved out from under a screw head': '{count} parça vida başının altından çıkarıldı',
    '{count} parts moved out from under a screw head': '{count} parça vida başının altından çıkarıldı',
    'wiring cost {cost}': 'kablolama maliyeti {cost}',
    '{made} connection wired across {closed}/{considered} nets': '{closed}/{considered} nette {made} bağlantı kablolandı',
    '{made} connections wired across {closed}/{considered} nets': '{closed}/{considered} nette {made} bağlantı kablolandı',
    '{count} could not be wired': '{count} tanesi kablolanamadı',
    "{count} needed an insulated wire or jumper": "{count} tanesi izoleli tel ya da jumper istedi",
    '{count} pad to measure for isolation': 'yalıtımı ölçülecek {count} ped',
    '{count} pads to measure for isolation': 'yalıtımı ölçülecek {count} ped',
    '{count} wiring orders tried': '{count} kablolama sırası denendi',
    '{count} old conductor removed': '{count} eski iletken kaldırıldı',
    '{count} old conductors removed': '{count} eski iletken kaldırıldı',
    '{count} connection wired again': '{count} bağlantı yeniden kablolandı',
    '{count} connections wired again': '{count} bağlantı yeniden kablolandı',
    '{count} conductor now': 'şimdi {count} iletken',
    '{count} conductors now': 'şimdi {count} iletken',
    "Nothing to do: every net is already right on this board.": "Yapılacak bir şey yok: bu karttaki her net zaten doğru.",
    '{count} cut': '{count} kesim',
    '{count} cuts': '{count} kesim',
    '{count} link': '{count} köprü',
    '{count} links': '{count} köprü',
    '{count} jumper': '{count} jumper',
    '{count} jumpers': '{count} jumper',
    "line": "çizgi",
    "rectangle": "dikdörtgen",
    "circle": "daire",
    "text": "metin",
    "left": "sol",
    "right": "sağ",
    "top": "üst",
    "bottom": "alt",
    "paste": "yapıştırın",
    "duplicate": "çoğaltın",
}

CATALOGUES: Mapping[str, Mapping[str, str]] = {"tr": TURKISH}

_language = "en"


def set_language(language: str | None) -> str:
    """Choose the interface language, returning the one actually in force.

    ``None`` means "work it out": PERFBOARD_STUDIO_LANG first, then the system locale, then
    English. An unknown language falls back to English rather than failing, because a
    misspelled environment variable should not stop the application starting.
    """
    global _language
    wanted = (language or _detect() or "en").lower().split("_")[0].split("-")[0]
    _language = wanted if wanted in AVAILABLE else "en"
    return _language


def language() -> str:
    return _language


def _detect() -> str | None:
    from_env = os.environ.get("PERFBOARD_STUDIO_LANG")
    if from_env:
        return from_env
    import locale

    try:
        code, _encoding = locale.getlocale()
    except ValueError:  # pragma: no cover - malformed locale on the host
        return None
    return code


def counted(count: int, one: str, many: str) -> str:
    """``one`` or ``many`` -- each already through ``t()``, so the catalogue scan sees both --
    with the count in it. "3 part(s)" read like a machine. English needs the two forms;
    Turkish says the singular after a number, so its two entries are the same words."""
    return (one if count == 1 else many).format(count=count)


def t(text: str) -> str:
    """Translate one interface string, or return it unchanged.

    Deliberately falls through rather than marking a missing translation: a
    half-translated interface is usable, and a placeholder in the middle of a menu is
    not.
    """
    catalogue = CATALOGUES.get(_language)
    if catalogue is None:
        return text
    return catalogue.get(text, text)


__all__ = ["AVAILABLE", "CATALOGUES", "TURKISH", "language", "set_language", "t"]
