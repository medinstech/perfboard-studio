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
    "1:1 &PDF (component side + solder side)…": "1:1 &PDF (parça + lehim yüzü)…",
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
    "The same layout on a solderable breadboard: {parts} and {wires}, each on the holes it had.": "Aynı yerleşim lehimlenebilir bir breadboard'da: {parts} ve {wires}, her biri eski deliklerinde.",
    "{count} part waiting in the design: choose the board it goes on.": (
        "Tasarımda {count} parça bekliyor: hangi karta gideceğini seçin."
    ),
    "{count} parts waiting in the design: choose the board they go on.": (
        "Tasarımda {count} parça bekliyor: hangi karta gideceklerini seçin."
    ),
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
    "Tinned wire on the solder side. Cannot cross other copper. Click where it starts "
    "and wherever it turns; Enter, right-click or a double-click finishes.": (
        "Lehim yüzünde kalaylı tel. Başka bakırın üzerinden geçemez. Başladığı ve döndüğü "
        "yerlere tıklayın; Enter, sağ tık ya da çift tık bitirir."
    ),
    "May cross anything, at the cost of stripping it. Click where it starts and wherever "
    "it turns; Enter, right-click or a double-click finishes.": (
        "Her şeyin üzerinden geçebilir; bedeli uçlarını soymaktır. Başladığı ve döndüğü "
        "yerlere tıklayın; Enter, sağ tık ya da çift tık bitirir."
    ),
    "An insulated wire on the component side, hopping over everything below. It takes room "
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
    "Wire on Both &Faces": "İki Y&üzde Kablola",
    "Wire on Both Faces laid nothing on the component side, where no net came out "
    "shorter: a net's Face set to Component Side puts it there": (
        "İki Yüzde Kablola parça yüzüne hiçbir şey döşemedi, orada daha kısa çıkan net "
        "olmadı: bir netin Yüzünü Parça Yüzü yapmak onu oraya koyar"
    ),
    "{count} via": "{count} via",
    "{count} vias": "{count} via",
    "Via": "Via",
    "Joins the other face at {holes}": "{holes} deliğinde öbür yüze bağlanır",
    "Joins the other face at the holes {holes}": "{holes} deliklerinde öbür yüze bağlanır",
    "Every net may use the component side too, changing face through a pad with no pin where that is shorter. Off, the wiring stays on the solder side, except a net whose Face is the component side.": (
        "Her net parça yüzünü de kullanabilir; daha kısaysa pimsiz bir pedden yüz "
        "değiştirir. Kapalıyken kablolama lehim yüzünde kalır; Yüzü parça yüzü olan netler "
        "bunun dışındadır."
    ),
    "This board has no copper on the component side.": "Bu kartın parça yüzünde bakır yok.",
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
    "Flip Board (component side / solder side)": "Kartı Çevir (parça yüzü / lehim yüzü)",
    "&Fit Board": "Karta &Sığdır",
    "Zoom &In": "&Yakınlaştır",
    "Zoom &Out": "&Uzaklaştır",
    "Show &Missing Connections": "Eksik &Bağlantıları Göster",
    "Show Hole &Addresses": "Delik &Adreslerini Göster",
    "&Copper on the Far Side": "Karşı &Yüzdeki Bakır",
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
    "Read what this release changes.": "Bu sürümün neleri değiştirdiğini okuyun.",
    "What Changed in {version}": "{version} sürümünde ne değişti",
    "This release carries no notes.": "Bu sürümün notu yok.",
    "Open on GitHub": "GitHub'da Aç",
    "Open this release's page in your browser.":
        "Bu sürümün sayfasını tarayıcınızda açar.",
    "Install and Restart": "Kur ve Yeniden Başlat",
    "Update {version}": "Güncelleme {version}",
    "Perfboard Studio {version} is available. Click to read what changed.":
        "Perfboard Studio {version} çıktı. Neler değiştiğini okumak için tıklayın.",
    "Close this window (asking about unsaved work), run the installer — Windows "
    "asks for permission — and open the new version.":
        "Bu pencereyi kapatır (kaydedilmemiş iş varsa sorar), kurulum dosyasını "
        "çalıştırır — Windows izin ister — ve yeni sürümü açar.",
    "The update is downloaded and its checksum matched.":
        "Güncelleme indirildi ve sağlama toplamı tuttu.",
    "Install and Restart closes this window, asking about unsaved work, runs "
    "the installer and opens the new version.":
        "Kur ve Yeniden Başlat bu pencereyi kapatır, kaydedilmemiş iş varsa sorar, "
        "kurulum dosyasını çalıştırır ve yeni sürümü açar.",
    "The update was not installed.": "Güncelleme kurulmadı.",
    "The installer is no longer where it was saved.":
        "Kurulum dosyası kaydedildiği yerde artık yok.",
    "Could not read the installer: {error}": "Kurulum dosyası okunamadı: {error}",
    "The installer changed after it was checked, so it was deleted and "
    "nothing was installed.":
        "Kurulum dosyası denetlendikten sonra değişmiş, o yüzden silindi ve hiçbir "
        "şey kurulmadı.",
    "Windows did not give permission, so nothing was installed.":
        "Windows izin vermedi, o yüzden hiçbir şey kurulmadı.",
    "The installer could not be started: {error}":
        "Kurulum dosyası başlatılamadı: {error}",
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
    "click both ends or drag from one to the other, Esc cancels": (
        "iki ucu da tıklayın ya da birinden ötekine sürükleyin, Esc iptal eder"
    ),
    "click where it turns or drag pad to pad, Enter or right-click finishes, / flips the corner, Esc cancels": (
        "döndüğü yere tıklayın ya da pedden pede sürükleyin, Enter veya sağ tık bitirir, / "
        "köşeyi çevirir, Esc iptal eder"
    ),
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
    "{count} part in the design is not on the board yet: Place on the Board puts it there.": "Tasarımdaki {count} parça henüz kartta değil: Karta Yerleştir onu oraya koyar.",
    "{count} parts in the design are not on the board yet: Place on the Board puts them there, arranged.": "Tasarımdaki {count} parça henüz kartta değil: Karta Yerleştir onları dizerek oraya koyar.",
    "Copied {parts}, {conductors}": "{parts}, {conductors} kopyalandı",
    "{count} conductor": "{count} iletken",
    "{count} conductors": "{count} iletken",
    "{count} lead bend left behind: a bent leg belongs to a part that was not in the selection": "{count} bacak bükme geride kaldı: bükülen bacak, seçimde olmayan bir parçanın",
    "{count} lead bends left behind: a bent leg belongs to a part that was not in the selection": "{count} bacak bükme geride kaldı: bükülen bacak, seçimde olmayan bir parçanın",
    "Pasted {parts} and {conductors} at {hole}": "{parts} ve {conductors} {hole} deliğine yapıştırıldı",
    "Duplicated {parts} and {conductors} at {hole}": "{parts} ve {conductors} {hole} deliğine çoğaltıldı",
    "{count} conductor would have run off the board": "{count} iletken kartın dışına taşacaktı",
    "{count} conductors would have run off the board": "{count} iletken kartın dışına taşacaktı",
    "{ref} at {hole}": "{ref}, {hole} deliğinde",
    "untitled": "adsız",
    "{path} is a directory, not a .perf document.": "{path} bir klasör, .perf belgesi değil.",
    "Cannot open {path}: {reason}.": "{path} açılamıyor: {reason}.",
    "Cannot open {path}: not UTF-8 text. A .perf document is JSON.":
        "{path} açılamıyor: UTF-8 metin değil. Bir .perf belgesi JSON'dur.",
    "{count} conductor is now out of date; Ctrl+R clears and rewires it":
        "{count} iletken eskidi; Ctrl+R temizler ve yeniden kablolar",
    "{count} conductors are now out of date; Ctrl+R clears and rewires them":
        "{count} iletken eskidi; Ctrl+R temizler ve yeniden kablolar",
    "{count} out-of-date conductor removed first": "önce {count} eskimiş iletken kaldırıldı",
    "{count} out-of-date conductors removed first": "önce {count} eskimiş iletken kaldırıldı",
    "“{style}” beat {count} other style": "“{style}” diğer {count} stilden iyi çıktı",
    "“{style}” beat {count} other styles": "“{style}” diğer {count} stilden iyi çıktı",
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
    "Written to {folder}, with {count} thing it could not cover:": "{folder} klasörüne yazıldı; kapsayamadığı {count} şey var:",
    "Written to {folder}, with {count} things it could not cover:": "{folder} klasörüne yazıldı; kapsayamadığı {count} şey var:",
    "Could not write the schematic: {err}": "Şema yazılamadı: {err}",
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
    "{ref} is on another board: {board}.": "{ref} başka bir kartta: {board}.",
    # The board strip and the System view (reach's words).
    "System": "Sistem",
    "+ Add Board": "+ Kart Ekle",
    "&Add Board": "Kart &Ekle",
    "Another board in this document, for a circuit built on more than one: the circuit stays "
    "one, and a cable joins a connector on one board to one on the other.": (
        "Bu belgede bir kart daha, birden çok karta kurulan bir devre için: devre tek kalır, "
        "bir kablo bir karttaki konnektörü ötekindekine bağlar."
    ),
    "second board, several boards, system": "ikinci kart, birden çok kart, sistem",
    "Click a board or a cable to see it in Properties; double-click a board to open it.":
        "Özellikler'de görmek için bir karta ya da kabloya tıklayın; açmak için bir karta "
        "çift tıklayın.",
    # Properties with System in front: the system, a board picked on it, a cable.
    "This board's name among the others: on the strip, in System, on the harness and on "
    "its build guide. Left empty, it is called by its place.":
        "Bu kartın diğerleri arasındaki adı: şeritte, Sistem'de, kablo demetinde ve kendi "
        "montaj kılavuzunda. Boş bırakılırsa sırasındaki yerle anılır.",
    "The name of the whole document: its file, its project and every board's guide.":
        "Belgenin tamamının adı: dosyası, projesi ve her kartın kılavuzu.",
    "Contents": "İçerik",
    "Add Board": "Kart Ekle",
    "Add Cable…": "Kablo Ekle…",
    "Click a board or a cable to see it here.":
        "Burada görmek için bir karta ya da kabloya tıklayın.",
    "Open": "Aç",
    "This board in front, to place and wire it.":
        "Parça yerleştirip kablolamak için bu kartı öne getirir.",
    "Remove Board": "Kartı Kaldır",
    "Take this board out of the document. Its parts go back to the design, wired as they "
    "were. A cable that reaches it has to be removed first.":
        "Bu kartı belgeden çıkarır. Parçaları bağlantıları korunarak tasarıma geri döner. "
        "Bu karta ulaşan bir kablo varsa önce o kaldırılmalıdır.",
    "What the harness and the cut list call this cable.":
        "Kablo demetinin ve kesim listesinin bu kabloya verdiği ad.",
    "Pin to pin": "Pinden pine",
    "Not given": "Verilmedi",
    "How long to cut it, end to end; the guide adds what is stripped. Not given, the guide "
    "leaves the length to you.":
        "Uçtan uca kesim uzunluğu; soyulacak kısmı kılavuz ekler. Verilmezse uzunluğu "
        "kılavuz size bırakır.",
    "Anything the builder should know about this cable.":
        "Kabloyu yapacak kişinin bilmesi gereken her şey.",
    "Remove Cable": "Kabloyu Kaldır",
    "No wires": "Tel yok",
    "{board} has nothing on it yet": "{board} üzerinde henüz bir şey yok",
    "Drag a part here from the Library or the schematic, or right-click a part on another "
    "board: Move to Board.":
        "Kütüphaneden ya da şemadan buraya bir parça sürükleyin veya başka bir karttaki bir "
        "parçaya sağ tıklayın: Karta Taşı.",
    "A cable then joins the boards: Board > Add Cable.":
        "Ardından kartları bir kablo birleştirir: Kart > Kablo Ekle.",
    "The 3D View shows the board in front.": "3D Görünüm, öndeki kartı gösterir.",
    "{count} board": "{count} kart",
    "{count} boards": "{count} kart",
    "{count} cable": "{count} kablo",
    "{count} cables": "{count} kablo",
    "{ref} is {length} mm; its ends are {span} mm apart in this row": (
        "{ref} {length} mm; bu dizilişte uçları arası {span} mm"
    ),
    # A board's own command done on one board of several (``board.on``'s undo label), and a
    # board nobody named, as the phrasebook calls it.
    "{what} on {board}": "{what} ({board})",
    # Add Cable, in reach's words.
    "Add &Cable…": "&Kablo Ekle…",
    "A cable from a connector on one board to a connector on another. Its wires are paired "
    "by net: a pin of each on the same net takes a wire, and what is not certain is left "
    "for you and said.": (
        "Bir karttaki konnektörden başka bir karttaki konnektöre giden kablo. Telleri nete "
        "göre eşlenir: iki uçta aynı nette olan pinler birer tel alır; kesin olmayan "
        "eşleşmeler size bırakılır ve söylenir."
    ),
    "harness, wire between boards, connect boards": "kablo demeti, kartlar arası tel, kartları bağla",
    "A cable joins two boards: add a board first.": "Kablo iki kartı bağlar: önce bir kart ekleyin.",
    "Add Cable": "Kablo Ekle",
    "From": "Nereden",
    "To": "Nereye",
    "Length": "Uzunluk",
    "cut to fit": "ölçüye göre",
    "Choose a connector at each end.": "Her iki uç için bir konnektör seçin.",
    "{count} wire, paired by net:": "Nete göre eşlenen {count} tel:",
    "{count} wires, paired by net:": "Nete göre eşlenen {count} tel:",
    "Not paired:": "Eşlenmeyenler:",
    "{count} pin left unpaired": "{count} pin eşlenmedi",
    "{count} pins left unpaired": "{count} pin eşlenmedi",
    "Add a board": "Kart ekle",
    "Add the board '{boardname}'": "'{boardname}' kartını ekle",
    "Name the board '{boardname}'": "Kartın adını '{boardname}' yap",
    "Unname {board}": "Kartın adını kaldır ({board})",
    "Remove the board '{board}'": "Kartı çıkar ({board})",
    "Add the cable {ref}": "{ref} kablosunu ekle",
    "Change the cable {ref}": "{ref} kablosunu değiştir",
    "Remove the cable {ref}": "{ref} kablosunu çıkar",
    # Move to Board, in reach's words: the boards in a submenu, so a name stands alone.
    "Move to &Board": "Karta &Taşı",
    "Wire it again: {board}.": "Yeniden kablolayın: {board}.",
    "Move {ref} to the board {board}": "{ref} parçasını başka karta taşı: {board}",
    "taking off {count} conductor that ran to it": "ona giden {count} iletken kaldırıldı",
    "taking off {count} conductors that ran to it": "ona giden {count} iletken kaldırıldı",
    "Board {n}": "Kart {n}",
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
    "{count} pin in a used hole": "{count} pin dolu bir delikte",
    "{count} pins in a used hole": "{count} pin dolu bir delikte",
    "{count} pin where there is no pad": "{count} pin pedi olmayan bir yerde",
    "{count} pins where there is no pad": "{count} pin pedi olmayan bir yerde",
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
    "Copper hidden under a part": "Parçanın altında kalan bakır",
    "Solder where the board has no pads": "Pedi olmayan yüzde lehim",
    "Rail with no bridge to the board": "Karta köprüsü olmayan ray",
    "Gap too wide for plain solder": "Telsiz lehim yolu için fazla geniş boşluk",
    "Copper at a pin under its own part": "Gövdesinin altında kalan pinde bakır",
    "Joint under its own part": "Lehim noktası parçanın altında",
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
    "Apply this placement?": "Bu yerleşim uygulansın mı?",
    "Redo the wiring?": "Kablolama yeniden yapılsın mı?",
    "Redo Wiring": "Kablolamayı Yeniden Yap",
    # Hand copper: what the step being drawn would do, what was drawn, what went.
    "{hole}: this would join {a} to {b}, a short": "{hole}: bu, {a} ile {b} netlerini birleştirir; kısa devre",
    "{hole}: this would cross {other}, and they would touch": "{hole}: bu, {other} ile kesişir ve birbirlerine değerler",
    "{hole}: this would lie on {joint}, another net's joint": "{hole}: bu, başka bir netin lehim noktası olan {joint} üzerine yatar",
    "{hole}: this runs along {other}": "{hole}: bu, {other} boyunca uzanır",
    "Drew {what}": "{what} çizildi",
    "Extended {what}": "{what} uzatıldı",
    "Reshaped {what}": "{what} yeniden biçimlendirildi",
    "on {net}": "{net} netinde",
    "not on any net yet": "henüz hiçbir nette değil",
    "it joins {a} to {b} at {hole}, a short. Ctrl+Z takes it back.": (
        "{hole} deliğinde {a} ile {b} netlerini birleştiriyor, bu bir kısa devre. Ctrl+Z ile "
        "geri alabilirsiniz."
    ),
    "it crosses {other} near {hole}, and they would touch. Ctrl+Z takes it back.": (
        "{hole} deliği yakınında {other} ile kesişiyor ve birbirlerine değerler. Ctrl+Z ile "
        "geri alabilirsiniz."
    ),
    "it lies on {joint} at {hole}, another net's joint. Ctrl+Z takes it back.": (
        "{hole} deliğinde başka bir netin lehim noktası olan {joint} üzerine yatıyor. Ctrl+Z "
        "ile geri alabilirsiniz."
    ),
    "it runs along {other} from {hole}.": "{hole} deliğinden itibaren {other} boyunca uzanıyor.",
    "{other} already lies here: Enter adds nothing": (
        "{other} zaten burada: Enter hiçbir şey eklemez"
    ),
    "Already joined by {other}: nothing added": "Zaten {other} ile bağlı: hiçbir şey eklenmedi",
    "{count} pad": "{count} ped",
    "{count} pads": "{count} ped",
    "past {limit} pads Shift+T lays it with a wire in it": (
        "{limit} pedden uzun: Shift+T içine tel koyarak döşer"
    ),
    "{which} of {count} here · click again for the next": (
        "Üst üste {count} iletken: seçili olan {which}. · Sıradaki için yeniden tıklayın"
    ),
    "Deleted {what} · Ctrl+Z brings it back": "{what} silindi · Ctrl+Z ile geri getirebilirsiniz",
    "Deleted {count} conductors · Ctrl+Z brings them back": "{count} iletken silindi · Ctrl+Z ile geri getirebilirsiniz",
    "Select All of {net}": "{net} Netinin Tümünü Seç",
    "Redo Wiring of {net}": "{net} Kablolamasını Yeniden Yap",
    "Remove Wiring of {net}": "{net} Kablolamasını Kaldır",
    "Remove Wiring of {count} Nets": "{count} Netin Kablolamasını Kaldır",
    "{net} has no wiring to remove.": "{net} için kaldırılacak kablolama yok.",
    "Removed the wiring of {net} · Ctrl+Z brings it back": "{net} kablolaması kaldırıldı · Ctrl+Z ile geri getirebilirsiniz",
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
    "component side": "parça yüzü",
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
    "{count} conductor on them goes and is planned again; copper with no net assigned is left alone. One Ctrl+Z puts it all back.": "Üzerlerindeki {count} iletken kaldırılıp yeniden planlanır; neti olmayan bakıra dokunulmaz. Tek Ctrl+Z hepsini geri alır.",
    "{count} conductors on them go and are planned again; copper with no net assigned is left alone. One Ctrl+Z puts it all back.": "Üzerlerindeki {count} iletken kaldırılıp yeniden planlanır; neti olmayan bakıra dokunulmaz. Tek Ctrl+Z hepsini geri alır.",
    "Locked": "Kilitli",
    "Kind": "Tür",
    "Type what the part is; Enter puts it on the sheet.": (
        "Parçanın ne olduğunu yazın; Enter onu şemaya koyar."
    ),
    "Holes": "Delikler",
    "Lies across": "Üzerinden geçtiği",
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
    "Its {count} lead bend was bent to this package's pins and goes with it.": "{count} bacak bükümü bu gövdenin pinlerine göre bükülmüştü; onunla birlikte kalkar.",
    "Its {count} lead bends were bent to this package's pins and go with it.": "{count} bacak bükümü bu gövdenin pinlerine göre bükülmüştü; onunla birlikte kalkar.",
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
    "Remove &Line Only": "Yalnızca Çizgiyi &Kaldır",
    "{pin} left {net}": "{pin}, {net} netinden ayrıldı",
    "The pins stay joined by other wires": "Pinler başka tellerle bağlı kalır",
    "{said}. Ctrl+Z brings the wire back.": "{said}. Ctrl+Z teli geri getirir.",
    "Wire rubbed out. The pins stay connected, by name; Ctrl+Z brings it back.": (
        "Tel silindi. Pinler adla bağlı kalır; Ctrl+Z teli geri getirir."
    ),
    "Take the line off the sheet. The pins stay connected — the net says so by "
    "name instead.": (
        "Çizgiyi sayfadan kaldırır. Pinler bağlı kalır — net bunu artık adıyla söyler."
    ),
    "Re&name Net…": "Neti Yeniden Adlandı&r…",
    "A new name. The pins on it, and any copper laid for it, stay.": (
        "Yeni bir ad. Üzerindeki pinler ve onun için döşenmiş bakır yerinde kalır."
    ),
    "Net &Class": "Net &Sınıfı",
    "Net &Face": "Net &Yüzü",
    "Either": "Fark Etmez",
    "&Either": "&Fark Etmez",
    "Component Side": "Parça Yüzü",
    "&Component Side": "&Parça Yüzü",
    "Solder Side": "Lehim Yüzü",
    "&Solder Side": "&Lehim Yüzü",
    "Draw on:": "Çizilen yüz:",
    "Make This Strip a Rail": "Bu Şeridi Ray Yap",
    "Make This Strip a Rail…": "Bu Şeridi Ray Yap…",
    "Solder along these fingers, bridged to the holes beside them: one net down the side of the board, the way ground and power are run.": (
        "Bu parmaklar boyunca lehim; yanlarındaki deliklere köprülerle bağlanır: kartın "
        "kenarı boyunca tek bir net, toprak ve beslemenin döşendiği gibi."
    ),
    "Solder along the outside fingers, joined to the holes beside them by bridges: how ground and power are run on a stock board.": (
        "Dıştaki parmaklar boyunca lehim, yanlarındaki deliklere köprülerle bağlanır: hazır "
        "kartlarda toprak ve besleme böyle döşenir."
    ),
    "No net": "Net yok",
    "Bridges": "Köprüler",
    "Each bridge is laid over a wire: the gap to the finger is wider than solder spans.": (
        "Her köprü bir telin üzerine döşenir: parmağa olan boşluk, lehimin aşabileceğinden "
        "geniştir."
    ),
    "A rail with no bridge carries nothing: tick at least one bridge to lay it.": (
        "Köprüsü olmayan ray hiçbir şey taşımaz: döşemek için en az bir köprü işaretleyin."
    ),
    "Lay the Rail": "Rayı Döşe",
    "{hole} to {finger}": "{hole} deliğinden {finger} parmağına",
    "Lay a rail {start}–{end}": "{start}–{end} rayını döşe",
    "A rail needs two fingers, or at least one bridge.": (
        "Bir ray için iki parmak ya da en az bir köprü gerekir."
    ),
    "The rail was not laid: {why}": "Ray döşenmedi: {why}",
    "The rail {span} is laid. One Ctrl+Z takes it up.": (
        "{span} rayı döşendi. Tek bir Ctrl+Z ile geri alabilirsiniz."
    ),
    "What you draw goes on the solder side, under the board. Turning the board over (Ctrl+F) chooses the face again.": (
        "Çizdiğiniz bakır, kartın altındaki lehim yüzüne gider. Kartı çevirdiğinizde "
        "(Ctrl+F) yüz yeniden seçilir."
    ),
    "What you draw goes on the component side, among the parts' pins, and an insulated wire is laid as a jumper over the parts. Turning the board over (Ctrl+F) chooses the face again.": (
        "Çizdiğiniz bakır, parçaların bacakları arasındaki parça yüzüne gider; yalıtımlı "
        "tel, parçaların üstünden geçen bir jumper olarak döşenir. Kartı çevirdiğinizde "
        "(Ctrl+F) yüz yeniden seçilir."
    ),
    "on the component side": "parça yüzünde",
    "on the solder side": "lehim yüzünde",
    "a bare wire goes under the board only: an insulated wire goes over the parts": (
        "çıplak tel yalnızca kartın altına döşenir: parçaların üstünden yalıtımlı tel geçer"
    ),
    "the copper goes on the far face: Ctrl+F turns the board over": (
        "bakır arka yüze döşenir: kartı Ctrl+F ile çevirebilirsiniz"
    ),
    "Auto-wire decides: the solder side, or either face when Wiring ▸ Wire on Both Faces is on.": (
        "Otomatik Kablolama karar verir: lehim yüzü ya da Kablolama ▸ İki Yüzde Kablola "
        "açıksa iki yüzden biri."
    ),
    "Auto-wire lays this net on the component side where it can, changing face through a pad with no pin where it must. It does not need Wire on Both Faces.": (
        "Otomatik Kablolama bu neti olabildiğince parça yüzüne döşer; gerektiğinde pimsiz "
        "bir pedden yüz değiştirir. İki Yüzde Kablola'nın açık olması gerekmez."
    ),
    "Auto-wire keeps this net underneath where it can, even with Wire on Both Faces on.": (
        "Otomatik Kablolama, İki Yüzde Kablola açıkken bile bu neti olabildiğince altta tutar."
    ),
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
    "Project saved to {path}: the board and {count} generated file{note}": "Proje {path} konumuna kaydedildi: kart ve {count} üretilmiş dosya{note}",
    "Project saved to {path}: the board and {count} generated files{note}": "Proje {path} konumuna kaydedildi: kart ve {count} üretilmiş dosya{note}",
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
    "Keep the board I have  ·  {size}": "Mevcut kartım kalsın  ·  {size}",
    "fits, {percent}% full": "sığıyor, %{percent} dolu",
    "too small — {count} part will not fit": "çok küçük — {count} parça sığmıyor",
    "too small — {count} parts will not fit": "çok küçük — {count} parça sığmıyor",
    "Suggested:  ": "Önerilen:  ",
    "Arranging the circuit on the board…": "Devre kart üzerine yerleştiriliyor…",
    "Board refused": "Kart reddedildi",
    "{count} conductor: a wire or a solder run": "{count} iletken: tel ya da lehim yolu",
    "{count} conductors: wires and solder runs": "{count} iletken: teller ve lehim yolları",
    "{count} track cut": "{count} yol kesiği",
    "{count} track cuts": "{count} yol kesiği",
    "{count} label": "{count} etiket",
    "{count} labels": "{count} etiket",
    "The new board has no room for these, so they are taken up with it:": (
        "Yeni kartta bunlara yer yok, bu yüzden kartla birlikte kaldırılırlar:"
    ),
    "One Ctrl+Z puts the board and all of it back.": (
        "Tek bir Ctrl+Z kartı da bunların hepsini de geri getirir."
    ),
    "Take up what does not fit?": "Sığmayanlar kaldırılsın mı?",
    "Not applied: the board on the document is as it was.": (
        "Uygulanmadı: belgedeki kart olduğu gibi kaldı."
    ),
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
    "Solder flowed pad to pad, joined at every pad": "Pedden pede akıtılan lehim; her pede bağlanır",
    "Solder over a tinned wire, for current": "Kalaylı tel üstünde lehim; akım taşıyan hatlar için",
    "Tinned wire on the solder side; cannot cross copper": "Lehim yüzünde kalaylı tel; bakırın üstünden geçemez",
    "Sleeved wire; may cross other copper": "Kılıfıyla başka bakırın üstünden geçebilir",
    "On the component side, over the parts": "Parça yüzünde, parçaların üstünden",
    "A solder trace is solder flowed from pad to pad, joined at every pad it crosses": (
        "Lehim yolu, pedden pede akıtılan lehimdir; üstünden geçtiği her pede bağlanır"
    ),
    "A reinforced solder trace is solder flowed over a tinned wire, for a line that carries current": (
        "Telli lehim yolu, kalaylı bir telin üstüne akıtılan lehimdir; akım taşıyan hatlar içindir"
    ),
    "A bare wire is soldered at its two ends on the solder side, and cannot cross other copper": (
        "Çıplak tel, lehim yüzünde iki ucundan lehimlenir ve başka bakırın üstünden geçemez"
    ),
    "An insulated wire is soldered only at its two ends, and its sleeve lets it cross other copper": (
        "İzoleli tel yalnızca iki ucundan lehimlenir; kılıfı sayesinde başka bakırın üstünden geçebilir"
    ),
    "A jumper is an insulated wire on the component side, over the parts": (
        "Jumper, parça yüzünde parçaların üstünden geçen izoleli bir teldir"
    ),
    "Connect puts two pins on one net and lays no copper: wiring them comes later": (
        "Bağla, iki pini aynı nete koyar ve bakır döşemez; kablolama sonra gelir"
    ),
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
    "{name} — {count} pin, {height} mm tall": "{name} — {count} pin, {height} mm yükseklik",
    "{name} — {count} pins, {height} mm tall": "{name} — {count} pin, {height} mm yükseklik",
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
    "Draw the copper on the face you are NOT looking at through the board, dimmed. "
    "Turned off, only a selected wire or a lit net's shows.": (
        "Bakmadığınız yüzdeki bakırı kartın içinden, soluk olarak çizer. Kapatıldığında "
        "yalnızca seçili bir tel ya da vurgulanan bir netinki görünür."
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
    "Trying boards was cancelled after {count} board.": "Kart denemesi {count} karttan sonra iptal edildi.",
    "Trying boards was cancelled after {count} boards.": "Kart denemesi {count} karttan sonra iptal edildi.",
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
    "Imported {count} net from {name}": "{name} dosyasından {count} net içe aktarıldı",
    "Imported {count} nets from {name}": "{name} dosyasından {count} net içe aktarıldı",
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
    "Rotated {count} part": "{count} parça döndürüldü",
    "Rotated {count} parts": "{count} parça döndürüldü",
    "Mirrored {count} part": "{count} parça aynalandı",
    "Mirrored {count} parts": "{count} parça aynalandı",
    "Move to &Solder Side": "&Lehim Yüzüne Al",
    "A part on the solder side is put in from underneath, turned over, so it is mirrored; "
    "its leads are soldered on the component side.": (
        "Lehim yüzündeki bir parça alttan, ters çevrilerek takılır; bu yüzden aynalıdır. "
        "Bacakları parça yüzünde lehimlenir."
    ),
    "Move to Component &Side": "Parça Yüzüne A&l",
    "move it to the other side": "öbür yüze alın",
    "Moved {count} part to the solder side: Ctrl+F turns the board over": "{count} parça lehim yüzüne alındı: Ctrl+F kartı çevirir",
    "Moved {count} parts to the solder side: Ctrl+F turns the board over": "{count} parça lehim yüzüne alındı: Ctrl+F kartı çevirir",
    "Moved {count} part to the component side": "{count} parça, parça yüzüne alındı",
    "Moved {count} parts to the component side": "{count} parça, parça yüzüne alındı",
    "{count} of {total} parts changed holes: its wiring needs redoing": (
        "{total} parçadan {count} tanesi başka deliklere geçti: kablolaması yeniden yapılmalı"
    ),
    "{count} of {total} parts changed holes: their wiring needs redoing": (
        "{total} parçadan {count} tanesi başka deliklere geçti: kablolaması yeniden yapılmalı"
    ),
    "{ref} is on the solder side, turned over, so it is mirrored already. Shift+M brings it "
    "back to the component side.": (
        "{ref} lehim yüzünde, ters çevrilmiş olduğu için zaten aynalı. Shift+M onu parça "
        "yüzüne geri getirir."
    ),
    "Locked {count} part": "{count} parça kilitlendi",
    "Locked {count} parts": "{count} parça kilitlendi",
    "Unlocked {count} part": "{count} parçanın kilidi açıldı",
    "Unlocked {count} parts": "{count} parçanın kilidi açıldı",
    "Deleted {count} part": "{count} parça silindi",
    "Deleted {count} parts": "{count} parça silindi",
    "Disconnected {count} pin": "{count} pin ayrıldı",
    "Disconnected {count} pins": "{count} pin ayrıldı",
    # -- confirmations, with the verb on the button ------------------------------------
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
    "{count} conductor already laid for it stays on the board, and Redo Wiring and Remove Out-of-Date Wiring leave it alone from then on.": "Onun için döşenmiş {count} iletken kartta kalır; Kablolamayı Yeniden Yap ve Eskimiş Kablolamayı Kaldır artık ona dokunmaz.",
    "{count} conductors already laid for it stay on the board, and Redo Wiring and Remove Out-of-Date Wiring leave them alone from then on.": "Onun için döşenmiş {count} iletken kartta kalır; Kablolamayı Yeniden Yap ve Eskimiş Kablolamayı Kaldır artık onlara dokunmaz.",
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
    "({count} warning)": "({count} uyarı)",
    "({count} warnings)": "({count} uyarı)",
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
    "{count} step by trace": "lehim yoluyla {count} adım",
    "{count} steps by trace": "lehim yoluyla {count} adım",
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
    "Battery (names + and -)": "Pil (adlar + ve -)",
    "DC jack (names + and -)": "DC jak (adlar + ve -)",
    "CR2032 coin cell holder, Keystone 1067 (vertical)": (
        "CR2032 düğme pil yuvası, Keystone 1067 (dikey)"
    ),
    "Stands one 20 mm coin cell on edge: CR2032, CR2016, CL2025, DL2020": (
        "Bir adet 20 mm düğme pili ayakta tutar: CR2032, CR2016, CL2025, DL2020"
    ),
    "The mounting leg sits 7.1 mm to one side of the pins and wants a hole of its own, "
    "which the 2.54 mm grid does not have (the drawing gives 2.4 mm for the pad and "
    "1.57 mm for the leg): drill it. Match + and - to the marks on the holder before "
    "soldering, not to the order here.": (
        "Montaj bacağı pinlerin 7,1 mm yanında durur ve kendi deliğini ister; 2,54 mm'lik "
        "ızgarada böyle bir delik yoktur (çizim pad için 2,4 mm, bacak için 1,57 mm verir): "
        "kendiniz delin. + ve - uçlarını buradaki sıraya göre değil, yuvanın üzerindeki "
        "işaretlere göre bağlayın."
    ),
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
    "{names} for {pins}.": "{pins} için {names}.",
    "{count} name": "{count} ad",
    "{count} names": "{count} ad",
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
    "Temperature sensor, 750 mV at 25 degrees C and 10 mV for each degree, from 2.7 V": (
        "Sıcaklık sensörü, 25 derecede 750 mV ve her derece için 10 mV, 2,7 V'tan itibaren"
    ),
    "It reads 500 mV at 0 degrees C and rises 10 mV a degree, so subtract the 500 mV before "
    "dividing by 10. Its datasheet draws the legs from below, so from the left with the flat "
    "face towards you they are +VS, VOUT, GND. Check the legs against the datasheet of the "
    "part you have before soldering.": (
        "0 derecede 500 mV okur ve derece başına 10 mV yükselir; bu yüzden 10'a bölmeden "
        "önce 500 mV'u çıkarın. Veri sayfası bacakları alttan çizer; yani düz yüz size "
        "dönükken soldan +VS, VOUT, GND'dir. Lehimlemeden önce bacakları elinizdeki "
        "parçanın veri sayfasıyla karşılaştırın."
    ),
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
    "DFPlayer Mini MP3 player": "DFPlayer Mini MP3 çalar",
    "MP3 and WAV player from a micro SD card, 16 pins, rows 17.78 mm apart: serial "
    "control, a 3 W speaker output and a line output": (
        "Mikro SD karttan MP3 ve WAV çalar, 16 pin, sıralar 17,78 mm arayla: seri "
        "kontrol, 3 W'lık hoparlör çıkışı ve hat çıkışı"
    ),
    "VCC takes 3.2 to 5 V. RX and TX are 3.3 V logic at 9600 baud: from a 5 V "
    "board's TX, put a 1k resistor in series with RX. SPK1 and SPK2 are the two "
    "ends of a bridge-tied amplifier for a 4 or 8 ohm speaker under 3 W: join "
    "neither to ground, and the speaker has no polarity. DAC_R and DAC_L are the "
    "line output for an external amplifier or headphones, not for a speaker. BUSY "
    "is low while a track plays and high when idle. IO1 and IO2 play the previous "
    "and next track when pulled to ground through a button, and ADKEY1 and ADKEY2 "
    "do the same through a resistor ladder; the module has two GND pins and uses "
    "either. DFRobot's board drawing v1.1 prints pin 12 as IO3 and pin 16 as GPIOA1"
    " where the datasheet has ADKEY1 and BUSY, and the datasheet's own picture "
    "swaps SPK1 with SPK2 and the ADKEYs and the USB pair against its table: the "
    "names here follow the table. A serial player needs only VCC, GND, RX, TX and "
    "the speaker. The micro SD socket is the tallest part and the maker gives no "
    "height: it is taken as 2 mm. The height of what is on the board is an "
    "estimate, and so is its colour; the pins, the rows and the board outline are "
    "measured.": (
        "VCC 3,2 ile 5 V alır. RX ve TX 9600 baud'da 3,3 V mantıktır: 5 V'luk bir "
        "kartın TX'inden RX'e 1k'lık bir direnç seri koyun. SPK1 ve SPK2, 3 W altı 4 "
        "ya da 8 ohm'luk bir hoparlör için köprü bağlı yükselticinin iki ucudur: "
        "ikisini de toprağa bağlamayın, hoparlörün kutbu yoktur. DAC_R ve DAC_L "
        "harici bir yükseltici ya da kulaklık için hat çıkışıdır, hoparlör için "
        "değil. BUSY parça çalarken düşük, boştayken yüksektir. IO1 ve IO2 bir buton "
        "üzerinden toprağa çekilince önceki ve sonraki parçayı çalar, ADKEY1 ve "
        "ADKEY2 aynısını direnç merdiveniyle yapar; modülde iki GND pini vardır ve "
        "ikisi de kullanılabilir. DFRobot'un v1.1 kart çizimi 12. pini IO3, 16. pini "
        "GPIOA1 yazar; datasheet'te bunlar ADKEY1 ve BUSY'dir, datasheet'in kendi "
        "resmi de SPK1 ile SPK2'yi, ADKEY'leri ve USB çiftini tablosuna göre ters "
        "yazar: buradaki adlar tabloyu izler. Seri bir çalar için yalnızca VCC, GND, "
        "RX, TX ve hoparlör gerekir. Mikro SD yuvası en yüksek parçadır ve yapımcı "
        "bir yükseklik vermez: 2 mm alındı. Kartın üzerindekilerin yüksekliği bir "
        "tahmindir, rengi de öyle; pinler, sıralar ve kart ana hattı ölçülmüştür."
    ),
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
    "NTC thermistor (MF52 bead)": "NTC termistör (MF52 damla)",
    "Epoxy-bead thermistor, 10,000 ohm at 25 degrees C, its resistance falling as it warms": (
        "Epoksi damlalı termistör, 25 derecede 10.000 ohm; ısındıkça direnci düşer"
    ),
    "Its wires are 2.5 mm apart and the holes 2.54, inside the drawing's +-0.5. The "
    "resistance and the B value are in its part number, not on the bead: measure it, about "
    "10 kohm at 25 degrees C. How high the bead stands is yours to choose and it is drawn "
    "at the longest the datasheet allows, 9.5 mm; leave less wire above the board and it "
    "stands lower.": (
        "Telleri 2,5 mm arayla durur, delikler 2,54 mm: çizimin ±0,5 payının içinde. Direnci "
        "ve B değeri damlanın üstünde değil, parça numarasında yazar: ölçün, 25 derecede "
        "yaklaşık 10 kohm olmalı. Damlanın ne kadar yüksekte duracağı sizin elinizde; çizim "
        "veri sayfasının izin verdiği en uzun boya, 9,5 mm'ye göre yapılmıştır; kartın "
        "üstünde daha az tel bırakırsanız daha alçakta durur."
    ),
    "ULN2003 stepper driver board (on a header)": "ULN2003 step motor sürücü kartı (header üzerinde)",
    "Driver board for a 28BYJ-48 stepper. Its cable plugs into this 6-pin header: IN1 IN2 IN3 "
    "IN4 - + from pin 1": (
        "28BYJ-48 step motoru için sürücü kartı. Kablosu bu 6 pinli header'a takılır: 1. "
        "pinden IN1 IN2 IN3 IN4 - +"
    ),
    "The four inputs are lettered A to D on the board and IN1 to IN4 under its header; the "
    "supply is a separate pair of pins, 5 to 12 V, so give a 5 V 28BYJ-48 5 V and join the "
    "supply's - to your logic ground. The motor plugs into the board's own white socket, not "
    "into this header. Match each lead to the name printed beside the module's pins, not to "
    "its place: sellers' boards are not all wired in the same order.": (
        "Dört giriş kartın üzerinde A'dan D'ye, header'ın altında IN1'den IN4'e diye yazılıdır; "
        "besleme ayrı bir pin çiftidir, 5 ile 12 V: 5 V'luk bir 28BYJ-48'e 5 V verin ve "
        "beslemenin - ucunu mantık topraklamanıza bağlayın. Motor bu header'a değil, kartın "
        "kendi beyaz soketine takılır. Her kabloyu yerine göre değil, modülün pinlerinin yanında "
        "yazan ada göre bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "SW-520D tilt switch": "SW-520D eğim anahtarı",
    "Ball tilt switch, 12 V contacts: closed while within about 45 degrees of upright with "
    "its leads down, open past that": (
        "Bilyeli eğim anahtarı, 12 V kontaklı: bacakları aşağıdayken dikten yaklaşık 45 "
        "dereceye kadar kapalı, ötesinde açık"
    ),
    "Its leads are 2.4 mm apart and the holes 2.54, so each ends up 0.07 mm off its hole, "
    "well inside the 0.2 mm a 0.6 mm lead has to spare in a 1 mm hole: it goes in as it is. "
    "Sellers disagree on which way up it conducts, so tilt yours over a multimeter before "
    "you solder it.": (
        "Bacakları 2,4 mm arayla durur, delikler 2,54 mm: her biri deliğinin merkezinden 0,07 "
        "mm kayar; bu, 1 mm'lik bir delikte 0,6 mm'lik bir bacağın payı olan 0,2 mm'nin çok "
        "içindedir, yani olduğu gibi girer. Satıcılar hangi yönde ilettiği konusunda hemfikir "
        "değildir: lehimlemeden önce sizinkini multimetreyle eğerek deneyin."
    ),
    "RV09 potentiometer, 9 mm": "RV09 potansiyometre, 9 mm",
    "Potentiometer with a 6 mm shaft standing 20 mm above the board: end, wiper, end, in a "
    "row of three pins": (
        "Mili karttan 20 mm yukarıda duran, 6 mm milli potansiyometre: uç, orta uç, uç; "
        "üç pinlik bir sırada"
    ),
    "Snip the two lugs off flush with the frame before you solder it. They are 3.8 mm long "
    "against the pins' 3.2, so left on they hold the frame 0.6 mm clear of the board and the "
    "pins stop short of the holes. The pins' 2.5 mm pitch against the board's 2.54 puts the "
    "end pins 0.04 mm off their holes, inside what a 1 mm hole has to spare. Its value is "
    "printed on it as B10K or A10K: B is linear, A the log taper of a volume control.": (
        "Lehimlemeden önce iki tırnağı gövdeyle aynı hizada kesin. Tırnaklar pinlerin 3,2 "
        "mm'sine karşılık 3,8 mm uzundur; bırakırsanız gövdeyi karttan 0,6 mm yukarıda "
        "tutar ve pinler deliklere ulaşmaz. Pinlerin 2,5 mm aralığı kartın 2,54 mm'sine "
        "karşı uçtaki pinleri deliklerinden 0,04 mm kaydırır; bu, 1 mm'lik bir deliğin payı "
        "içindedir. Değeri üzerinde B10K ya da A10K diye yazar: B doğrusaldır, A ses "
        "kontrolünün istediği logaritmik eğridir."
    ),
    "EC11 rotary encoder": "EC11 döner kodlayıcı",
    "Two-phase rotary encoder, shaft 20 mm above its frame: A and B pulse against the common "
    "C as it turns": (
        "İki fazlı döner kodlayıcı, mili gövdesinin 20 mm üstünde: dönerken A ve B, ortak C'ye "
        "karşı darbe verir"
    ),
    "Snip off the two pegs and the switch's D and E flush with the frame. D and E sit 14.5 mm "
    "from the three pins, 0.74 mm off a row of holes, and the pegs are as long as the pins "
    "(3.5 mm), so left on they would stand the frame on the board and keep the pins out of "
    "the holes. If you want the push switch, solder wires to the stubs of D and E by hand; "
    "the KY-040 is the encoder with a switch ready to plug in. A and B are 0.04 mm off their "
    "holes for the 2.5 mm against 2.54 pitch, inside what a 1 mm hole has to spare.": (
        "İki tırnağı ve düğmenin D ile E uçlarını gövdeyle aynı hizada kesin. D ve E üç "
        "pinden 14,5 mm uzaktadır, bir delik sırasından 0,74 mm kaçıktır; tırnaklar da "
        "pinler kadar (3,5 mm) uzundur, bırakırsanız gövdeyi kartın üstüne oturtur ve "
        "pinleri deliklerin dışında tutar. Basmalı düğmeyi isterseniz D ve E'nin kalan "
        "uçlarına tel lehimleyin; hazır takılan düğmeli kodlayıcı KY-040'tır. A ve B, 2,5 mm "
        "aralığın kartın 2,54 mm'sine karşı yüzünden deliklerinden 0,04 mm kayar; bu, 1 mm'lik "
        "bir deliğin payı içindedir."
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
    "ESP32 DevKit V1 (30-pin)": "ESP32 DevKit V1 (30 pinli)",
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
    "Adafruit BH1750 light sensor (on a header)": (
        "Adafruit BH1750 ışık sensörü (header üzerinde)"
    ),
    "Light sensor, 1 to 65535 lux, on I2C. Its cable plugs into this 6-pin header: VIN "
    "3Vo GND SCL SDA ADDR from pin 1": (
        "I2C üzerinden 1 ile 65535 lüks arası ışık sensörü. Kablosu bu 6 pinli header'a"
        " takılır: 1. pinden VIN 3Vo GND SCL SDA ADDR"
    ),
    "VIN takes 3 to 5 V by the board's silkscreen: a 3.3 V regulator makes the sensor's"
    " supply, and 3Vo is that regulator's output, not a second input. SCL and SDA go "
    "through level-shifting transistors, so the bus may run at VIN's level. The "
    "silkscreen gives the default I2C address as 0x23: a resistor on the board holds "
    "ADDR low, and the solder jumper beside it ties ADDR to 3.3 V for the other "
    "address, so leave ADDR unwired for the default. Other BH1750 boards carry a "
    "different header, so compare the names printed on yours with these. Match each "
    "lead to the name printed beside the module's pins, not to its place: sellers' "
    "boards are not all wired in the same order.": (
        "VIN, kartın baskısına göre 3 ile 5 V alır: kartın üzerindeki 3,3 V'luk bir "
        "regülatör sensörün beslemesini üretir ve 3Vo o regülatörün çıkışıdır, ikinci "
        "bir giriş değildir. SCL ile SDA seviye çeviren transistörlerden geçer, bu "
        "yüzden hat VIN seviyesinde çalışabilir. Baskı varsayılan I2C adresini 0x23 "
        "olarak verir: kartın üzerindeki bir direnç ADDR'yi düşük tutar, yanındaki "
        "lehim köprüsü de öteki adres için ADDR'yi 3,3 V'a bağlar; varsayılan için "
        "ADDR'yi boş bırakın. Başka BH1750 kartlarının header'ı farklıdır: sizinkinin "
        "üzerinde yazan adları bunlarla karşılaştırın. Her kabloyu yerine göre değil, "
        "modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı "
        "sırayla bağlanmamıştır."
    ),
    "Adafruit AHT20 temperature and humidity sensor (on a header)": (
        "Adafruit AHT20 sıcaklık ve nem sensörü (header üzerinde)"
    ),
    "Temperature and humidity sensor, on I2C. Its cable plugs into this 4-pin header: "
    "VIN GND SCL SDA from pin 1": (
        "I2C üzerinden sıcaklık ve nem sensörü. Kablosu bu 4 pinli header'a takılır: 1."
        " pinden VIN GND SCL SDA"
    ),
    "VIN takes 3 to 5 V by the board's silkscreen, and the board has no regulator: the "
    "sensor's supply is VIN through a resistor and a capacitor, and the pull-ups on SCL"
    " and SDA go to VIN, so the bus idles at VIN's level. Other AHT20 boards carry a "
    "different header, so compare the names printed on yours with these. Match each "
    "lead to the name printed beside the module's pins, not to its place: sellers' "
    "boards are not all wired in the same order.": (
        "VIN, kartın baskısına göre 3 ile 5 V alır ve kartta regülatör yoktur: sensörün"
        " beslemesi VIN'dir, bir direnç ve bir kondansatörden geçer; SCL ile SDA'nın "
        "yukarı çekme dirençleri de VIN'e gider, bu yüzden hat VIN seviyesinde bekler. "
        "Başka AHT20 kartlarının header'ı farklıdır: sizinkinin üzerinde yazan adları "
        "bunlarla karşılaştırın. Her kabloyu yerine göre değil, modülün pinlerinin "
        "yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "Adafruit VL53L0X time-of-flight distance sensor (on a header)": (
        "Adafruit VL53L0X uçuş süresi mesafe sensörü (header üzerinde)"
    ),
    "Laser distance sensor, about 30 to 1000 mm, on I2C. Its cable plugs into this "
    "7-pin header: VIN 2v8 GND GPIO SHDN SCL SDA from pin 1": (
        "I2C üzerinden lazerli mesafe sensörü, yaklaşık 30 ile 1000 mm. Kablosu bu 7 "
        "pinli header'a takılır: 1. pinden VIN 2v8 GND GPIO SHDN SCL SDA"
    ),
    "VIN takes 3 to 5 V by the board's silkscreen: a 2.8 V regulator makes the sensor's"
    " supply, and 2v8 is its output, not a second input. SCL and SDA go through level-"
    "shifting transistors, so the bus may run at VIN's level. SHDN is the sensor's "
    "XSHUT line, held high by a resistor on the board: pull it low to switch the sensor"
    " off, or leave it unwired. GPIO is the sensor's interrupt output and can stay "
    "unwired. Other VL53L0X boards carry a different header, so compare the names "
    "printed on yours with these. Match each lead to the name printed beside the "
    "module's pins, not to its place: sellers' boards are not all wired in the same "
    "order.": (
        "VIN, kartın baskısına göre 3 ile 5 V alır: kartın üzerindeki 2,8 V'luk bir "
        "regülatör sensörün beslemesini üretir ve 2v8 onun çıkışıdır, ikinci bir giriş "
        "değildir. SCL ile SDA seviye çeviren transistörlerden geçer, bu yüzden hat VIN"
        " seviyesinde çalışabilir. SHDN sensörün XSHUT hattıdır ve kartın üzerindeki "
        "bir dirençle yüksek tutulur: sensörü kapatmak için düşük çekin, ya da boş "
        "bırakın. GPIO sensörün kesme çıkışıdır ve boş kalabilir. Başka VL53L0X "
        "kartlarının header'ı farklıdır: sizinkinin üzerinde yazan adları bunlarla "
        "karşılaştırın. Her kabloyu yerine göre değil, modülün pinlerinin yanında yazan"
        " ada göre bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "Adafruit APDS9960 gesture and colour sensor (on a header)": (
        "Adafruit APDS9960 hareket ve renk sensörü (header üzerinde)"
    ),
    "Proximity, gesture, colour and ambient light sensor, on I2C. Its cable plugs "
    "into this 6-pin header: VIN 3Vo GND SCL SDA INT from pin 1": (
        "I2C üzerinden yakınlık, hareket, renk ve ortam ışığı sensörü. Kablosu bu 6 "
        "pinli header'a takılır: 1. pinden VIN 3Vo GND SCL SDA INT"
    ),
    "VIN takes 3 to 5 V: a 3.3 V regulator makes the sensor's supply, and 3Vo is "
    "its output, not a second input. SCL and SDA go through level-shifting "
    "transistors with 10k pull-ups on both sides, so the bus idles at VIN's level. "
    "INT is the sensor's open-drain interrupt, pulled up to VIN by a 10k: it goes "
    "low on a gesture or a threshold, and can stay unwired when the sensor is "
    "polled. The address is 0x39 and cannot be changed. Other APDS9960 boards carry"
    " a different header, so compare the names printed on yours with these. Match "
    "each lead to the name printed beside the module's pins, not to its place: "
    "sellers' boards are not all wired in the same order.": (
        "VIN 3 ile 5 V alır: 3,3 V'luk bir regülatör sensörün beslemesini üretir ve "
        "3Vo onun çıkışıdır, ikinci bir giriş değildir. SCL ile SDA seviye çeviren "
        "transistörlerden geçer ve iki yanında da 10k'lık yukarı çekme dirençleri "
        "vardır, bu yüzden hat VIN seviyesinde bekler. INT sensörün açık savaklı "
        "kesme çıkışıdır ve 10k ile VIN'e çekilir: bir harekette ya da eşikte düşer, "
        "sensör sorgulanıyorsa boş kalabilir. Adres 0x39'dur ve değiştirilemez. Başka"
        " APDS9960 kartlarının header'ı farklıdır: sizinkinin üzerinde yazan adları "
        "bunlarla karşılaştırın. Her kabloyu yerine göre değil, modülün pinlerinin "
        "yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "Adafruit VL53L1X time-of-flight distance sensor (on a header)": (
        "Adafruit VL53L1X uçuş süresi mesafe sensörü (header üzerinde)"
    ),
    "Laser distance sensor, up to about 4 m, on I2C. Its cable plugs into this "
    "6-pin header: VIN GND SCL SDA GPIO XSHUT from pin 1": (
        "I2C üzerinden lazerli mesafe sensörü, yaklaşık 4 m'ye kadar. Kablosu bu 6 "
        "pinli header'a takılır: 1. pinden VIN GND SCL SDA GPIO XSHUT"
    ),
    "VIN takes 3 to 5 V: a 2.8 V regulator makes the sensor's supply and stays on "
    "the board. SCL and SDA go through level-shifting transistors, so the bus may "
    "run at VIN's level. XSHUT is held high by a 10k on the sensor's side of a "
    "diode: pull it low to switch the sensor off. The diode keeps a high from the "
    "controller off the sensor, so it can stay unwired. GPIO is the sensor's "
    "interrupt output, pulled up to 2.8 V and not to VIN, so a 5 V controller may "
    "not read it as high: it can stay unwired. The address is 0x29 until the "
    "software changes it, and the range is about 4 m in the dark and less in "
    "daylight. Other VL53L1X boards carry a different header, so compare the names "
    "printed on yours with these. Match each lead to the name printed beside the "
    "module's pins, not to its place: sellers' boards are not all wired in the same"
    " order.": (
        "VIN 3 ile 5 V alır: 2,8 V'luk bir regülatör sensörün beslemesini üretir ve "
        "kartın üzerinde kalır. SCL ile SDA seviye çeviren transistörlerden geçer, bu"
        " yüzden hat VIN seviyesinde çalışabilir. XSHUT, bir diyodun sensör tarafında"
        " 10k ile yüksek tutulur: sensörü kapatmak için düşük çekin. Diyot "
        "denetleyicinin yüksek seviyesini sensörden uzak tutar, bu yüzden boş "
        "bırakılabilir. GPIO sensörün kesme çıkışıdır ve VIN'e değil 2,8 V'a çekilir,"
        " bu yüzden 5 V'luk bir denetleyici onu yüksek okumayabilir: boş kalabilir. "
        "Adres yazılım değiştirene kadar 0x29'dur, menzil karanlıkta yaklaşık 4 m, "
        "gün ışığında daha azdır. Başka VL53L1X kartlarının header'ı farklıdır: "
        "sizinkinin üzerinde yazan adları bunlarla karşılaştırın. Her kabloyu yerine "
        "göre değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların "
        "kartları aynı sırayla bağlanmamıştır."
    ),
    "Adafruit ADXL345 accelerometer (on a header)": (
        "Adafruit ADXL345 ivmeölçer (header üzerinde)"
    ),
    "3-axis accelerometer, on I2C or SPI. Its cable plugs into this 9-pin header: VIN "
    "3V3 GND CS INT1 INT2 SDO SDA SCL from pin 1": (
        "I2C veya SPI üzerinden 3 eksenli ivmeölçer. Kablosu bu 9 pinli header'a "
        "takılır: 1. pinden VIN 3V3 GND CS INT1 INT2 SDO SDA SCL"
    ),
    "VIN feeds a regulator on the board and 3V3 is that regulator's output, not a "
    "second input. SCL and SDA go through level-shifting transistors, so the bus may "
    "run at VIN's level. CS is pulled high on the board, which leaves the chip on I2C: "
    "pull it low only to use SPI. SDO is pulled low on the board, which makes the I2C "
    "address 0x53; tie it to 3V3 for 0x1D. INT1 and INT2 are the chip's interrupt "
    "outputs and can stay unwired. Other ADXL345 boards carry a different header, so "
    "compare the names printed on yours with these. Match each lead to the name printed"
    " beside the module's pins, not to its place: sellers' boards are not all wired in "
    "the same order.": (
        "VIN, kartın üzerindeki bir regülatörü besler ve 3V3 o regülatörün çıkışıdır, "
        "ikinci bir giriş değildir. SCL ile SDA seviye çeviren transistörlerden geçer, "
        "bu yüzden hat VIN seviyesinde çalışabilir. CS kartın üzerinde yüksek tutulur, "
        "bu da çipi I2C'de bırakır: yalnızca SPI kullanmak için düşük çekin. SDO kartın"
        " üzerinde düşük tutulur, bu da I2C adresini 0x53 yapar; 0x1D için SDO'yu 3V3'e"
        " bağlayın. INT1 ile INT2 çipin kesme çıkışlarıdır ve boş kalabilir. Başka "
        "ADXL345 kartlarının header'ı farklıdır: sizinkinin üzerinde yazan adları "
        "bunlarla karşılaştırın. Her kabloyu yerine göre değil, modülün pinlerinin "
        "yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "Adafruit SHT31-D temperature and humidity sensor (on a header)": (
        "Adafruit SHT31-D sıcaklık ve nem sensörü (header üzerinde)"
    ),
    "Temperature and humidity sensor, on I2C. Its cable plugs into this 7-pin header: "
    "VIN GND SCL SDA ADR RST ALR from pin 1": (
        "I2C üzerinden sıcaklık ve nem sensörü. Kablosu bu 7 pinli header'a takılır: 1."
        " pinden VIN GND SCL SDA ADR RST ALR"
    ),
    "VIN and the logic take 3.3 to 5 V by the board's silkscreen, and the board has no "
    "regulator. Resistors on the board pull SCL, SDA and RST up to the sensor's supply,"
    " and ADR is pulled low, which makes the I2C address 0x44; tie ADR to VIN for 0x45."
    " RST is the sensor's reset line (pull it low to reset) and ALR its alert output: "
    "both can stay unwired. Other SHT31 boards carry a different header, so compare the"
    " names printed on yours with these. Match each lead to the name printed beside the"
    " module's pins, not to its place: sellers' boards are not all wired in the same "
    "order.": (
        "VIN ile mantık seviyesi, kartın baskısına göre 3,3 ile 5 V alır ve kartta "
        "regülatör yoktur. Kartın üzerindeki dirençler SCL, SDA ve RST'yi sensörün "
        "beslemesine çeker, ADR ise düşük tutulur; bu da I2C adresini 0x44 yapar, 0x45 "
        "için ADR'yi VIN'e bağlayın. RST sensörün sıfırlama hattıdır (sıfırlamak için "
        "düşük çekin), ALR de uyarı çıkışıdır: ikisi de boş kalabilir. Başka SHT31 "
        "kartlarının header'ı farklıdır: sizinkinin üzerinde yazan adları bunlarla "
        "karşılaştırın. Her kabloyu yerine göre değil, modülün pinlerinin yanında yazan"
        " ada göre bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "SparkFun MAX30105 particle and pulse sensor (on a header)": (
        "SparkFun MAX30105 partikül ve nabız sensörü (header üzerinde)"
    ),
    "Particle, pulse and pulse-oximeter sensor, on I2C. Its cable plugs into this 5-pin"
    " header: SCL SDA 5V GND !INT from pin 1": (
        "I2C üzerinden partikül, nabız ve nabız oksimetresi sensörü. Kablosu bu 5 pinli"
        " header'a takılır: 1. pinden SCL SDA 5V GND !INT"
    ),
    "The 5V pad feeds the sensor's LEDs directly and a 1.8 V regulator for its logic. "
    "SCL and SDA go through level-shifting MOSFETs, so the bus may run at the 5V pad's "
    "level. The readme says the board needs 3.3 V to run the red and infrared LEDs and "
    "recommends 3.5 V for the green one, so the pad is not only a 5 V input. The bus "
    "pull-ups and the !INT pull-up go to the 5V pad through the PU and INT solder "
    "jumpers, which the board file draws closed by a trace. !INT is the sensor's "
    "interrupt output, active low, and can stay unwired. Other MAX30102 and MAX30105 "
    "boards carry a different header, so compare the names printed on yours with these."
    " Match each lead to the name printed beside the module's pins, not to its place: "
    "sellers' boards are not all wired in the same order.": (
        "5V pini sensörün LED'lerini doğrudan, mantığını da 1,8 V'luk bir regülatör "
        "üzerinden besler. SCL ile SDA seviye çeviren MOSFET'lerden geçer, bu yüzden "
        "hat 5V pininin seviyesinde çalışabilir. Deponun readme'sine göre kart kırmızı "
        "ve kızılötesi LED'ler için 3,3 V ister, yeşil LED için 3,5 V önerir; yani pin "
        "yalnızca bir 5 V girişi değildir. Hat ve !INT yukarı çekme dirençleri, kart "
        "dosyasında iz ile kapalı çizilmiş PU ve INT lehim köprüleri üzerinden 5V "
        "pinine gider. !INT sensörün kesme çıkışıdır, düşükte etkindir ve boş "
        "kalabilir. Başka MAX30102 ve MAX30105 kartlarının header'ı farklıdır: "
        "sizinkinin üzerinde yazan adları bunlarla karşılaştırın. Her kabloyu yerine "
        "göre değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların "
        "kartları aynı sırayla bağlanmamıştır."
    ),
    "Adafruit MCP4725 12-bit DAC (on a header)": (
        "Adafruit MCP4725 12 bit DAC (header üzerinde)"
    ),
    "12-bit digital-to-analog converter, on I2C. Its cable plugs into this 6-pin "
    "header: VDD GND SCL SDA A0 VOUT from pin 1": (
        "I2C üzerinden 12 bit dijital-analog çevirici. Kablosu bu 6 pinli header'a "
        "takılır: 1. pinden VDD GND SCL SDA A0 VOUT"
    ),
    "VDD takes 2.7 to 5.5 V by the board's silkscreen, and VOUT swings between 0 V and "
    "VDD. Resistors on the board pull SCL and SDA up to VDD, and A0 is pulled low, "
    "which makes the I2C address 0x62; tie A0 to VDD for 0x63. Other MCP4725 boards "
    "carry a different header, so compare the names printed on yours with these. Match "
    "each lead to the name printed beside the module's pins, not to its place: sellers'"
    " boards are not all wired in the same order.": (
        "VDD, kartın baskısına göre 2,7 ile 5,5 V alır ve VOUT 0 V ile VDD arasında "
        "değişir. Kartın üzerindeki dirençler SCL ile SDA'yı VDD'ye çeker, A0 ise düşük"
        " tutulur; bu da I2C adresini 0x62 yapar, 0x63 için A0'ı VDD'ye bağlayın. Başka"
        " MCP4725 kartlarının header'ı farklıdır: sizinkinin üzerinde yazan adları "
        "bunlarla karşılaştırın. Her kabloyu yerine göre değil, modülün pinlerinin "
        "yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "Adafruit TCS34725 RGB colour sensor (on a header)": (
        "Adafruit TCS34725 RGB renk sensörü (header üzerinde)"
    ),
    "RGB colour and light sensor with an infrared filter, on I2C. Its cable plugs into "
    "this 7-pin header: VIN GND 3V3 SCL SDA INT LED from pin 1": (
        "I2C üzerinden kızılötesi filtreli RGB renk ve ışık sensörü. Kablosu bu 7 pinli"
        " header'a takılır: 1. pinden VIN GND 3V3 SCL SDA INT LED"
    ),
    "VIN takes 3.3 to 5 V by the board's silkscreen: a 3.3 V regulator makes the "
    "sensor's supply, and 3V3 is its output, not a second input. SCL and SDA go through"
    " level-shifting transistors, so the bus is safe at 5 V. LED is the gate of the "
    "transistor that switches the board's white LED, and a resistor holds it high, so "
    "the LED is on until LED is pulled low. INT comes straight from the sensor with no "
    "pull-up on the board, so leave it unwired unless the program uses it. Other "
    "TCS34725 boards carry a different header, so compare the names printed on yours "
    "with these. Match each lead to the name printed beside the module's pins, not to "
    "its place: sellers' boards are not all wired in the same order.": (
        "VIN, kartın baskısına göre 3,3 ile 5 V alır: 3,3 V'luk bir regülatör sensörün "
        "beslemesini üretir ve 3V3 onun çıkışıdır, ikinci bir giriş değildir. SCL ile "
        "SDA seviye çeviren transistörlerden geçer, bu yüzden hat 5 V'ta güvenlidir. "
        "LED, kartın beyaz LED'ini açıp kapatan transistörün gate ucudur ve bir direnç "
        "onu yüksek tutar; LED düşük çekilene kadar LED yanar. INT doğrudan sensörden "
        "gelir ve kartta yukarı çekme direnci yoktur, program kullanmıyorsa boş "
        "bırakın. Başka TCS34725 kartlarının header'ı farklıdır: sizinkinin üzerinde "
        "yazan adları bunlarla karşılaştırın. Her kabloyu yerine göre değil, modülün "
        "pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "Adafruit MAX31855 thermocouple amplifier (on a header)": (
        "Adafruit MAX31855 termokupl yükselticisi (header üzerinde)"
    ),
    "K-type thermocouple amplifier, -200 to 1350 C, on SPI. Its cable plugs into this "
    "6-pin header: Vin 3Vo GND DO CS CLK from pin 1": (
        "SPI üzerinden K tipi termokupl yükselticisi, -200 ile 1350 C arası. Kablosu bu"
        " 6 pinli header'a takılır: 1. pinden Vin 3Vo GND DO CS CLK"
    ),
    "Vin takes 3 to 5 V by the board's silkscreen: a 3.3 V regulator makes the chip's "
    "supply, and 3Vo is its output, up to 100 mA, not a second input. CS and CLK reach "
    "the chip through a diode and a pull-up to 3.3 V, which is what makes them 5 V "
    "compatible; DO is the chip's own output. The thermocouple itself goes to the screw"
    " terminal on the board, not to this header: the silkscreen marks yellow as + and "
    "red as -, and says K-type wire only. Other MAX31855 boards carry a different "
    "header, so compare the names printed on yours with these. Match each lead to the "
    "name printed beside the module's pins, not to its place: sellers' boards are not "
    "all wired in the same order.": (
        "Vin, kartın baskısına göre 3 ile 5 V alır: 3,3 V'luk bir regülatör çipin "
        "beslemesini üretir ve 3Vo onun çıkışıdır, 100 mA'e kadar, ikinci bir giriş "
        "değildir. CS ile CLK çipe bir diyot ve 3,3 V'a bir yukarı çekme direnci "
        "üzerinden ulaşır, onları 5 V ile uyumlu yapan budur; DO çipin kendi çıkışıdır."
        " Termokuplun kendisi bu header'a değil, kartın üzerindeki vidalı klemense "
        "gider: baskı sarıyı + kırmızıyı - olarak işaretler ve yalnızca K tipi tel der."
        " Başka MAX31855 kartlarının header'ı farklıdır: sizinkinin üzerinde yazan "
        "adları bunlarla karşılaştırın. Her kabloyu yerine göre değil, modülün "
        "pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "Adafruit HMC5883L compass (on a header)": (
        "Adafruit HMC5883L pusula (header üzerinde)"
    ),
    "3-axis magnetometer (compass), on I2C. Its cable plugs into this 6-pin header: VIN"
    " GND 3Vo SDA SCL RDY from pin 1": (
        "I2C üzerinden 3 eksenli manyetometre (pusula). Kablosu bu 6 pinli header'a "
        "takılır: 1. pinden VIN GND 3Vo SDA SCL RDY"
    ),
    "VIN takes 3.3 to 5 V by the board's silkscreen: a 3.3 V regulator makes the "
    "sensor's supply, and 3Vo is its output, not a second input. SDA and SCL go through"
    " level-shifting transistors, so the bus is safe at 5 V. RDY is the sensor's data-"
    "ready output, straight from the chip, and can stay unwired. Other HMC5883L boards "
    "carry a different header, so compare the names printed on yours with these. Match "
    "each lead to the name printed beside the module's pins, not to its place: sellers'"
    " boards are not all wired in the same order.": (
        "VIN, kartın baskısına göre 3,3 ile 5 V alır: 3,3 V'luk bir regülatör sensörün "
        "beslemesini üretir ve 3Vo onun çıkışıdır, ikinci bir giriş değildir. SDA ile "
        "SCL seviye çeviren transistörlerden geçer, bu yüzden hat 5 V'ta güvenlidir. "
        "RDY sensörün veri hazır çıkışıdır, doğrudan çipten gelir ve boş kalabilir. "
        "Başka HMC5883L kartlarının header'ı farklıdır: sizinkinin üzerinde yazan "
        "adları bunlarla karşılaştırın. Her kabloyu yerine göre değil, modülün "
        "pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "Adafruit TCA9548A I2C multiplexer": (
        "Adafruit TCA9548A I2C çoklayıcı"
    ),
    "One I2C bus to eight, one at a time: 24 pins, rows 15.24 mm apart": (
        "Tek I2C hattını sekize böler, birer birer: 24 pin, sıralar 15,24 mm arayla"
    ),
    "VIN takes 1.8 to 5 V by the board's silkscreen. SDA and SCL are the controller's "
    "side, and each has a 10k pull-up to VIN through a solder jumper the board ships "
    "closed: cut it if another board already pulls the bus up. None of the eight "
    "channels has a pull-up, so each bus needs its own. A0, A1 and A2 are held low by "
    "10k resistors, which makes the I2C address 0x70; a solder jumper beside each ties "
    "it to VIN instead. RST is held high by a 10k resistor: pull it low to reset the "
    "chip. Both rows are 12-pin headers the board ships without, so the pins and the "
    "rows are what to check against the board in your hand. The height of what is on "
    "the board is an estimate, and so is its colour; the pins, the rows and the board "
    "outline are measured.": (
        "VIN, kartın baskısına göre 1,8 ile 5 V alır. SDA ile SCL denetleyici tarafıdır"
        " ve her birinin VIN'e, kartın kapalı gönderdiği bir lehim köprüsü üzerinden "
        "10k yukarı çekme direnci vardır: hattı başka bir kart zaten yukarı çekiyorsa "
        "köprüyü kesin. Sekiz kanalın hiçbirinde yukarı çekme direnci yoktur, bu yüzden"
        " her hat kendi direncini ister. A0, A1 ve A2 10k dirençlerle düşük tutulur, bu"
        " da I2C adresini 0x70 yapar; her birinin yanındaki lehim köprüsü onu bunun "
        "yerine VIN'e bağlar. RST 10k dirençle yüksek tutulur: çipi sıfırlamak için "
        "düşük çekin. İki sıra da kartın pinsiz gönderdiği 12 pinli header'lardır, bu "
        "yüzden elinizdeki kartta pinleri ve sıraları kontrol edin. Kartın "
        "üstündekilerin yüksekliği tahmindir, rengi de öyle; pinler, sıralar ve kart "
        "çevresi ölçülmüştür."
    ),
    "Adafruit CCS811 air quality sensor (on a header)": (
        "Adafruit CCS811 hava kalitesi sensörü (header üzerinde)"
    ),
    "Air quality (eCO2 and TVOC) sensor, on I2C. Its cable plugs into this 8-pin "
    "header: VIN 3V3 GND SDA SCL !WAKE !RST !INT from pin 1": (
        "I2C üzerinden hava kalitesi (eCO2 ve TVOC) sensörü. Kablosu bu 8 pinli "
        "header'a takılır: 1. pinden VIN 3V3 GND SDA SCL !WAKE !RST !INT"
    ),
    "VIN takes 3 to 5 V by the board's silkscreen: a 3.3 V regulator makes the chip's "
    "supply, and 3V3 is its output, not a second input. SDA and SCL go through level-"
    "shifting transistors, so the bus may run at VIN's level. !WAKE and !RST are held "
    "high by resistors on the board, each through a diode, so a pin pulling them low "
    "from outside works at either logic level. By the chip's datasheet !WAKE must be "
    "low while the chip talks on I2C, so wire it to GND or to a pin; pulling !RST low "
    "resets the chip. !INT comes straight from the chip and can stay unwired. Other "
    "CCS811 boards carry a different header, so compare the names printed on yours with"
    " these. Match each lead to the name printed beside the module's pins, not to its "
    "place: sellers' boards are not all wired in the same order.": (
        "VIN, kartın baskısına göre 3 ile 5 V alır: 3,3 V'luk bir regülatör çipin "
        "beslemesini üretir ve 3V3 onun çıkışıdır, ikinci bir giriş değildir. SDA ile "
        "SCL seviye çeviren transistörlerden geçer, bu yüzden hat VIN seviyesinde "
        "çalışabilir. !WAKE ile !RST kartın üzerindeki dirençlerle yüksek tutulur, her "
        "biri bir diyot üzerinden; böylece dışarıdan düşük çeken bir pin her iki mantık"
        " seviyesinde de çalışır. Çipin veri sayfasına göre çip I2C'de konuşurken !WAKE"
        " düşük olmalıdır, bu yüzden onu GND'ye ya da bir pine bağlayın; !RST'yi düşük "
        "çekmek çipi sıfırlar. !INT doğrudan çipten gelir ve boş kalabilir. Başka "
        "CCS811 kartlarının header'ı farklıdır: sizinkinin üzerinde yazan adları "
        "bunlarla karşılaştırın. Her kabloyu yerine göre değil, modülün pinlerinin "
        "yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "Adafruit LSM6DS3 accelerometer and gyro (on a header)": (
        "Adafruit LSM6DS3 ivmeölçer ve jiroskop (header üzerinde)"
    ),
    "6-axis accelerometer and gyroscope, on I2C or SPI. Its cable plugs into this 9-pin"
    " header: VIN 3Vo GND SCL SDA DO CS I1 I2 from pin 1": (
        "I2C veya SPI üzerinden 6 eksenli ivmeölçer ve jiroskop. Kablosu bu 9 pinli "
        "header'a takılır: 1. pinden VIN 3Vo GND SCL SDA DO CS I1 I2"
    ),
    "VIN takes 3 to 5 V by the board's silkscreen: a 3.3 V regulator makes the chip's "
    "supply, and 3Vo is its output, not a second input. SCL and SDA go through level-"
    "shifting transistors, so the bus may run at VIN's level. CS is held high on the "
    "board through a diode, which leaves the chip on I2C: pull it low only to use SPI. "
    "DO is the chip's SDO and, on I2C, its address bit: the board holds it low for the "
    "0x6A the silkscreen gives, and the AD0 solder jumper ties it to 3.3 V for the "
    "other address. I1 and I2 are the interrupt outputs and can stay unwired. The "
    "board's second header, the chip's auxiliary I2C for a sensor hub, is not drawn "
    "here. Other LSM6DS3 boards carry a different header, so compare the names printed "
    "on yours with these. Match each lead to the name printed beside the module's pins,"
    " not to its place: sellers' boards are not all wired in the same order.": (
        "VIN, kartın baskısına göre 3 ile 5 V alır: 3,3 V'luk bir regülatör çipin "
        "beslemesini üretir ve 3Vo onun çıkışıdır, ikinci bir giriş değildir. SCL ile "
        "SDA seviye çeviren transistörlerden geçer, bu yüzden hat VIN seviyesinde "
        "çalışabilir. CS kartın üzerinde bir diyot üzerinden yüksek tutulur, bu da çipi"
        " I2C'de bırakır: yalnızca SPI kullanmak için düşük çekin. DO çipin SDO'sudur "
        "ve I2C'de adres bitidir: kart onu baskının verdiği 0x6A için düşük tutar, AD0 "
        "lehim köprüsü de öteki adres için 3,3 V'a bağlar. I1 ile I2 kesme çıkışlarıdır"
        " ve boş kalabilir. Kartın ikinci header'ı, çipin sensör merkezi için yardımcı "
        "I2C'si, burada çizilmemiştir. Başka LSM6DS3 kartlarının header'ı farklıdır: "
        "sizinkinin üzerinde yazan adları bunlarla karşılaştırın. Her kabloyu yerine "
        "göre değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların "
        "kartları aynı sırayla bağlanmamıştır."
    ),
    "Adafruit BNO055 orientation sensor (on a header)": (
        "Adafruit BNO055 yönelim sensörü (header üzerinde)"
    ),
    "9-axis orientation sensor with sensor fusion, on I2C. Its cable plugs into this "
    "6-pin header: Vin 3Vo GND SDA SCL RST from pin 1": (
        "I2C üzerinden sensör birleştirmeli 9 eksenli yönelim sensörü. Kablosu bu 6 "
        "pinli header'a takılır: 1. pinden Vin 3Vo GND SDA SCL RST"
    ),
    "Vin takes 3 to 5 V by the board's silkscreen: a 3.3 V regulator makes the chip's "
    "supply, and 3Vo is its output, not a second input. SDA and SCL go through level-"
    "shifting transistors and RST through a diode, which is what the silkscreen means "
    "by 5 V OK. The board's second header, PS0, PS1, INT and ADR, is not drawn here: "
    "the board holds all three inputs low, which is I2C at 0x28, and ADR tied to 3.3 V "
    "gives 0x29. Other BNO055 boards carry a different header, so compare the names "
    "printed on yours with these. Match each lead to the name printed beside the "
    "module's pins, not to its place: sellers' boards are not all wired in the same "
    "order.": (
        "Vin, kartın baskısına göre 3 ile 5 V alır: 3,3 V'luk bir regülatör çipin "
        "beslemesini üretir ve 3Vo onun çıkışıdır, ikinci bir giriş değildir. SDA ile "
        "SCL seviye çeviren transistörlerden, RST de bir diyottan geçer; baskıdaki 5 V "
        "OK bunu söyler. Kartın ikinci header'ı, PS0, PS1, INT ve ADR, burada "
        "çizilmemiştir: kart üç girişi de düşük tutar, bu da 0x28 adresinde I2C'dir; "
        "ADR'yi 3,3 V'a bağlamak 0x29 verir. Başka BNO055 kartlarının header'ı "
        "farklıdır: sizinkinin üzerinde yazan adları bunlarla karşılaştırın. Her "
        "kabloyu yerine göre değil, modülün pinlerinin yanında yazan ada göre bağlayın:"
        " satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "Adafruit AS5600 magnetic angle sensor (on a header)": (
        "Adafruit AS5600 manyetik açı sensörü (header üzerinde)"
    ),
    "12-bit magnetic rotary position sensor, on I2C. Its cable plugs into this 6-pin "
    "header: VIN 3Vo GND SCL SDA OUT from pin 1": (
        "I2C üzerinden 12 bit manyetik dönme konumu sensörü. Kablosu bu 6 pinli "
        "header'a takılır: 1. pinden VIN 3Vo GND SCL SDA OUT"
    ),
    "VIN takes 3 to 5 V by the board's silkscreen: a 3.3 V regulator makes the chip's "
    "supply, and 3Vo is its output, not a second input. SCL and SDA go through level-"
    "shifting transistors, so the bus may run at VIN's level. OUT comes straight from "
    "the chip and is its analog or PWM output, as the chip is set up. The board ties "
    "the chip's DIR pin low with a closed solder jumper. Other AS5600 boards carry a "
    "different header, so compare the names printed on yours with these. Match each "
    "lead to the name printed beside the module's pins, not to its place: sellers' "
    "boards are not all wired in the same order.": (
        "VIN, kartın baskısına göre 3 ile 5 V alır: 3,3 V'luk bir regülatör çipin "
        "beslemesini üretir ve 3Vo onun çıkışıdır, ikinci bir giriş değildir. SCL ile "
        "SDA seviye çeviren transistörlerden geçer, bu yüzden hat VIN seviyesinde "
        "çalışabilir. OUT doğrudan çipten gelir ve çip nasıl ayarlandıysa analog ya da "
        "PWM çıkışıdır. Kart çipin DIR pinini kapalı bir lehim köprüsüyle düşük tutar. "
        "Başka AS5600 kartlarının header'ı farklıdır: sizinkinin üzerinde yazan adları "
        "bunlarla karşılaştırın. Her kabloyu yerine göre değil, modülün pinlerinin "
        "yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "Adafruit QMC5883P magnetometer (on a header)": (
        "Adafruit QMC5883P manyetometre (header üzerinde)"
    ),
    "3-axis magnetometer (compass), on I2C. Its cable plugs into this 5-pin header: VIN"
    " 3Vo GND SCL SDA from pin 1": (
        "I2C üzerinden 3 eksenli manyetometre (pusula). Kablosu bu 5 pinli header'a "
        "takılır: 1. pinden VIN 3Vo GND SCL SDA"
    ),
    "VIN takes 3 to 5 V by the board's silkscreen: a 3.3 V regulator makes the chip's "
    "supply, and 3Vo is its output, not a second input. SCL and SDA go through level-"
    "shifting transistors, so the bus may run at VIN's level. The QMC5883P is not the "
    "QMC5883L or the HMC5883L: its I2C address is 0x2C by the silkscreen, so code "
    "written for those two will not find it. Other QMC5883P boards carry a different "
    "header, so compare the names printed on yours with these. Match each lead to the "
    "name printed beside the module's pins, not to its place: sellers' boards are not "
    "all wired in the same order.": (
        "VIN, kartın baskısına göre 3 ile 5 V alır: 3,3 V'luk bir regülatör çipin "
        "beslemesini üretir ve 3Vo onun çıkışıdır, ikinci bir giriş değildir. SCL ile "
        "SDA seviye çeviren transistörlerden geçer, bu yüzden hat VIN seviyesinde "
        "çalışabilir. QMC5883P, QMC5883L ya da HMC5883L değildir: baskıya göre I2C "
        "adresi 0x2C'dir, bu yüzden o ikisi için yazılmış kod onu bulamaz. Başka "
        "QMC5883P kartlarının header'ı farklıdır: sizinkinin üzerinde yazan adları "
        "bunlarla karşılaştırın. Her kabloyu yerine göre değil, modülün pinlerinin "
        "yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "SparkFun TEMT6000 ambient light sensor (on a header)": (
        "SparkFun TEMT6000 ortam ışığı sensörü (header üzerinde)"
    ),
    "Analog ambient light sensor, a phototransistor with its resistor. Its cable plugs "
    "into this 3-pin header: VCC GND SIG from pin 1": (
        "Analog ortam ışığı sensörü, direnciyle birlikte bir fototransistör. Kablosu bu"
        " 3 pinli header'a takılır: 1. pinden VCC GND SIG"
    ),
    "The phototransistor's collector is on VCC and its emitter is SIG, with a 10k "
    "resistor from SIG to GND on the board, so SIG is a voltage that rises with the "
    "light, for an analog input. The board prints no supply range: read the one on the "
    "maker's page for the revision you hold. Other TEMT6000 boards carry a different "
    "header, so compare the names printed on yours with these. Match each lead to the "
    "name printed beside the module's pins, not to its place: sellers' boards are not "
    "all wired in the same order.": (
        "Fototransistörün kolektörü VCC'de, emiteri SIG'dedir; kartın üzerinde SIG'den "
        "GND'ye 10k bir direnç vardır. Böylece SIG, ışıkla birlikte yükselen bir "
        "gerilimdir ve bir analog girişe bağlanır. Kart bir besleme aralığı yazmaz: "
        "elinizdeki revizyon için üreticinin sayfasındakine bakın. Başka TEMT6000 "
        "kartlarının header'ı farklıdır: sizinkinin üzerinde yazan adları bunlarla "
        "karşılaştırın. Her kabloyu yerine göre değil, modülün pinlerinin yanında yazan"
        " ada göre bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "Adafruit MAX98357 I2S amplifier (on a header)": (
        "Adafruit MAX98357 I2S yükselteç (header üzerinde)"
    ),
    "I2S class D mono amplifier, 3 W into 4 to 8 ohm. Its cable plugs into this 7-pin "
    "header: Vin GND SD GAIN DIN BCLK LRC from pin 1": (
        "I2S girişli, D sınıfı mono ses yükseltici, 4 ile 8 ohm'a 3 W. Kablosu bu 7 "
        "pinli header'a takılır: 1. pinden Vin GND SD GAIN DIN BCLK LRC"
    ),
    "Vin takes 2.5 to 5.5 V by the board's silkscreen and is the chip's supply itself, "
    "with no regulator between. SD is the chip's SD_MODE, held high through a 1 megohm "
    "resistor on the board, so left unwired the amplifier plays, as (L+R)/2 by the "
    "silkscreen; GAIN left open is the 9 dB the silkscreen gives as default. DIN, BCLK "
    "and LRC are the I2S data, bit clock and word select. The speaker goes to the "
    "board's 2-pin screw terminal, not drawn here: both of its terminals are driven by "
    "the chip, so neither goes to GND. Other MAX98357 boards carry a different header, "
    "so compare the names printed on yours with these. Match each lead to the name "
    "printed beside the module's pins, not to its place: sellers' boards are not all "
    "wired in the same order.": (
        "Vin, kartın baskısına göre 2,5 ile 5,5 V alır ve aradan regülatör geçmeden "
        "çipin beslemesinin kendisidir. SD çipin SD_MODE pinidir ve kartta 1 megohm'luk"
        " bir dirençle yüksek tutulur; bu yüzden boş bırakılırsa yükseltici çalışır ve "
        "baskıya göre (L+R)/2 çıkış verir. GAIN boş bırakılırsa baskının varsayılan "
        "diye yazdığı 9 dB olur. DIN, BCLK ve LRC I2S'in veri, bit saati ve kelime "
        "seçme hatlarıdır. Hoparlör kartın 2 pinli vidalı terminaline gider, burada "
        "çizilmemiştir: terminalin iki ucunu da çip sürer, bu yüzden hiçbiri GND'ye "
        "bağlanmaz. Başka MAX98357 kartlarının header'ı farklıdır: sizinkinin üzerinde "
        "yazan adları bunlarla karşılaştırın. Her kabloyu yerine göre değil, modülün "
        "pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "Adafruit TMC2209 stepper driver (on a header)": (
        "Adafruit TMC2209 step motor sürücüsü (header üzerinde)"
    ),
    "Stepper motor driver with step and direction pins and a serial UART. Its cable "
    "plugs into this 10-pin header: VDD GND DIR STEP MS1 MS2 DIAG INDEX UART EN from "
    "pin 1": (
        "Adım ve yön pinli, seri UART'lı step motor sürücüsü. Kablosu bu 10 pinli "
        "header'a takılır: 1. pinden VDD GND DIR STEP MS1 MS2 DIAG INDEX UART EN"
    ),
    "VDD is the logic supply, 3 to 5 V by the silkscreen. The motor's supply, 5 to 29 V"
    " by the silkscreen, and the four coil outputs are on the board's 6-pin terminal, "
    "not drawn here: its ground and this header's GND must be joined. STEP and DIR move"
    " the motor; EN is the chip's enable, which the datasheet makes active low; MS1 and"
    " MS2 pick the microstep, 8, 16, 32 or 64 by the silkscreen. UART is the chip's "
    "single-wire serial, for the advanced settings. DIAG and INDEX are outputs from the"
    " chip and can stay unwired. The board's trimmer sets the current limit, 0 to 2 A "
    "by its silkscreen. Other TMC2209 boards carry a different header, so compare the "
    "names printed on yours with these. Match each lead to the name printed beside the "
    "module's pins, not to its place: sellers' boards are not all wired in the same "
    "order.": (
        "VDD mantık beslemesidir, baskıya göre 3 ile 5 V. Motorun beslemesi, baskıya "
        "göre 5 ile 29 V, ve dört bobin çıkışı kartın 6 pinli terminalindedir, burada "
        "çizilmemiştir: onun toprağı ile bu header'ın GND'si birleştirilmelidir. STEP "
        "ile DIR motoru döndürür; EN çipin etkinleştirme pinidir ve veri sayfasına göre"
        " düşükte etkindir; MS1 ile MS2 mikro adımı seçer, baskıya göre 8, 16, 32 ya da"
        " 64. UART çipin tek telli seri hattıdır, gelişmiş ayarlar içindir. DIAG ile "
        "INDEX çipten çıkan çıkışlardır ve boş kalabilir. Kartın trimeri akım sınırını "
        "ayarlar, baskıya göre 0 ile 2 A. Başka TMC2209 kartlarının header'ı farklıdır:"
        " sizinkinin üzerinde yazan adları bunlarla karşılaştırın. Her kabloyu yerine "
        "göre değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların "
        "kartları aynı sırayla bağlanmamıştır."
    ),
    "SparkFun AD8232 heart rate monitor (on a header)": (
        "SparkFun AD8232 kalp ritmi monitörü (header üzerinde)"
    ),
    "Single-lead ECG front end with an analog output. Its cable plugs into this 6-pin "
    "header: GND 3.3V OUTPUT LO- LO+ !SDN from pin 1": (
        "Analog çıkışlı, tek derivasyonlu EKG ön katı. Kablosu bu 6 pinli header'a "
        "takılır: 1. pinden GND 3.3V OUTPUT LO- LO+ !SDN"
    ),
    "3.3V feeds the chip directly, with no regulator on the board, and the AD8232 is a "
    "2.0 to 3.5 V part by its datasheet: never feed it 5 V. OUTPUT is the analog "
    "signal. LO- and LO+ are the leads-off detection outputs. !SDN is the shutdown pin,"
    " held high by a 10k resistor on the board, so left unwired the chip runs and "
    "pulling it low shuts it down. The electrodes, RL, LA and RA, go to the board's "
    "separate 3-pin header or its 3.5 mm jack, not drawn here. Other AD8232 boards "
    "carry a different header, so compare the names printed on yours with these. Match "
    "each lead to the name printed beside the module's pins, not to its place: sellers'"
    " boards are not all wired in the same order.": (
        "3.3V çipi doğrudan besler, kartta regülatör yoktur ve AD8232 veri sayfasına "
        "göre 2,0 ile 3,5 V'luk bir parçadır: ona asla 5 V vermeyin. OUTPUT analog "
        "sinyaldir. LO- ile LO+ elektrot kopma algılama çıkışlarıdır. !SDN kapatma "
        "pinidir ve kartta 10k bir dirençle yüksek tutulur; boş bırakılırsa çip "
        "çalışır, düşük çekmek onu kapatır. Elektrotlar, RL, LA ve RA, kartın ayrı 3 "
        "pinli header'ına ya da 3,5 mm jakına gider, burada çizilmemiştir. Başka AD8232"
        " kartlarının header'ı farklıdır: sizinkinin üzerinde yazan adları bunlarla "
        "karşılaştırın. Her kabloyu yerine göre değil, modülün pinlerinin yanında yazan"
        " ada göre bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "Adafruit MPR121 capacitive touch sensor (on a header)": (
        "Adafruit MPR121 kapasitif dokunmatik sensör (header üzerinde)"
    ),
    "12-key capacitive touch sensor, on I2C. Its cable plugs into this 7-pin "
    "header: VIN 3Vo GND ADDR SDA SCL IRQ from pin 1": (
        "I2C üzerinden 12 tuşlu kapasitif dokunmatik sensör. Kablosu bu 7 pinli "
        "header'a takılır: 1. pinden VIN 3Vo GND ADDR SDA SCL IRQ"
    ),
    "VIN takes 3 to 5 V: a 3.3 V regulator makes the chip's supply, and 3Vo is "
    "its output (100 mA by Adafruit's page), not a second input. SDA and SCL go "
    "through level-shifting transistors with 10k pull-ups to VIN, so the bus "
    "idles at VIN's level. A 100k resistor holds ADDR low for the address "
    "0x5A; tying ADDR to 3Vo gives 0x5B, to SDA 0x5C and to SCL 0x5D, so leave "
    "it unwired for the default. IRQ is the chip's own 3.3 V line, pulled up "
    "by the board's LED and a 1k resistor: it goes low when a touch changes "
    "and stays low until the chip is read over I2C, so it can stay unwired. "
    "The electrodes are on the 13-pin header along the other edge, which this "
    "part does not have: wire them to your touch pads from the board's own "
    "header. Other MPR121 boards carry a different header, so compare the "
    "names printed on yours with these. Match each lead to the name printed beside the "
    "module's pins, not to its place: sellers' boards are not all wired in the same "
    "order.": (
        "VIN 3 ile 5 V alır: 3,3 V'luk bir regülatör çipin beslemesini üretir ve 3Vo "
        "onun çıkışıdır (Adafruit'in sayfasına göre 100 mA), ikinci bir giriş değildir. "
        "SDA ile SCL seviye çeviren transistörlerden ve VIN'e giden 10k'lık yukarı "
        "çekme dirençlerinden geçer, bu yüzden hat VIN seviyesinde bekler. 100k'lık bir "
        "direnç ADDR'yi düşük tutar ve adres 0x5A olur; ADDR'yi 3Vo'ya bağlarsanız "
        "0x5B, SDA'ya bağlarsanız 0x5C, SCL'ye bağlarsanız 0x5D olur, varsayılan için "
        "boş bırakın. IRQ çipin kendi 3,3 V hattıdır ve kartın LED'i ile 1k'lık bir "
        "dirençle yukarı çekilir: dokunma değişince düşer ve çip I2C'den okunana kadar "
        "düşük kalır, boş bırakılabilir. Elektrotlar karşı kenardaki 13 pinli header'da "
        "durur, bu parçada o yoktur: dokunma yüzeylerinizi kartın kendi header'ından "
        "bağlayın. Başka MPR121 kartlarının header'ı farklıdır: sizinkinin üzerinde "
        "yazan adları bunlarla karşılaştırın. Her kabloyu yerine göre değil, modülün "
        "pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "HC-12 433 MHz serial radio module (on a header)": (
        "HC-12 433 MHz seri telsiz modülü (header üzerinde)"
    ),
    "433 MHz wireless serial module, about 1 km in the open. Its cable plugs into "
    "this 5-pin header: VCC GND RXD TXD SET from pin 1": (
        "Açık alanda yaklaşık 1 km menzilli 433 MHz kablosuz seri modül. Kablosu bu 5 "
        "pinli header'a takılır: 1. pinden VCC GND RXD TXD SET"
    ),
    "VCC takes 3.2 to 5.5 V and the supply has to give at least 200 mA while "
    "the module transmits: the manual says that above 4.5 V a 1N4007 diode in "
    "series with VCC keeps the module's own regulator cool. TXD goes to the "
    "controller's RX and RXD to its TX. The manuals disagree on RXD's level: "
    "V2.4 says 3.3 V TTL and V2.6 says 3.3 to 5 V, so from a 5 V board's TX "
    "bring it down through a divider of 1k and 2k unless the manual for your "
    "revision says otherwise. SET has a 10k pull-up inside: leave it unwired to "
    "send and receive, and pull it low to give the module AT commands. Other "
    "HC-12 boards carry a different header, so compare the names printed on "
    "yours with these. Match each lead to the name printed beside the "
    "module's pins, not to its place: sellers' boards are not all wired in the same "
    "order.": (
        "VCC 3,2 ile 5,5 V alır ve modül gönderirken besleme en az 200 mA vermelidir: "
        "kılavuza göre 4,5 V'un üzerinde VCC'ye seri bir 1N4007 diyot modülün kendi "
        "regülatörünü serin tutar. TXD denetleyicinin RX'ine, RXD de TX'ine gider. "
        "Kılavuzlar RXD'nin seviyesinde ayrılır: V2.4 3,3 V TTL der, V2.6 3,3 ile 5 V "
        "der; bu yüzden 5 V'luk bir kartın TX'inden, sizin sürümünüzün kılavuzu başka "
        "bir şey demiyorsa, 1k ve 2k'lık bir bölücüyle düşürün. SET'in içinde 10k'lık "
        "bir yukarı çekme vardır: göndermek ve almak için boş bırakın, modüle AT "
        "komutu vermek için düşük çekin. Başka HC-12 kartlarının header'ı farklıdır: "
        "sizinkinin üzerinde yazan adları bunlarla karşılaştırın. Her kabloyu yerine "
        "göre değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların "
        "kartları aynı sırayla bağlanmamıştır."
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
    "FTDI / USB-serial basic board (on a header)": (
        "FTDI / USB-seri temel kart (header üzerinde)"
    ),
    "USB to serial adapter for programming and logging. Its cable plugs into this 6-pin"
    " header: GND CTS VCC TXO RXI DTR from pin 1": (
        "Programlama ve kayıt için USB - seri adaptör. Kablosu bu 6 pinli header'a "
        "takılır: 1. pinden GND CTS VCC TXO RXI DTR"
    ),
    "TXO goes to the controller's RX and RXI to its TX. Pick 3.3 V or 5 V on the "
    "board's jumper before it is plugged into the target, and DTR goes to the target's "
    "reset through a 100 nF capacitor. Match each lead to the name printed beside the "
    "module's pins, not to its place: sellers' boards are not all wired in the same "
    "order.": (
        "TXO denetleyicinin RX'ine, RXI de TX'ine gider. Hedefe takmadan önce kartın "
        "jumper'ıyla 3,3 V ya da 5 V seçin; DTR hedefin reset ucuna 100 nF'lık bir "
        "kondansatörle gider. Her kabloyu yerine göre değil, modülün pinlerinin yanında"
        " yazan ada göre bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "PCA9685 16-channel PWM driver (on a header)": (
        "PCA9685 16 kanallı PWM sürücü (header üzerinde)"
    ),
    "16-channel 12-bit PWM driver on I2C, for servos and LEDs. Its cable plugs into "
    "this 6-pin header: V+ VCC SDA SCL OE GND from pin 1": (
        "Servolar ve LED'ler için I2C üzerinden 16 kanallı, 12 bit PWM sürücü. Kablosu "
        "bu 6 pinli header'a takılır: 1. pinden V+ VCC SDA SCL OE GND"
    ),
    "V+ is the servo supply and is not the chip's VCC: bring each from its own source, "
    "with the grounds joined. OE enables the outputs when low and a 10k on the board "
    "holds it low, so it can be left unwired. The servo plugs are on the board's 16 "
    "channel headers, not on this one. Match each lead to the name printed beside the "
    "module's pins, not to its place: sellers' boards are not all wired in the same "
    "order.": (
        "V+ servo beslemesidir ve çipin VCC'si değildir: her birini kendi kaynağından "
        "getirin, topraklar birleşik olsun. OE düşükken çıkışları açar ve kartın "
        "üzerindeki bir 10k onu düşük tutar, bu yüzden boş bırakılabilir. Servo fişleri"
        " bu header'da değil, kartın 16 kanal header'ındadır. Her kabloyu yerine göre "
        "değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların "
        "kartları aynı sırayla bağlanmamıştır."
    ),
    "SparkFun HX711 load cell amplifier": (
        "SparkFun HX711 yük hücresi yükselteci"
    ),
    "24-bit ADC for a load cell, two 1 x 5 headers 27.94 mm apart": (
        "Yük hücresi için 24 bit ADC, 27,94 mm arayla iki adet 1 x 5 header"
    ),
    "The load cell goes to A+ and A-, a second one to the 2-pin B+ and B- header, which"
    " is off the pin grid. AVDD is made on the board from VCC and brought out for the "
    "bridge; VCC and VDD are both inputs, so feed them from one supply. The green HX711"
    " boards sold under the same name carry a different header, so compare the names "
    "printed on the board with these before using it. The height of what is on the "
    "board is an estimate, and so is its colour; the pins, the rows and the board "
    "outline are measured.": (
        "Yük hücresi A+ ve A-'ye, ikincisi ise ızgaranın dışındaki 2 pinli B+ ve B- "
        "header'ına gider. AVDD kartın üzerinde VCC'den üretilir ve köprü için dışarı "
        "çıkarılır; VCC ile VDD ikisi de girişlerdir, bu yüzden ikisini aynı kaynaktan "
        "besleyin. Aynı adla satılan yeşil HX711 kartlarının header'ı farklıdır: "
        "kullanmadan önce kartın üzerinde yazan adları bunlarla karşılaştırın. Kartın "
        "üzerindekilerin yüksekliği ve rengi tahmindir; pinler, sıralar ve kart "
        "çerçevesi ölçülmüştür."
    ),
    "Adafruit 2.8 in TFT touch breakout, ILI9341 (on a header)": (
        "Adafruit 2,8 inç TFT dokunmatik kart, ILI9341 (header üzerinde)"
    ),
    "2.8 inch colour TFT, 240 x 320, with a resistive touchscreen and a microSD socket,"
    " on SPI. Its cable plugs into this 20-pin header: GND Vin 3Vo CLK MISO MOSI CS D/C"
    " RST Lite Y+ X+ Y- X- IM3 IM2 IM1 IM0 CCS CD from pin 1": (
        "Dirençli dokunmatik ekranlı ve microSD yuvalı, SPI üzerinden 240 x 320, 2,8 "
        "inç renkli TFT. Kablosu bu 20 pinli header'a takılır: 1. pinden GND Vin 3Vo "
        "CLK MISO MOSI CS D/C RST Lite Y+ X+ Y- X- IM3 IM2 IM1 IM0 CCS CD"
    ),
    "Vin takes 3 to 5 V and a 3.3 V regulator on the board makes 3Vo, which is an "
    "output and not a second supply. CS, D/C, CLK, RST, MOSI and CCS go through "
    "74LVC245 level shifters on the board, so 3.3 V and 5 V logic both do; MISO is a "
    "3.3 V output. Lite is the base of the backlight's transistor: high lights it, and "
    "tying it to Vin keeps it lit. X+, Y+, X- and Y- are the resistive touchscreen's "
    "four wires, and CCS and CD the microSD socket's chip select and card detect, which"
    " share CLK, MISO and MOSI. IM0 to IM3 are the controller's interface-mode inputs, "
    "set by the solder jumpers beside them; the board's silkscreen says to close IM1, "
    "IM2 and IM3 for SPI. Other ILI9341 modules sold as 2.8 inch SPI carry a shorter "
    "header with other names, so compare the names printed on the board with these "
    "before using it. Match each lead to the name printed beside the module's pins, not"
    " to its place: sellers' boards are not all wired in the same order.": (
        "Vin 3 ile 5 V alır, kartın üzerindeki 3,3 V'luk regülatör 3Vo'yu üretir; 3Vo "
        "bir çıkıştır, ikinci bir besleme girişi değildir. CS, D/C, CLK, RST, MOSI ve "
        "CCS kartın üzerindeki 74LVC245 seviye çeviricilerinden geçer, bu yüzden hem "
        "3,3 V hem 5 V mantık olur; MISO 3,3 V'luk bir çıkıştır. Lite arka ışığın "
        "transistörünün beyzidir: yüksek olunca yanar, Vin'e bağlarsanız hep yanık "
        "kalır. X+, Y+, X- ve Y- dirençli dokunmatik ekranın dört teli, CCS ile CD de "
        "microSD yuvasının çip seçimi ve kart algılamasıdır; ikisi de CLK, MISO ve "
        "MOSI'yi paylaşır. IM0 ile IM3 denetleyicinin arayüz kipi girişleridir ve "
        "yanlarındaki lehim köprüleriyle ayarlanır; kartın baskısı SPI için IM1, IM2 ve"
        " IM3'ün kapatılmasını söyler. 2,8 inç SPI diye satılan başka ILI9341 "
        "modüllerinin header'ı daha kısadır ve adları farklıdır: kullanmadan önce "
        "kartın üzerinde yazan adları bunlarla karşılaştırın. Her kabloyu yerine göre "
        "değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların "
        "kartları aynı sırayla bağlanmamıştır."
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
    "3-pin sensor board (S + -), on a header": "3 pinli sensör kartı (S + -), header üzerinde",
    "The small three-pin KY boards of a sensor kit: one signal pin, supply and ground. "
    "Its cable plugs into this 3-pin header: S + - from pin 1": (
        "Bir sensör kitinin küçük üç pinli KY kartları: bir sinyal pini, besleme ve "
        "toprak. Kablosu bu 3 pinli header'a takılır: 1. pinden S + -"
    ),
    "The manual numbers some of these boards S + - and others - + S, the same three pins "
    "from the other end, so a board plugged straight into a header must match its "
    "silkscreen. S is the signal: an output on a sensor, an input on a buzzer. A water level sensor prints its three pins - + S, as Conrad's SE045 datasheet lists them, S being the signal pin. Match each "
    "lead to the name printed beside the module's pins, not to its place: sellers' boards "
    "are not all wired in the same order.": (
        "Kılavuz bu kartların bazılarını S + -, bazılarını - + S diye numaralar; bunlar "
        "aynı üç pinin öbür uçtan sayılmasıdır. Bu yüzden bir kartı doğrudan header'a "
        "takarsanız serigrafisine uydurun. S sinyaldir: bir sensörde çıkış, bir buzzer'da "
        "giriştir. Bir su seviyesi sensörü üç pinini - + S diye basar (Conrad'ın SE045 veri sayfası da böyle sıralar); S sinyal pinidir. Her kabloyu yerine göre değil, modülün pinlerinin yanında yazan ada "
        "göre bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "4-pin sensor board (D0 + - A0), on a header": "4 pinli sensör kartı (D0 + - A0), header üzerinde",
    "The four-pin KY boards with a comparator and a sensitivity trimmer: a digital and an "
    "analog output. Its cable plugs into this 4-pin header: D0 + - A0 from pin 1": (
        "Karşılaştırıcılı ve hassasiyet trimmerli dört pinli KY kartları: bir sayısal ve "
        "bir analog çıkış. Kablosu bu 4 pinli header'a takılır: 1. pinden D0 + - A0"
    ),
    "The manual calls pin 1 the digital signal and pin 4 the analog signal; your board "
    "may print other names for them. The digital output comes from the on-board "
    "comparator, set with the trimmer; the analog one is the sensor's own, and the manual "
    "says it reads inverted: a stronger input is a lower voltage. The soil moisture (FC-28, YL-69), rain (YL-83, FC-37) and MQ-2 gas boards have the same four pins in other orders, and write the outputs DO and AO or DOUT and AOUT: Components101 lists VCC GND D0 A0 for the rain board and VCC GND DO AO for the soil one, and Waveshare's MQ-2 datasheet lists DOUT AOUT GND VCC. Match each lead to the "
    "name printed beside the module's pins, not to its place: sellers' boards are not all "
    "wired in the same order.": (
        "Kılavuz 1. pine sayısal sinyal, 4. pine analog sinyal der; kartınız onlara başka "
        "adlar basmış olabilir. Sayısal çıkış kart üzerindeki karşılaştırıcıdan gelir ve "
        "trimmerle ayarlanır; analog çıkış sensörün kendisidir ve kılavuza göre ters "
        "okunur: daha güçlü bir girdi daha düşük bir gerilimdir. Toprak nemi (FC-28, YL-69), yağmur (YL-83, FC-37) ve MQ-2 gaz kartlarında aynı dört pin başka sıralarla bulunur ve çıkışlar DO ve AO ya da DOUT ve AOUT diye yazılır: Components101 yağmur kartı için VCC GND D0 A0, toprak kartı için VCC GND DO AO sırasını, Waveshare'in MQ-2 veri sayfası ise DOUT AOUT GND VCC sırasını verir. Her kabloyu yerine göre "
        "değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları "
        "aynı sırayla bağlanmamıştır."
    ),
    "DS1307 Tiny RTC module (on a header)": "DS1307 Tiny RTC modülü (header üzerinde)",
    "Real-time clock on I2C. Its cable plugs into this 7-pin header: SQ DS SCL SDA VCC GND "
    "BAT from pin 1": (
        "I2C üzerinde 24C32 EEPROM'lu gerçek zamanlı saat. Kablosu bu 7 pinli header'a "
        "takılır: 1. pinden SQ DS SCL SDA VCC GND BAT"
    ),
    "Feed VCC 5 V: the datasheet gives the module 5 V and the chip 4.5 to 5.5 V on VCC, so "
    "this is not a 3.3 V board. BAT is the plus of the backup cell, 2.0 to 3.5 V. The "
    "datasheet lists DS as the main supply's plus through 3.3 kOhm, so it is not a signal: "
    "it is wired to the supply, not to a pin. SQ is the programmable square-wave output. "
    "Match each lead to the name printed beside the module's pins, not to its place: "
    "sellers' boards are not all wired in the same order.": (
        "VCC pinine 5 V verin: veri sayfası modüle 5 V, çipin VCC ucuna 4,5 ile 5,5 V "
        "verir; yani bu 3,3 V'luk bir kart değildir. BAT yedek pilin artısıdır (2,0 ile 3,5 "
        "V). Veri sayfası DS'yi, 3,3 kOhm üzerinden ana beslemenin artısı olarak listeler; "
        "yani sinyal değildir, bir pine değil beslemeye bağlanır. SQ programlanabilir kare "
        "dalga çıkışıdır. Her kabloyu yerine göre değil, modülün pinlerinin yanında yazan "
        "ada göre bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "TP4056 charger module with protection, on six wires": "TP4056 şarj modülü, korumalı, altı telli",
    "Charges one lithium cell from a 5 V input and cuts the load off when the cell is flat "
    "or the load shorted: the cell on B, the load on OUT": (
        "Tek lityum hücreyi 5 V girişten şarj eder; hücre boşalırsa ya da yük kısa devre "
        "olursa yükü keser: hücre B uçlarına, yük OUT uçlarına"
    ),
    "Put the load on OUT+ and OUT-, not on B+ and B-: the protection switches OUT, so a "
    "load on B goes round it. OUT- is not the same wire as B-: it is the protection's "
    "switch, and it opens on overdischarge (2.4 V) or overcurrent (3 A); the page says a "
    "tripped module is often reset by briefly applying the input. The input is recommended "
    "at 4.5 to 5.5 V, 8 V at the very most.": (
        "Yükü B+ ve B- değil, OUT+ ve OUT- uçlarına bağlayın: koruma OUT uçlarını "
        "anahtarlar, B uçlarına bağlanan yük korumayı atlar. OUT- ile B- aynı tel değildir: "
        "OUT- korumanın anahtarıdır ve aşırı deşarjda (2,4 V) ya da aşırı akımda (3 A) "
        "açılır; sayfa, devreye giren modülün çoğunlukla girişe kısa süre gerilim verilerek "
        "sıfırlandığını söyler. Giriş 4,5 ile 5,5 V önerilir, en çok 8 V."
    ),
    "MT3608 boost module, on four wires": "MT3608 yükseltici modül, dört telli",
    "Steps a voltage up: 2 to 24 V in, 5 to 28 V out, set with its trimmer": (
        "Gerilimi yükseltir: 2 ile 24 V giriş, 5 ile 28 V çıkış, trimmerle ayarlanır"
    ),
    "A boost converter's output must stay above its input: if turning the trimmer changes "
    "nothing, the output equals the input, and a 12 V input cannot give 9 V. Set the "
    "trimmer with the output unloaded and a meter on VOUT+ and VOUT- before you connect "
    "what it feeds. Components101 says the output must always be higher than the input, and "
    "its page mentions no protection against a reversed input, so check VIN+ against the "
    "supply's plus.": (
        "Yükseltici bir dönüştürücünün çıkışı girişinin üstünde kalmalıdır: trimmeri "
        "çevirmek bir şey değiştirmiyorsa çıkış girişe eşittir ve 12 V giriş 9 V veremez. "
        "Beslediği devreyi bağlamadan önce, çıkış yüksüzken ve VOUT+ ile VOUT- uçlarında "
        "bir ölçü aletiyle trimmeri ayarlayın. Components101 çıkışın girişten hep yüksek "
        "olması gerektiğini söyler ve sayfası ters girişe karşı bir korumadan söz etmez; bu "
        "yüzden VIN+ ucunu besleme kaynağının artısıyla karşılaştırın."
    ),
    "XL6009 boost module, on four wires": (
        "XL6009 yükseltici modül, dört telli"
    ),
    "Steps a voltage up, with a 4 A limit: 3 to 32 V in, 5 to 35 V out, set with its "
    "trimmer": (
        "Gerilimi yükseltir, 4 A sınırıyla: 3 ile 32 V giriş, 5 ile 35 V çıkış, "
        "trimmerle ayarlanır"
    ),
    "A boost converter's output must stay above its input: if turning the trimmer "
    "changes nothing, the output equals the input, and a 12 V input cannot give 9 V. "
    "Set the trimmer with the output unloaded and a meter on OUT+ and OUT- before you "
    "connect what it feeds. Components101 recommends a heat sink above 15 W of output, "
    "and its page mentions no protection against a reversed input, so check IN+ against"
    " the supply's plus.": (
        "Yükseltici bir dönüştürücünün çıkışı girişinin üstünde kalmalıdır: trimmeri "
        "çevirmek bir şey değiştirmiyorsa çıkış girişe eşittir ve 12 V giriş 9 V "
        "veremez. Beslediği devreyi bağlamadan önce, çıkış yüksüzken ve OUT+ ile OUT- "
        "uçlarında bir ölçü aletiyle trimmeri ayarlayın. Components101 15 W'ın "
        "üstündeki çıkışta bir soğutucu önerir ve sayfası ters girişe karşı bir "
        "korumadan söz etmez; bu yüzden IN+ ucunu besleme kaynağının artısıyla "
        "karşılaştırın."
    ),
    "AMS1117-3.3 regulator module, on three wires": "AMS1117-3.3 regülatör modülü, üç telli",
    "Fixed 3.3 V linear regulator on a small board: 4.75 to 12 V in, 800 mA at most": (
        "Küçük bir kart üzerinde sabit 3,3 V doğrusal regülatör: 4,75 ile 12 V giriş, en "
        "çok 800 mA"
    ),
    "Its manual says a reversed input shorts the module: check VIN against the supply's "
    "plus. It is a linear regulator, so what it drops from the input is heat: 5 V in and "
    "500 mA out is 0.85 W in the chip. Input and output share the one GND.": (
        "Kılavuzu, ters bağlanan girişin modülü kısa devre yaptığını söyler: VIN ucunu "
        "besleme kaynağının artısıyla karşılaştırın. Doğrusal bir regülatördür, yani "
        "girişten düşürdüğü şey ısıdır: 5 V giriş ve 500 mA çıkışta çipte 0,85 W harcanır. "
        "Giriş ve çıkış tek GND'yi paylaşır."
    ),
    "TFT 1.8 in ST7735 128x160 module (on a header)": "TFT 1,8 inç ST7735 128x160 modülü (header üzerinde)",
    "1.8 inch colour TFT, 128 x 160, on SPI. Its cable plugs into this 8-pin header: VCC "
    "GND CS RESET A0 SDA SCK LED from pin 1": (
        "SPI üzerinde 1,8 inç renkli TFT, 128 x 160. Kablosu bu 8 pinli header'a takılır: "
        "1. pinden VCC GND CS RESET A0 SDA SCK LED"
    ),
    "The page gives the logic IO as 3.3 V (TTL), so a 5 V board wants level shifting on CS, "
    "RESET, A0, SDA and SCK. CS and RESET are low-level enable and low-level reset; A0 "
    "selects register (high) or data (low); SDA is the SPI write-data line here, not I2C, "
    "and SCK its clock. LED is the backlight: high lights it, and it says to tie 3.3 V to "
    "it for always on. Match each lead to the name printed beside the module's pins, not to "
    "its place: sellers' boards are not all wired in the same order.": (
        "Sayfa mantık IO'yu 3,3 V (TTL) olarak verir; bu yüzden 5 V'luk bir kart CS, RESET, "
        "A0, SDA ve SCK üzerinde seviye çevirici ister. CS düşük seviyede etkin, RESET "
        "düşük seviyede sıfırlar; A0 register (yüksek) ya da veri (düşük) seçer; SDA burada "
        "I2C değil SPI yazma veri hattıdır, SCK onun saatidir. LED arka ışıktır: yüksek "
        "seviye yakar ve hep yanık kalması için ona 3,3 V bağlanmasını söyler. Her kabloyu "
        "yerine göre değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların "
        "kartları aynı sırayla bağlanmamıştır."
    ),
    "Adafruit RFM9x LoRa radio breakout (on a header)": (
        "Adafruit RFM9x LoRa radyo kartı (header üzerinde)"
    ),
    "LoRa packet radio (RFM95W, 868 or 915 MHz) on SPI. Its cable plugs into this 9-pin"
    " header: VIN GND EN G0 SCK MISO MOSI CS RST from pin 1": (
        "SPI üzerinden LoRa paket radyosu (RFM95W, 868 ya da 915 MHz). Kablosu bu 9 "
        "pinli header'a takılır: 1. pinden VIN GND EN G0 SCK MISO MOSI CS RST"
    ),
    "VIN takes 3.3 to 5.5 V by the board's silkscreen: a 3.3 V regulator makes the "
    "radio's supply, and EN is its enable, pulled up to VIN by a resistor on the board,"
    " so leave it unwired to keep the radio on. SCK, MOSI, CS and RST go through a "
    "level shifter on the board, so the silkscreen calls the SPI logic 3 to 5 V safe, "
    "and CS and RST are held high by resistors to VIN. MISO and G0 come straight from "
    "the radio at 3 V; G0 is its DIO0 line. The radio needs an antenna for its band: at"
    " 868 or 915 MHz a quarter-wave wire is about 8 cm. The same board is sold with an "
    "RFM69HCW radio, with this header, so check what is printed on yours. Match each "
    "lead to the name printed beside the module's pins, not to its place: sellers' "
    "boards are not all wired in the same order.": (
        "VIN, kartın baskısına göre 3,3 ile 5,5 V alır: kartın üzerindeki 3,3 V'luk bir"
        " regülatör radyonun beslemesini üretir, EN de onun etkinleştirme ucudur ve "
        "kartın üzerindeki bir dirençle VIN'e çekilmiştir; radyo açık kalsın diye boş "
        "bırakın. SCK, MOSI, CS ve RST kartın üzerindeki bir seviye çeviriciden geçer, "
        "bu yüzden baskı SPI mantığına 3 ile 5 V'ta güvenli der; CS ile RST de "
        "dirençlerle VIN'e çekilerek yüksek tutulur. MISO ve G0 doğrudan radyodan 3 "
        "V'luk olarak gelir; G0 onun DIO0 hattıdır. Radyonun bandına uygun bir anten "
        "gerekir: 868 ya da 915 MHz'de çeyrek dalga tel yaklaşık 8 cm'dir. Aynı kart bu"
        " header'la bir RFM69HCW radyosuyla da satılır, bu yüzden sizinkinin üzerinde "
        "ne yazdığına bakın. Her kabloyu yerine göre değil, modülün pinlerinin yanında "
        "yazan ada göre bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "Nokia 5110 LCD module (on a header)": "Nokia 5110 LCD modülü (header üzerinde)",
    "84 x 48 monochrome LCD (PCD8544) on SPI. Its cable plugs into this 8-pin header: RST "
    "CE DC DIN CLK VCC LIGHT GND from pin 1": (
        "SPI üzerinde 84 x 48 tek renkli LCD (PCD8544). Kablosu bu 8 pinli header'a "
        "takılır: 1. pinden RST CE DC DIN CLK VCC LIGHT GND"
    ),
    "Feed VCC 3.3 V: the first page gives 2.7 to 3.3 V, and neither page says the signal "
    "pins tolerate 5 V, so a 5 V Arduino wants a divider or level shifter on RST, CE, DC, "
    "DIN and CLK. The boards print the backlight pin as LIGHT or BL, and the pages differ "
    "on it: Espruino wires it to GND for backlight on, the other says it lights when "
    "powered. Read your seller's note before you tie it. The second page numbers the pins "
    "from the other end, GND first. Match each lead to the name printed beside the module's "
    "pins, not to its place: sellers' boards are not all wired in the same order.": (
        "VCC pinine 3,3 V verin: ilk sayfa 2,7 ile 3,3 V verir ve iki sayfa da sinyal "
        "pinlerinin 5 V'a dayandığını söylemez; bu yüzden 5 V'luk bir Arduino RST, CE, DC, "
        "DIN ve CLK için bölücü ya da seviye çevirici ister. Kartlar arka ışık pinini LIGHT "
        "ya da BL diye basar ve sayfalar bu konuda ayrışır: Espruino arka ışık için onu "
        "GND'ye bağlar, diğeri besleme verilince yandığını söyler. Bağlamadan önce "
        "satıcınızın notunu okuyun. İkinci sayfa pinleri öbür uçtan, GND'den başlayarak "
        "numaralar. Her kabloyu yerine göre değil, modülün pinlerinin yanında yazan ada "
        "göre bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "TTP223 touch module (on a header)": "TTP223 dokunmatik modülü (header üzerinde)",
    "Capacitive touch button on a 24 mm board: its output goes high while touched. Its "
    "cable plugs into this 3-pin header: GND VCC SIG from pin 1": (
        "24 mm'lik kart üzerinde kapasitif dokunma düğmesi: dokunulduğu sürece çıkışı "
        "yükselir. Kablosu bu 3 pinli header'a takılır: 1. pinden GND VCC SIG"
    ),
    "In AZ-Delivery's datasheet the output is low until the body touches the sensor and "
    "high while it does; with no touch for more than 12 s the sensor falls into its "
    "low-power mode, where it answers in 220 ms against 60 ms in fast mode. Other boards of "
    "the part may print its three pins in another order. Match each lead to the name "
    "printed beside the module's pins, not to its place: sellers' boards are not all wired "
    "in the same order.": (
        "AZ-Delivery'nin veri sayfasında çıkış, vücut sensöre dokunana kadar düşük, "
        "dokunduğu sürece yüksektir; 12 sn'den uzun süre dokunulmazsa sensör düşük güç "
        "kipine düşer ve hızlı kipteki 60 ms yerine 220 ms'de yanıt verir. Bu parçanın "
        "başka kartları üç pinini başka sırayla basabilir. Her kabloyu yerine göre değil, "
        "modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı "
        "sırayla bağlanmamıştır."
    ),
    "KY-009 RGB LED module, SMD (on a header)": "KY-009 RGB LED modülü, SMD (header üzerinde)",
    "RGB LED on a small board, one pin per colour and a common ground. Its cable plugs "
    "into this 4-pin header: GND G R B from pin 1": (
        "Küçük bir kart üzerinde RGB LED, renk başına bir pin ve ortak toprak. Kablosu bu "
        "4 pinli header'a takılır: 1. pinden GND G R B"
    ),
    "Green comes before red here: the KY-016 puts red first, so the two boards are not "
    "interchangeable on one header. The manual lists a series resistor for each colour, "
    "100 ohm for green and blue and 180 ohm for red, at 3.3 V and at 5 V: look at your "
    "board for resistors before driving it. Match each lead to the name printed beside "
    "the module's pins, not to its place: sellers' boards are not all wired in the same "
    "order.": (
        "Burada yeşil kırmızıdan önce gelir: KY-016 kırmızıyı öne koyar, yani iki kart "
        "aynı header'da birbirinin yerine kullanılamaz. Kılavuz her renk için bir seri "
        "direnç verir: 3,3 V'ta da 5 V'ta da yeşil ve mavi için 100 ohm, kırmızı için 180 "
        "ohm; sürmeden önce kartınızda direnç olup olmadığına bakın. Her kabloyu yerine "
        "göre değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların "
        "kartları aynı sırayla bağlanmamıştır."
    ),
    "KY-016 RGB LED module, 5 mm (on a header)": "KY-016 RGB LED modülü, 5 mm (header üzerinde)",
    "RGB 5 mm LED on a small board, one pin per colour and a common ground. Its cable "
    "plugs into this 4-pin header: GND R G B from pin 1": (
        "Küçük bir kart üzerinde 5 mm RGB LED, renk başına bir pin ve ortak toprak. "
        "Kablosu bu 4 pinli header'a takılır: 1. pinden GND R G B"
    ),
    "Red comes before green here: the KY-009 puts green first, so the two boards are not "
    "interchangeable on one header. The manual lists a series resistor for each colour, "
    "100 ohm for green and blue and 180 ohm for red, at 3.3 V and at 5 V: look at your "
    "board for resistors before driving it. Match each lead to the name printed beside "
    "the module's pins, not to its place: sellers' boards are not all wired in the same "
    "order.": (
        "Burada kırmızı yeşilden önce gelir: KY-009 yeşili öne koyar, yani iki kart aynı "
        "header'da birbirinin yerine kullanılamaz. Kılavuz her renk için bir seri direnç "
        "verir: 3,3 V'ta da 5 V'ta da yeşil ve mavi için 100 ohm, kırmızı için 180 ohm; "
        "sürmeden önce kartınızda direnç olup olmadığına bakın. Her kabloyu yerine göre "
        "değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları "
        "aynı sırayla bağlanmamıştır."
    ),
    "KY-011 / KY-029 two-colour LED module (on a header)": "KY-011 / KY-029 iki renkli LED modülü (header üzerinde)",
    "Red and green LED on a small board, one pin per colour and a common ground. Its "
    "cable plugs into this 3-pin header: G R GND from pin 1": (
        "Küçük bir kart üzerinde kırmızı ve yeşil LED, renk başına bir pin ve ortak "
        "toprak. Kablosu bu 3 pinli header'a takılır: 1. pinden G R GND"
    ),
    "KY-011 carries a 5 mm LED and KY-029 a 3 mm one; both are numbered the same. For the "
    "KY-011 the manual gives a series resistor of 120 ohm per colour at 3.3 V and 220 ohm "
    "per colour at 5 V: look at your board for resistors before driving it. Match each "
    "lead to the name printed beside the module's pins, not to its place: sellers' boards "
    "are not all wired in the same order.": (
        "KY-011 5 mm, KY-029 3 mm LED taşır; ikisi de aynı numaralanmıştır. KY-011 için "
        "kılavuz renk başına seri direnç olarak 3,3 V'ta 120 ohm, 5 V'ta 220 ohm verir: "
        "sürmeden önce kartınızda direnç olup olmadığına bakın. Her kabloyu yerine göre "
        "değil, modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları "
        "aynı sırayla bağlanmamıştır."
    ),
    "KY-053 ADS1115 ADC module (on a header)": "KY-053 ADS1115 ADC modülü (header üzerinde)",
    "Four-input analog-to-digital converter board (ADS1115, 16 bit, I2C). Its cable plugs "
    "into this 10-pin header: VDD GND SCL SDA ADDR ALRT A0 A1 A2 A3 from pin 1": (
        "Dört girişli analog-sayısal çevirici kart (ADS1115, 16 bit, I2C). Kablosu bu 10 "
        "pinli header'a takılır: 1. pinden VDD GND SCL SDA ADDR ALRT A0 A1 A2 A3"
    ),
    "The pins are in the order the manual's photograph shows them down the board's edge, "
    "VDD at the top. ADDR and ALRT are not part of the I2C wiring: connect the supply, "
    "SCL and SDA first. Match each lead to the name printed beside the module's pins, not "
    "to its place: sellers' boards are not all wired in the same order.": (
        "Pinler, kılavuzdaki fotoğrafın kartın kenarı boyunca gösterdiği sırayla "
        "dizilidir; VDD en üsttedir. ADDR ve ALRT I2C bağlantısının parçası değildir: "
        "önce beslemeyi, SCL ve SDA'yı bağlayın. Her kabloyu yerine göre değil, modülün "
        "pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı sırayla "
        "bağlanmamıştır."
    ),
    "KY-051 level shifter module (on a header)": "KY-051 seviye çevirici modülü (header üzerinde)",
    "Four-channel voltage translator board with two supply sides, A and B. Its cable "
    "plugs into this 12-pin header: VCCb VCCa B1 A1 B2 A2 B3 A3 B4 A4 OE GND from pin 1": (
        "İki besleme tarafı (A ve B) olan dört kanallı gerilim çevirici kart. Kablosu bu "
        "12 pinli header'a takılır: 1. pinden VCCb VCCa B1 A1 B2 A2 B3 A3 B4 A4 OE GND"
    ),
    "The real board has its two rows of six on opposite edges, so this header is not its "
    "shape: it is only the twelve wires listed in pairs, VCCb with VCCa, B1 with A1 and "
    "so on. Wire each by its label. The board prints VCCa 1.2 to 3.6 V and VCCb 1.7 to "
    "5.5 V, and the manual says VCCb must be higher than or equal to VCCa. GND is on the "
    "A side: join it to yours. Match each lead to the name printed beside the module's "
    "pins, not to its place: sellers' boards are not all wired in the same order.": (
        "Gerçek kartın altışarlı iki sırası karşılıklı kenarlardadır; bu yüzden bu header "
        "kartın şekli değildir, yalnızca on iki telin çiftler halinde listesidir: VCCb "
        "ile VCCa, B1 ile A1 ve böyle sürer. Her teli etiketine göre bağlayın. Kart VCCa "
        "için 1,2 ila 3,6 V, VCCb için 1,7 ila 5,5 V basar; kılavuza göre VCCb, VCCa'dan "
        "yüksek ya da ona eşit olmalıdır. GND A tarafındadır: onu kendi toprağınıza "
        "bağlayın. Her kabloyu yerine göre değil, modülün pinlerinin yanında yazan ada "
        "göre bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "RC522 RFID reader module (on a header)": "RC522 RFID okuyucu modülü (header üzerinde)",
    "13.56 MHz RFID reader on SPI. Its cable plugs into this 8-pin header: 3.3V RST GND IRQ "
    "MISO MOSI SCK SDA from pin 1": (
        "SPI üzerinden 13,56 MHz RFID okuyucu. Kablosu bu 8 pinli header'a takılır: 1. "
        "pinden 3.3V RST GND IRQ MISO MOSI SCK SDA"
    ),
    "Feed it 3.3 V, not 5 V: its supply pin is the one marked 3.3V. SDA is the SPI chip "
    "select here, not an I2C data line; MISO is also marked SCL and TX for the chip's other "
    "modes. IRQ may stay unconnected. Sellers print the same row from the other end, SDA "
    "first: read the names, not the place. Match each lead to the name printed beside the "
    "module's pins, not to its place: sellers' boards are not all wired in the same order.": (
        "Ona 5 V değil 3,3 V verin: besleme pini 3.3V yazan pindir. SDA burada SPI çip "
        "seçimidir, bir I2C veri hattı değil; MISO çipin diğer kipleri için SCL ve TX olarak "
        "da işaretlidir. IRQ bağlanmadan kalabilir. Satıcılar aynı sırayı öbür uçtan, önce "
        "SDA olacak şekilde basar: yere değil, adlara bakın. Her kabloyu yerine göre değil, "
        "modülün pinlerinin yanında yazan ada göre bağlayın: satıcıların kartları aynı "
        "sırayla bağlanmamıştır."
    ),
    "L298N dual motor driver board (on a header)": "L298N çift motor sürücü kartı (header üzerinde)",
    "Dual H-bridge board for two DC motors. Its cable plugs into this 6-pin header: ENA IN1 "
    "IN2 IN3 IN4 ENB from pin 1": (
        "İki DC motor için çift H-köprü kartı. Kablosu bu 6 pinli header'a takılır: 1. "
        "pinden ENA IN1 IN2 IN3 IN4 ENB"
    ),
    "ENA and ENB enable the two channels and IN1 and IN2, IN3 and IN4 set each one's "
    "direction. The motors, the motor supply (the 12V terminal) and the 5V terminal are on "
    "the board's own screw terminals, not on this header: join the supply's GND to your "
    "logic ground. With the motor supply above 12 V take off the board's 5V jumper and feed "
    "your logic separately. Match each lead to the name printed beside the module's pins, "
    "not to its place: sellers' boards are not all wired in the same order.": (
        "ENA ve ENB iki kanalı etkinleştirir; IN1 ile IN2, IN3 ile IN4 her birinin yönünü "
        "belirler. Motorlar, motor beslemesi (12V ucu) ve 5V ucu bu header'da değil, kartın "
        "kendi vidalı klemenslerindedir: beslemenin GND ucunu mantık topraklamanıza bağlayın. "
        "Motor beslemesi 12 V'un üzerindeyse kartın 5V jumper'ını çıkarın ve mantığınızı ayrı "
        "besleyin. Her kabloyu yerine göre değil, modülün pinlerinin yanında yazan ada göre "
        "bağlayın: satıcıların kartları aynı sırayla bağlanmamıştır."
    ),
    "DC motor, 130 size, on two wires": "DC motor, 130 boy, iki telli",
    "Small brushed motor off the board on two wires: swap them and it turns the other way": (
        "Karttan ayrı, iki telli küçük fırçalı motor: telleri değiştirirseniz ters yöne döner"
    ),
    "Do not drive it from a pin: the FA-130 stalls at 2.1 A at 3 V, so put a transistor or a "
    "motor driver between them, and a diode across the motor with its banded end on the "
    "supply side. Measure yours stalled before you choose the transistor: kit motors "
    "differ.": (
        "Bir pinden sürmeyin: FA-130 3 V'ta tıkandığında 2,1 A çeker; bu yüzden araya bir "
        "transistör ya da motor sürücü koyun, motorun uçlarına da çizgili ucu besleme "
        "tarafında olacak şekilde bir diyot bağlayın. Transistörü seçmeden önce sizinkini "
        "tıkalıyken ölçün: kit motorları birbirinden farklıdır."
    ),
    "Piezo disc, 7BB-27-4, on two wires": "Piezo disk, 7BB-27-4, iki telli",
    "Bare piezo diaphragm off the board on two wires: it sounds from a tone on a pin and "
    "stays silent on DC": (
        "Karttan ayrı, iki telli çıplak piezo disk: bir pindeki ton ile ses verir, DC'de "
        "sessiz kalır"
    ),
    "The leads are red and black and Murata's catalog marks no polarity: either goes to "
    "either. A disc has no driver in it, so give it a tone (tone() on an Arduino), not DC: "
    "Murata says to avoid DC across it for long periods, and to put a 1 to 2 kohm resistor "
    "in series with the driving pin. Never press on the middle of the disc, which cracks "
    "the ceramic, and do not pull on its wires.": (
        "Telleri kırmızı ve siyahtır, Murata'nın kataloğu kutup belirtmez: biri ötekinin "
        "yerine bağlanabilir. Diskin içinde sürücü yoktur; ona DC değil bir ton verin "
        "(Arduino'da tone()): Murata, uzun süre DC uygulanmamasını ve sürücü pinine seri "
        "1 ila 2 kohm'luk bir direnç konmasını söyler. Diskin ortasına bastırmayın, "
        "seramik çatlar; tellerini de çekmeyin."
    ),
    "Reed switch, glass, 14 mm": "Reed anahtar, cam, 14 mm",
    "Glass capsule that closes when a magnet comes near, 14 mm long, legs 20.32 mm apart: no "
    "polarity": (
        "Mıknatıs yaklaşınca kapanan cam kapsül, 14 mm uzunlukta, bacaklar arası 20,32 mm: "
        "kutupsuz"
    ),
    "Bend the leads at least 2 mm from the glass, and clamp the lead with pliers between the "
    "glass and the bend, and again when you solder: Standex-Meder says mechanical and heat "
    "stress on the leads must be kept off the glass, and that bending them changes the "
    "switch's sensitivity, so test it with the magnet after it is soldered. A drop from "
    "more than 30 cm can change it or destroy it. The holes are 8 pitches (20.32 mm) apart "
    "for a 14 mm capsule, which leaves 3.16 mm of lead at each end.": (
        "Bacakları camdan en az 2 mm uzakta bükün; cam ile büküm arasındaki bacağı, lehim "
        "yaparken de, bir pensle tutun: Standex-Meder, bacaklardaki mekanik ve ısıl "
        "gerilimin cama geçmemesini ve bacakları bükmenin anahtarın duyarlılığını "
        "değiştirdiğini söyler; bu yüzden lehimledikten sonra mıknatısla deneyin. 30 cm'den "
        "yüksekten düşürmek duyarlılığı değiştirebilir ya da anahtarı bozabilir. 14 mm'lik "
        "kapsül için delikler 8 adım (20,32 mm) arayla durur; bu, her uçta 3,16 mm bacak "
        "bırakır."
    ),
    "SS-12D00 slide switch": "SS-12D00 kaydırmalı anahtar",
    "Small slide switch, one pole two positions: the lever joins the middle pin to one end "
    "or the other": (
        "Küçük kaydırmalı anahtar, tek kutuplu iki konumlu: kol orta pini uçlardan birine "
        "ya da ötekine bağlar"
    ),
    "Measure the lever's height and the body on yours: the lever is not in the height DRC "
    "checks, so a lid or a panel above the switch is yours to check, and other makers' "
    "SS-12D00s are a little larger than the Vimex drawing. The 2.5 mm pin pitch against "
    "2.54 puts the end pins 0.04 mm off their holes, inside what a 1 mm hole has to spare. "
    "Which end the lever's first position joins is not something this part can say: try "
    "the switch with a meter before you wire the two ends.": (
        "Sizinkinin kolunun yüksekliğini ve gövdesini ölçün: kol DRC'nin denetlediği "
        "yüksekliğe dahil değildir; bu yüzden anahtarın üstündeki kapak ya da panel sizin "
        "denetiminizdedir, ayrıca başka üreticilerin SS-12D00'ları Vimex çiziminden biraz "
        "büyüktür. 2,5 mm pin aralığı 2,54'e karşı uçtaki pinleri deliklerinden 0,04 mm "
        "kaydırır, 1 mm'lik bir deliğin payı içindedir. Kolun ilk konumunun hangi ucu "
        "bağladığını bu parça söyleyemez: iki ucu bağlamadan önce anahtarı ölçü aletiyle "
        "deneyin."
    ),
    "Crystal, low can HC-49/S (HC-49/US)": "Kristal, alçak kılıf HC-49/S (HC-49/US)",
    "Quartz crystal for a microcontroller's clock, the low can that comes in kits, 3.5 mm "
    "tall, legs 4.88 mm apart": (
        "Mikrodenetleyicinin saati için kuvars kristal, kitlerde bulunan alçak kılıf, 3,5 mm "
        "yüksekliğinde, bacaklar arası 4,88 mm"
    ),
    "This is the LOW can, 3.5 mm tall, the one in most kits (HC-49/S, HC-49/US); the tall "
    "HC-49/U, 13.46 mm, is the other entry. Its legs are 4.88 mm apart against the board's "
    "5.08 two holes over, so each ends 0.10 mm off its hole, 0.20 mm at the drawing's worst, "
    "inside the 0.27 mm a 0.457 mm leg has to spare in a 1 mm hole. Its frequency is printed "
    "on the can: put it in the value. Abracon sells an insulator tab as an option, so a bare "
    "can is metal: keep it off bare copper.": (
        "Bu ALÇAK kılıftır, 3,5 mm yüksekliğinde, çoğu kitte bulunan (HC-49/S, HC-49/US); "
        "13,46 mm'lik uzun HC-49/U öbür kayıttır. Bacakları 4,88 mm arayla durur, kartın iki "
        "delik ötedeki 5,08 mm'sine karşı her biri deliğinden 0,10 mm kayar, çizimin en kötü "
        "durumunda 0,20 mm; bu, 1 mm'lik bir delikte 0,457 mm'lik bir bacağın payı olan 0,27 "
        "mm'nin içindedir. Frekansı kılıfın üzerinde yazar: değer alanına yazın. Abracon "
        "seçenek olarak yalıtım pulu satar; yani çıplak kılıf metaldir: çıplak bakırdan uzak "
        "tutun."
    ),
    "Crystal, tall can HC-49/U": "Kristal, uzun kılıf HC-49/U",
    "Quartz crystal for a microcontroller's clock, the tall can, 13.46 mm tall, legs 4.88 mm "
    "apart": (
        "Mikrodenetleyicinin saati için kuvars kristal, uzun kılıf, 13,46 mm yüksekliğinde, "
        "bacaklar arası 4,88 mm"
    ),
    "This is the TALL can, 13.46 mm high. Most crystals in kits are the low one (HC-49/S, "
    "HC-49/US), 3.5 mm: if yours is that, take the other entry. Its legs are 4.88 mm apart "
    "against the board's 5.08 two holes over, so each ends 0.10 mm off its hole. Its "
    "frequency is printed on the can: put it in the value.": (
        "Bu UZUN kılıftır, 13,46 mm yüksekliğinde. Kitlerdeki kristallerin çoğu alçak olandır "
        "(HC-49/S, HC-49/US), 3,5 mm: sizinki oysa öbür kaydı seçin. Bacakları 4,88 mm arayla "
        "durur, kartın iki delik ötedeki 5,08 mm'sine karşı her biri deliğinden 0,10 mm kayar. "
        "Frekansı kılıfın üzerinde yazar: değer alanına yazın."
    ),
    "Optocoupler with the transistor's base brought out, CTR over 100 %, 5000 V isolation": (
        "Transistörün bazı dışarı çıkarılmış optokuplör, akım aktarım oranı %100'ün üzerinde, "
        "5000 V yalıtım"
    ),
    "Pin 3 is not connected. Pin 6, the base, is brought out for those who want it: leave it "
    "open if you do not.": (
        "3. pin bağlı değildir. 6. pin, yani baz, isteyenler için dışarı çıkarılmıştır: "
        "kullanmayacaksanız açık bırakın."
    ),
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
    "ESP8266 board, 30 pins, rows 22.86 mm apart": (
        "ESP8266 kartı, 30 pin, sıralar arası 22,86 mm"
    ),
    "Its pins are 3.3 V logic. VIN is the 5 V rail: USB feeds it through a Schottky "
    "diode, or feed it yourself. D3, D4 and D8 are GPIO0, GPIO2 and GPIO15, which "
    "choose how it boots: nothing may hold D3 or D4 low, or D8 high, as it starts. SD0 "
    "to SD3, CMD and CLK are the module's flash: leave them free. LoLin's wider \"V3\", "
    "rows 27.94 mm apart, is another board. The height of what is on the board is an "
    "estimate, and so is its colour; the pins, the rows and the board outline are "
    "measured.": (
        "Pinleri 3,3 V mantık seviyesindedir. VIN 5 V hattıdır: USB onu bir Schottky diyot "
        "üzerinden besler, ya da siz besleyin. D3, D4 ve D8, kartın nasıl açılacağını seçen "
        "GPIO0, GPIO2 ve GPIO15'tir: açılırken hiçbir şey D3'ü ya da D4'ü low'a, D8'i "
        "high'a çekmemelidir. SD0-SD3, CMD ve CLK modülün flash hattıdır: bunları boş "
        "bırakın. LoLin'in daha geniş \"V3\" kartı, sıraları 27,94 mm arayla, başka bir "
        "karttır. Kartın üzerindekilerin yüksekliği ve rengi tahmindir; pinler, sıralar ve "
        "kart çerçevesi ölçülmüştür."
    ),
    "Temperature, humidity and pressure on I2C or SPI, 3 to 5 V": (
        "I2C ya da SPI üzerinden sıcaklık, nem ve basınç, 3-5 V"
    ),
    "Temperature and pressure on I2C or SPI, 3 to 5 V": (
        "I2C ya da SPI üzerinden sıcaklık ve basınç, 3-5 V"
    ),
    "VIN takes 3 to 5 V and 3Vo gives out the board's 3.3 V. For I2C, SCK is SCL and "
    "SDI is SDA, with CS left alone: the address is 0x77, or 0x76 with SDO to GND. For "
    "SPI, SDO is the data out. The height of what is on the board is an estimate, and "
    "so is its colour; the pins, the rows and the board outline are measured.": (
        "VIN 3-5 V alır, 3Vo kartın 3,3 V'unu verir. I2C için SCK SCL, SDI SDA'dır; CS'ye "
        "dokunmayın: adres 0x77'dir, SDO GND'ye bağlıysa 0x76. SPI için SDO veri çıkışıdır. "
        "Kartın üzerindekilerin yüksekliği ve rengi tahmindir; pinler, sıralar ve kart "
        "çerçevesi ölçülmüştür."
    ),
    "VIN takes 3 to 5 V and 3Vo gives out the board's 3.3 V. For I2C, SCK is SCL and "
    "SDI is SDA, with CS left alone: the address is 0x77, or 0x76 with SDO to GND. For "
    "SPI, SDO is the data out. The two STEMMA QT sockets carry the same I2C. The height "
    "of what is on the board is an estimate, and so is its colour; the pins, the rows "
    "and the board outline are measured.": (
        "VIN 3-5 V alır, 3Vo kartın 3,3 V'unu verir. I2C için SCK SCL, SDI SDA'dır; CS'ye "
        "dokunmayın: adres 0x77'dir, SDO GND'ye bağlıysa 0x76. SPI için SDO veri çıkışıdır. "
        "İki STEMMA QT soketi de aynı I2C hattını taşır. Kartın üzerindekilerin yüksekliği "
        "ve rengi tahmindir; pinler, sıralar ve kart çerçevesi ölçülmüştür."
    ),
    "Adafruit BME280 (original)": (
        "Adafruit BME280 (orijinal)"
    ),
    "Adafruit BMP280 (original)": (
        "Adafruit BMP280 (orijinal)"
    ),
    "ESP32-WROOM-32 dev board, 30 pins, rows 25.4 mm apart": (
        "ESP32-WROOM-32 geliştirme kartı, 30 pin, sıralar arası 25,4 mm"
    ),
    "Sold by many makers: the 30 pins and their order are fixed, the parts' places vary "
    "from one to the next, and this drawing is one of them to about half a millimetre. "
    "The 38-pin ESP32-DevKitC is a different board with its own entry: count your pins. "
    "Its pins are 3.3 V; VIN takes 5 V. VP, VN, D34 and D35 are inputs only, and "
    "nothing may hold D12 high as it starts (it sets the flash voltage). The height of "
    "what is on the board is an estimate, and so is its colour; the pins, the rows and "
    "the board outline are measured.": (
        "Birçok üretici satar: 30 pin ve sıraları sabittir, parçaların yeri birinden "
        "ötekine değişir ve bu çizim yaklaşık yarım milimetreyle onlardan biridir. 38 pinli "
        "ESP32-DevKitC başka bir karttır ve kendi girdisi vardır: pinlerinizi sayın. "
        "Pinleri 3,3 V'tur; VIN 5 V alır. VP, VN, D34 ve D35 yalnızca giriştir; açılırken "
        "hiçbir şey D12'yi high'a çekmemelidir (flash gerilimini o seçer). Kartın "
        "üzerindekilerin yüksekliği ve rengi tahmindir; pinler, sıralar ve kart çerçevesi "
        "ölçülmüştür."
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
    "Wiring to review": "Gözden geçirilecek kablolama",
    "{count} ring of wires, each over another's end: none can go in first": (
        "her biri bir başkasının ucunun üzerinden geçen {count} tel halkası: hiçbiri önce "
        "döşenemez"
    ),
    "{count} rings of wires, each over another's end: none can go in first": (
        "her biri bir başkasının ucunun üzerinden geçen {count} tel halkası: hiçbiri önce "
        "döşenemez"
    ),
    "{count} place a wire lies over a pin": "bir telin bir pinin üzerinden geçtiği {count} yer",
    "{count} places a wire lies over a pin": "bir telin bir pinin üzerinden geçtiği {count} yer",
    "{count} place a wire lies over where other copper ends": (
        "bir telin başka bir bakırın bittiği yerin üzerinden geçtiği {count} yer"
    ),
    "{count} places a wire lies over where other copper ends": (
        "bir telin başka bir bakırın bittiği yerin üzerinden geçtiği {count} yer"
    ),
    "{count} wire stacked three or more deep": "üç ya da daha çok kat üst üste binen {count} tel",
    "{count} wires stacked three or more deep": "üç ya da daha çok kat üst üste binen {count} tel",
    "{count} wire": "{count} tel",
    "{count} wires": "{count} tel",
    "{count} bend": "{count} büküm",
    "{count} bends": "{count} büküm",
    "{count} solder trace": "{count} lehim yolu",
    "{count} solder traces": "{count} lehim yolu",
    "{count} pin": "{count} pin",
    "{count} end of other copper": "başka bakırın {count} ucu",
    "{count} ends of other copper": "başka bakırın {count} ucu",
    "{count} crossing": "{count} kesişme",
    "{count} crossings": "{count} kesişme",
    "stacked over {count} wire": "{count} telin üstünde",
    "stacked over {count} wires": "{count} telin üstünde",
    "Select these wires on the board.": "Bu telleri kartta seçer.",
    "Redo Wiring Without This Wire": "Bu Tel Olmadan Yeniden Kablola",
    "Try every wiring style…": "Her kablolama tarzını deneyin…",
    "Wires the board once in each style and offers the one easiest to build. It takes several times as long as Auto-wire; Cancel keeps the best found so far.": (
        "Kartı her tarzda bir kez kablolar ve yapması en kolay olanı önerir. Otomatik "
        "Kablolamadan birkaç kat uzun sürer; İptal o ana kadar bulunan en iyisini tutar."
    ),
    "It is the wiring already on the board, so nothing changed.": (
        "Bu, kartta zaten olan kablolama; hiçbir şey değişmedi."
    ),
    "Wire the board in “{style}”?": "Kart “{style}” tarzında kablolansın mı?",
    "Use This Wiring": "Bu Kablolamayı Kullan",
    "Wiring in “{style}”": "“{style}” tarzında kablolama",
    "Wiring in “{style}” ({number} of {total})…": "“{style}” tarzında kablolanıyor ({number}/{total})…",
    "stopped after {count} of {total} styles": "{total} tarzın {count} tanesinden sonra durduruldu",
    "Wires this net again, keeping clear of the holes this wire lies across, so the same wire cannot come back.": (
        "Bu neti yeniden kablolar ve bu telin üzerinden geçtiği deliklerden uzak durur; "
        "böylece aynı tel geri gelemez."
    ),
    "Without the wire {start} → {end}: nothing new lies across its holes.": (
        "{start} → {end} teli olmadan: yeni bakırın hiçbiri onun deliklerinin üzerinden geçmez."
    ),
    "{count} connection could not be wired without it.": "Bu tel olmadan {count} bağlantı kablolanamadı.",
    "{count} connections could not be wired without it.": "Bu tel olmadan {count} bağlantı kablolanamadı.",
    "Wire every connection not wired yet, in the Wiring Style. The copper already there "
    "stays, and one Ctrl+Z takes back what it lays. When everything is wired, it offers to "
    "wire it all again.": (
        "Henüz kablolanmamış her bağlantıyı Kablolama Tarzı'na göre kablolar. Var olan bakır "
        "yerinde kalır; döşediğini tek bir Ctrl+Z geri alır. Her şey zaten kabloluysa hepsini "
        "yeniden kablolamayı önerir."
    ),
    "Wire only the connections of the parts or nets selected, and leave the rest.": (
        "Yalnızca seçili parçaların ya da netlerin bağlantılarını kablolar, gerisine dokunmaz."
    ),
    "What Auto-wire reaches for first: solder traces, wires, bent legs, or a balance of "
    "them.": (
        "Otomatik kablolamanın önce neye başvurduğu: lehim yolları, teller, bükülmüş bacaklar "
        "ya da bunların dengesi."
    ),
    "What a solder trace does where it meets copper it may not cross.": (
        "Lehim yolunun geçemeyeceği bir bakırla karşılaştığında ne yaptığı."
    ),
    "Take up the wiring of the selected parts or nets and lay it again. Asked first; one "
    "Ctrl+Z puts it back.": (
        "Seçili parçaların ya da netlerin kablolamasını söküp yeniden döşer. Önce sorar; tek "
        "bir Ctrl+Z geri getirir."
    ),
    "Take up copper joined to nothing: what a moved part leaves behind at its old pins.": (
        "Hiçbir şeye bağlı olmayan bakırı söker: taşınan bir parçanın eski pinlerinde "
        "bıraktığı bakır."
    ),
    "Co&mpare With Before": "Ö&ncesiyle Karşılaştır",
    "Draw the wiring as it was before the last Auto-wire or Redo Wiring, dashed, over the "
    "wiring there now.": (
        "Son Otomatik Kablolama ya da Kablolamayı Yeniden Yap öncesindeki kablolamayı, şimdiki "
        "kablolamanın üzerine kesikli çizer."
    ),
    "Dashed: the wiring before the last Auto-wire or Redo Wiring. Wiring ▸ Compare With "
    "Before again hides it.": (
        "Kesikli çizgiler: son Otomatik Kablolama ya da Kablolamayı Yeniden Yap öncesindeki "
        "kablolama. Kablolama ▸ Öncesiyle Karşılaştır yeniden seçilince gizlenir."
    ),
    "Of the copper on these nets: {kept} left exactly as it is, {gone} taken up, {laid} "
    "laid new. Copper with no net assigned is left alone.": (
        "Bu netlerin bakırından {kept} parça olduğu gibi kalır, {gone} parça sökülür, {laid} "
        "parça yeniden döşenir. Neti atanmamış bakıra dokunulmaz."
    ),
    "{gone} taken up, {laid} laid, {kept} unchanged": (
        "{gone} söküldü, {laid} döşendi, {kept} değişmedi"
    ),
    "In “{style}”, for these nets only.": "“{style}” tarzında, yalnızca bu netler için.",
    "The style the whole board is wired in.": "Bütün kartın kablolandığı tarz.",
    "This net only. The Wiring Style menu stays as it is.": (
        "Yalnızca bu net. Kablolama Tarzı menüsü olduğu gibi kalır."
    ),
    "{count} wire to look at": "bakılacak {count} tel",
    "{count} wires to look at": "bakılacak {count} tel",
    "Not wrong: wiring that works and is harder to build than it has to be. Click a row to select its wires.": (
        "Yanlış değil: çalışan ama gerektiğinden zor kurulan kablolama. Tellerini seçmek "
        "için bir satıra tıklayın."
    ),
    "Faces": "Yüzler",
    "{count} net off its face": "{count} net başka yüzde",
    "{count} nets off their face": "{count} net başka yüzde",
    "Not a problem: a face a net prefers is a price, not a rule, and Auto-wire gave it up where it had to. Click a row to light its net.": (
        "Sorun değil: bir netin tercih ettiği yüz bir kural değil, bir bedeldir; Otomatik "
        "Kablola ondan gerektiği yerde vazgeçti. Netini yakmak için bir satıra tıklayın."
    ),
    "{count} net wired off the face it prefers: why is in Problems": (
        "{count} net tercih ettiği yüzün dışında kablolandı: nedeni Sorunlar'da"
    ),
    "{count} nets wired off the face they prefer: why is in Problems": (
        "{count} net tercih ettiği yüzün dışında kablolandı: nedenleri Sorunlar'da"
    ),
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
    "{count} part is in the design: {catalog} known from the catalog, {kicad} matched by its KiCad footprint, {guess} guessed from its reference. Next: choose a board and place it.": "{count} parça tasarımda: {catalog} tanesi katalogdan tanındı, {kicad} tanesi KiCad kılıfından eşleşti, {guess} tanesi referansından tahmin edildi. Sıradaki: bir kart seçip parçayı yerleştirin.",
    "{count} parts are in the design: {catalog} known from the catalog, {kicad} matched by their KiCad footprint, {guess} guessed from their reference — check those. Next: choose a board and place them.": "{count} parça tasarımda: {catalog} tanesi katalogdan tanındı, {kicad} tanesi KiCad kılıfından eşleşti, {guess} tanesi referansından tahmin edildi — onları kontrol edin. Sıradaki: bir kart seçip parçaları yerleştirin.",
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
    "The board from the component side (Ctrl+1). Flip shows the solder side, where the traces "
    "and bare wires are; on a board with pads on both faces, what you draw goes on the face "
    "you are looking at. A hole is named like C7: column letter, row number.": (
        "Kart, parça yüzünden (Ctrl+1). Çevir, lehim yollarının ve çıplak tellerin "
        "bulunduğu lehim yüzünü gösterir; iki yüzünde ped olan bir kartta çizdiğiniz bakır, "
        "baktığınız yüze gider. Bir delik C7 gibi adlandırılır: sütun harfi, satır "
        "numarası."
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
    "An insulated wire on the component side, hopping over everything below. It takes room a "
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
    "An insulated wire on the component side, over everything below.": (
        "Parça yüzünde, alttaki her şeyin üstünden geçen izoleli tel."
    ),
    "Bent leg": "Bükülen bacak",
    "A part's own leg folded to a nearby hole: the cheapest connection.": (
        "Parçanın kendi bacağının yakındaki bir deliğe bükülmesi: en ucuz bağlantı."
    ),
    "Component side": "Parça yüzü",
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
    "Relay driver and its supply, two boards": "Röle sürücüsü ve beslemesi, iki kart",
    # The shipped examples' own names, said in the window's language when one is opened
    # (``main._example_names``).
    "Arduino I/O Shield": "Arduino Giriş/Çıkış Kartı",
    "ATmega328 Relay Board": "ATmega328 Röle Kartı",
    "LM317 Adjustable Supply": "LM317 Ayarlı Güç Kaynağı",
    "One-Transistor Guitar Booster": "Tek Transistörlü Gitar Booster'ı",
    "Arduino Nano Relay Driver": "Arduino Nano Röle Sürücüsü",
    "NE555 Astable": "NE555 Astabil",
    "NE555 Blinker": "NE555 Flaşör",
    "Relay Driver and Its Supply": "Röle Sürücüsü ve Beslemesi",
    "Relay driver": "Röle sürücüsü",
    "Supply": "Besleme",
    # An empty board of a system (``workflow.WorkflowFacts.empty_board``).
    "Show the Empty Board": "Boş Kartı Göster",
    "{board} is empty": "{board} boş",
    "{board} has nothing on it. Move parts to it: right-click a part on another board, Move "
    "to Board. Or remove it in its Properties.": (
        "{board} üzerinde hiçbir şey yok. Ona parça taşıyın: başka bir karttaki parçaya sağ "
        "tıklayın, Karta Taşı. Ya da Özellikler'den kaldırın."
    ),
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
    "{parts} part on a board of {size}": "{size} kart üzerinde {parts} parça",
    "{parts} parts on a board of {size}": "{size} kart üzerinde {parts} parça",
    "{parts} parts on {boards} boards, {size} each": "{boards} kart üzerinde {parts} parça, her biri {size}",
    "{parts} parts on {boards} boards": "{boards} kart üzerinde {parts} parça",
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
    "e.g. 470, 10k": "ör. 470, 10k",
    "e.g. 10k": "ör. 10k",
    "e.g. 100nF, 10µF": "ör. 100nF, 10µF",
    "e.g. 10µH, 100µH": "ör. 10µH, 100µH",
    "We picked the smallest stock board your parts fit on. Pick another if you have "
    "one.": "Parçalarınızın sığdığı en küçük hazır kartı seçtik. Elinizde başka bir kart varsa onu seçin.",
    "ready to build": "montaja hazır",
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
    # -- the step, in Properties with nothing selected (inspector._StepCard) ----------
    "Step {number} of 6": "Adım {number} / 6",
    "Board Settings…": "Kart Ayarları…",
    "The board's name, its size and type, and what a case asks of it.": (
        "Kartın adı, boyutu ve türü, ve bir kutunun ondan istedikleri."
    ),
    "The circuit has a mistake to put right first. Show Problems says what and where.": (
        "Devrede önce düzeltilmesi gereken bir hata var. Sorunları Göster neyin nerede "
        "olduğunu söyler."
    ),
    "Join the parts on the sheet: click a pin, then the pin it connects to. Every pin that "
    "should be joined needs a line.": (
        "Şemadaki parçaları birleştirin: bir pine, sonra bağlandığı pine tıklayın. "
        "Birleşmesi gereken her pinin bir çizgisi olmalı."
    ),
    "Start with the parts. Type a part's name in the Library and press Enter: it goes on "
    "the sheet, ready to be joined to the others.": (
        "Parçalarla başlayın. Kütüphanede bir parçanın adını yazıp Enter'a basın: parça, "
        "diğerlerine bağlanmaya hazır olarak şemaya gelir."
    ),
    "Pick the perfboard it goes on. Every stock size is tried with your circuit on it, and "
    "the smallest that fits is suggested.": (
        "Devrenin gideceği delikli kartı seçin. Satılan her boy devreniz üzerine "
        "yerleştirilerek denenir ve sığdığı en küçük kart önerilir."
    ),
    "Put the parts on the board. They are arranged for you; drag any of them afterwards.": (
        "Parçaları karta yerleştirin. Sizin için dizilirler; sonra istediğinizi "
        "sürükleyebilirsiniz."
    ),
    "Join the pins on the board. Auto-wire lays the wires on the solder side, under the "
    "board; Ctrl+F turns the board over to see them.": (
        "Karttaki pinleri birleştirin. Otomatik Kablola telleri lehim yüzüne, kartın altına "
        "döşer; onları görmek için Ctrl+F kartı çevirir."
    ),
    "Something on the board needs a look. Show Problems lists each one and where it is.": (
        "Kartta bakılması gereken bir şey var. Sorunları Göster her birini ve yerini listeler."
    ),
    "The board is ready to build. The build guide takes you through it one part at a "
    "time.": (
        "Kart yapılmaya hazır. Montaj rehberi size her seferinde bir parça olmak üzere yol "
        "gösterir."
    ),
    "The board can be built. {count} wire is worth a look first: a count below selects "
    "it.": (
        "Kart yapılabilir. Önce {count} tele bakmakta yarar var: aşağıdaki sayıya tıklamak "
        "onu seçer."
    ),
    "The board can be built. {count} wires are worth a look first: each count below selects "
    "its wires.": (
        "Kart yapılabilir. Önce {count} tele bakmakta yarar var: aşağıdaki her sayı kendi "
        "tellerini seçer."
    ),
    # -- what the engine says it did (ui/engine_text.py) ---------------------------
    "Place {parts} part and {links} connection": "{parts} parça ve {links} bağlantı yerleştir",
    "Place {parts} part and {links} connections": "{parts} parça ve {links} bağlantı yerleştir",
    "Place {parts} parts and {links} connection": "{parts} parça ve {links} bağlantı yerleştir",
    "Place {parts} parts and {links} connections": "{parts} parça ve {links} bağlantı yerleştir",
    "Place and arrange {count} part from the schematic": "Şemadaki {count} parçayı karta yerleştir ve diz",
    "Place and arrange {count} parts from the schematic": "Şemadaki {count} parçayı karta yerleştir ve diz",
    "Place {count} part on the board": "{count} parçayı karta yerleştir",
    "Place {count} parts on the board": "{count} parçayı karta yerleştir",
    "Place {ref} at {hole}": "{ref} parçasını {hole} deliğine yerleştir",
    "Move {count} component": "{count} parçayı taşı",
    "Move {count} components": "{count} parçayı taşı",
    "Rotate {count} component": "{count} parçayı döndür",
    "Rotate {count} components": "{count} parçayı döndür",
    "Mirror {count} component": "{count} parçayı aynala",
    "Mirror {count} components": "{count} parçayı aynala",
    "Update {count} component": "{count} parçayı güncelle",
    "Update {count} components": "{count} parçayı güncelle",
    "Lock {count} component": "{count} parçayı kilitle",
    "Lock {count} components": "{count} parçayı kilitle",
    "Unlock {count} component": "{count} parçanın kilidini aç",
    "Unlock {count} components": "{count} parçanın kilidini aç",
    "Delete {count} component and {conductors} conductor": "{count} parçayı ve {conductors} iletkeni sil",
    "Delete {count} component and {conductors} conductors": "{count} parçayı ve {conductors} iletkeni sil",
    "Delete {count} components and {conductors} conductor": "{count} parçayı ve {conductors} iletkeni sil",
    "Delete {count} components and {conductors} conductors": "{count} parçayı ve {conductors} iletkeni sil",
    "Delete {count} component": "{count} parçayı sil",
    "Delete {count} components": "{count} parçayı sil",
    "Move {count} symbol on the sheet": "Şemada {count} sembolü taşı",
    "Move {count} symbols on the sheet": "Şemada {count} sembolü taşı",
    "Move {ref} on the sheet": "{ref} sembolünü şemada taşı",
    "Add {ref} to the sheet at ({x}, {y})": "{ref} sembolünü şemaya ekle ({x}, {y})",
    "Move {ref} to {hole}": "{ref} parçasını {hole} deliğine taşı",
    "Move {ref} to Solder Side: its rows of pins swapped sides, so its wiring needs redoing":
        "{ref} parçasını lehim yüzüne taşı: bacak sıraları yer değiştirdi, kablolamasını yeniden yapmanız gerekir",
    "Move {ref} to Solder Side: its pins moved to other holes, so its wiring needs redoing":
        "{ref} parçasını lehim yüzüne taşı: bacakları başka deliklere geçti, kablolamasını yeniden yapmanız gerekir",
    "Move {ref} to Component Side: its rows of pins swapped sides, so its wiring needs redoing":
        "{ref} parçasını parça yüzüne taşı: bacak sıraları yer değiştirdi, kablolamasını yeniden yapmanız gerekir",
    "Move {ref} to Component Side: its pins moved to other holes, so its wiring needs redoing":
        "{ref} parçasını parça yüzüne taşı: bacakları başka deliklere geçti, kablolamasını yeniden yapmanız gerekir",
    "Move {ref} to Solder Side": "{ref} parçasını lehim yüzüne taşı",
    "Move {ref} to Component Side": "{ref} parçasını parça yüzüne taşı",
    "Move {count} component to another side": "{count} parçayı öbür yüze taşı",
    "Move {count} components to another side": "{count} parçayı öbür yüze taşı",
    "Rotate {ref} to {degrees} degrees": "{ref} parçasını {degrees} dereceye döndür",
    "Unmirror {ref}": "{ref} parçasının aynalamasını kaldır",
    "Mirror {ref}": "{ref} parçasını aynala",
    "Take {ref} off the board": "{ref} parçasını karttan kaldır",
    "Paste {parts} part and {links} connection": "{parts} parça ve {links} bağlantı yapıştır",
    "Paste {parts} part and {links} connections": "{parts} parça ve {links} bağlantı yapıştır",
    "Paste {parts} parts and {links} connection": "{parts} parça ve {links} bağlantı yapıştır",
    "Paste {parts} parts and {links} connections": "{parts} parça ve {links} bağlantı yapıştır",
    "Paste {parts} part": "{parts} parça yapıştır",
    "Paste {parts} parts": "{parts} parça yapıştır",
    "Paste {links} connection": "{links} bağlantı yapıştır",
    "Paste {links} connections": "{links} bağlantı yapıştır",
    "{what} at {hole}": "{hole} deliğine {what}",
    "Auto-place {count} component": "{count} parçayı otomatik yerleştir",
    "Auto-place {count} components": "{count} parçayı otomatik yerleştir",
    "Auto-place (no change)": "Otomatik yerleşim (değişiklik yok)",
    "Add {count} imported part": "İçe aktarılan {count} parçayı ekle",
    "Add {count} imported parts": "İçe aktarılan {count} parçayı ekle",
    "Place {count} imported part": "İçe aktarılan {count} parçayı yerleştir",
    "Place {count} imported parts": "İçe aktarılan {count} parçayı yerleştir",
    "Add {count} part to the schematic": "Şemaya {count} parça ekle",
    "Add {count} parts to the schematic": "Şemaya {count} parça ekle",
    "Add {ref} {value} to the schematic": "Şemaya {ref} {value} ekle",
    "Add {ref} to the schematic": "Şemaya {ref} ekle",
    "Delete {ref} and its {count} connection(s)": "{ref} parçasını ve {count} bağlantısını sil",
    "Turn {count} symbol(s) on the sheet": "Şemada {count} sembolü döndür",
    "Flip {count} symbol(s) on the sheet": "Şemada {count} sembolü çevir",
    "Lay {count} symbol out automatically": "{count} sembolü otomatik diz",
    "Lay {count} symbols out automatically": "{count} sembolü otomatik diz",
    "Lay the whole sheet out automatically": "Bütün şemayı otomatik diz",
    "Wire {a} onto the wire from {b} to {c}": "{a} pinini {b}–{c} teline bağla",
    "Wire {a} to {b}": "{a} pinini {b} pinine tel ile bağla",
    "Rub out {count} wire on the sheet and {branches} branch(es) off it": "Şemadaki {count} teli ve ondan çıkan {branches} dalı sil",
    "Rub out {count} wires on the sheet and {branches} branch(es) off it": "Şemadaki {count} teli ve ondan çıkan {branches} dalı sil",
    "Rub out {count} wire on the sheet": "Şemadaki {count} teli sil",
    "Rub out {count} wires on the sheet": "Şemadaki {count} teli sil",
    "Rub out the wire from {a} to {b} and {branches} branch(es) off it": "{a}–{b} telini ve ondan çıkan {branches} dalı sil",
    "Rub out the wire from {a} to {b}": "{a}–{b} telini sil",
    "Delete the wire from {a} to {b}": "{a}–{b} telini sil",
    "Delete {count} wire on the sheet": "Şemadaki {count} teli sil",
    "Delete {count} wires on the sheet": "Şemadaki {count} teli sil",
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
    "Reshape {kind} {start} to {end}": "{start} → {end} iletkenini ({kind}) yeniden biçimlendir",
    "Reroute conductor {id}": "{id} iletkenini yeniden döşe",
    "Delete {kind} {start} to {end}": "{start} → {end} iletkenini ({kind}) sil",
    "Delete {kind} {id}": "{id} iletkenini ({kind}) sil",
    "Delete {count} conductor(s)": "{count} iletkeni sil",
    "Remove the wiring of {name}": "{name} netinin kablolamasını kaldır",
    "Remove {count} stale conductor": "Eskimiş {count} iletkeni kaldır",
    "Remove {count} stale conductors": "Eskimiş {count} iletkeni kaldır",
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
    "{wirekind} {wire} runs under {ref}, which is on the solder side and covers {hole}. Lay it before fitting {ref_b}, or the part has to come off to reach it.": "{wirekind} {wire}, {ref} altından geçiyor; parça lehim yüzünde ve {hole} deliğini örtüyor. Onu {ref_b} takılmadan önce döşeyin, yoksa ona ulaşmak için parçayı sökmek gerekir.",
    "{wirekind} {wire} runs under {ref} on the component side and covers {hole}. Copper on the component side is laid after the parts, so it cannot be laid there once {ref_b} is fitted: route it clear of {ref_c}.": "{wirekind} {wire}, parça yüzünde {ref} altından geçiyor ve {hole} deliğini örtüyor. Parça yüzündeki bakır parçalardan sonra döşenir; {ref_b} takıldıktan sonra oraya döşenemez. Onu {ref_c} parçasından uzak geçirin.",
    "{wirekind} {wire} is on the component side, where this board has no pads to solder to. Lay it on the solder side.": "{wirekind} {wire} parça yüzünde, ama bu kartın o yüzde lehimlenecek pedi yok. Lehim yüzüne döşeyin.",
    "{wirekind} {wire} is soldered at {hole}, {ref}'s pin, on the component side, where {ref_b}'s body sits on the board over the pad: the joint cannot be made. Lay it on the solder side.": "{wirekind} {wire}, parça yüzünde {ref} parçasının pini olan {hole} deliğine lehimleniyor; orada {ref_b} gövdesi pedin üstünde karta oturur: lehim noktası yapılamaz. Onu lehim yüzüne döşeyin.",
    "{wirekind} {wire} is soldered at {hole}, {ref}'s pin, on the component side, under {ref_b}'s body. Fit {ref_c} with its leads left about {mm} mm long so the iron reaches the pad, or lay it on the solder side.": "{wirekind} {wire}, parça yüzünde {ref} parçasının pini olan {hole} deliğine, {ref_b} gövdesinin altında lehimleniyor. Havya pede ulaşsın diye {ref_c} parçasını bacaklarını yaklaşık {mm} mm uzun bırakarak takın ya da onu lehim yüzüne döşeyin.",
    "{wirekind} {wire} is soldered at {hole}, {ref}'s pin, on the solder side, where {ref_b}'s body sits on the board over the pad: the joint cannot be made. Lay it on the component side.": "{wirekind} {wire}, lehim yüzünde {ref} parçasının pini olan {hole} deliğine lehimleniyor; orada {ref_b} gövdesi pedin üstünde karta oturur: lehim noktası yapılamaz. Onu parça yüzüne döşeyin.",
    "{wirekind} {wire} is soldered at {hole}, {ref}'s pin, on the solder side, under {ref_b}'s body. Fit {ref_c} with its leads left about {mm} mm long so the iron reaches the pad, or lay it on the component side.": "{wirekind} {wire}, lehim yüzünde {ref} parçasının pini olan {hole} deliğine, {ref_b} gövdesinin altında lehimleniyor. Havya pede ulaşsın diye {ref_c} parçasını bacaklarını yaklaşık {mm} mm uzun bırakarak takın ya da onu parça yüzüne döşeyin.",
    "The solder on the fingers {hole} to {hole_b} is joined to no hole of the board, so it carries nothing. Bridge a finger to the hole beside it.": "{hole} ile {hole_b} arasındaki parmaklardaki lehim kartın hiçbir deliğine bağlı değil, bu yüzden hiçbir şey taşımaz. Bir parmağı yanındaki deliğe köprüleyin.",
    "Solder trace {wire} crosses {mm} mm of bare board between {hole} and {hole_b}, wider than solder spans ({limit} mm). Lay it over a wire spine ('solder-trace-wired').": "{wire} lehim yolu {hole} ile {hole_b} arasında {mm} mm çıplak karttan geçiyor; bu, lehimin köprüleyebildiğinden ({limit} mm) geniş. Onu telli lehim yolu olarak döşeyin ('solder-trace-wired').",
    "{ref}'s joint at {hole} is under {ref_b}, on the solder side. Solder {ref_c} before fitting {ref_d}, or the joint cannot be reached or reworked.": "{ref} parçasının {hole} deliğindeki lehim noktası, lehim yüzündeki {ref_b} altında kalıyor. {ref_c} parçasını {ref_d} takılmadan önce lehimleyin, yoksa o noktaya ulaşılamaz ve düzeltilemez.",
    "{ref}'s joint at {hole} is under {ref_b}, on the component side. Solder {ref_c} before fitting {ref_d}, or the joint cannot be reached or reworked.": "{ref} parçasının {hole} deliğindeki lehim noktası, parça yüzündeki {ref_b} altında kalıyor. {ref_c} parçasını {ref_d} takılmadan önce lehimleyin, yoksa o noktaya ulaşılamaz ve düzeltilemez.",
    "{ref} is on the solder side of a single-sided board, so its leads are soldered on the solder side, and its body sits on the board over its joints ({holes}): the iron cannot reach them. Put it on the component side, or use a double-sided board.": "{ref} tek yüzlü bir kartın lehim yüzünde; bu yüzden bacakları lehim yüzünde lehimlenir ve gövdesi kartın üstüne, lehim noktalarının üzerine oturur ({holes}): havya onlara ulaşamaz. Onu parça yüzüne koyun ya da çift yüzlü bir kart kullanın.",
    "{ref} is on the solder side of a single-sided board, so its leads are soldered on the solder side, under its own body ({holes}). Leave the leads about {mm} mm long so the iron reaches the pads, or use a double-sided board.": "{ref} tek yüzlü bir kartın lehim yüzünde; bu yüzden bacakları lehim yüzünde, kendi gövdesinin altında lehimlenir ({holes}). Havyanın pedlere ulaşması için bacakları yaklaşık {mm} mm uzun bırakın ya da çift yüzlü bir kart kullanın.",
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
    "{ref} is on the solder side, which is what mirrors it; move it to the component side instead.": "{ref} lehim yüzünde ve onu aynalayan da bu; bunun yerine onu parça yüzüne taşıyın.",
    "{ref} cannot go on the solder side of a breadboard: a breadboard has no underside to put a part on.": "{ref} bir breadboard'ın lehim yüzüne konamaz: breadboard'ın altında parça takılacak bir yüz yok.",
    "{ref} cannot be on the solder side unmirrored: a part put in from underneath is turned over, which reflects its pins.": "{ref} lehim yüzünde aynalanmadan duramaz: alttan takılan parça ters çevrilir ve bu, bacaklarını aynalar.",
    "{ref} is already on the solder side.": "{ref} zaten lehim yüzünde.",
    "{ref} is already on the component side.": "{ref} zaten parça yüzünde.",
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
    "{count} on the solder side, under the board: Ctrl+F turns it over": (
        "{count} tanesi lehim yüzünde, kartın altında: Ctrl+F kartı çevirir"
    ),
    "{count} on the component side: Ctrl+F turns the board over": (
        "{count} tanesi parça yüzünde: Ctrl+F kartı çevirir"
    ),
    '{count} could not be wired': '{count} tanesi kablolanamadı',
    "{closed} of {considered} nets wired": "{considered} netin {closed} tanesi kablolandı",
    "{count} connection could not be wired": "{count} bağlantı kablolanamadı",
    "{count} connections could not be wired": "{count} bağlantı kablolanamadı",
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
    "component": "parça",
    "solder": "lehim",
    "the body of {refs}": "{refs} gövdesinin",
    "the bodies of {refs}": "{refs} gövdelerinin",
    "{net} prefers the {faceside} side, but this board has no pads there, so it is wired on the {faceside_b} side.": "{net} {faceside} yüzünü tercih ediyor, ama bu kartın orada pedi yok; bu yüzden {faceside_b} yüzünde kablolandı.",
    "{net} prefers the {faceside} side, but its pins there are under {refs}, so it is wired on the {faceside_b} side.": "{net} {faceside} yüzünü tercih ediyor, ama oradaki pinleri {refs} altında; bu yüzden {faceside_b} yüzünde kablolandı.",
    "{net} prefers the {faceside} side, but no clear way was found there, so it is wired on the {faceside_b} side.": "{net} {faceside} yüzünü tercih ediyor, ama orada açık bir yol bulunamadı; bu yüzden {faceside_b} yüzünde kablolandı.",
    "{net} prefers the {faceside} side, but {count} of its {total} connections are wired on the {faceside_b} side: this board has no pads there.": "{net} {faceside} yüzünü tercih ediyor, ama {total} bağlantısından {count} tanesi {faceside_b} yüzünde kablolandı: bu kartın orada pedi yok.",
    "{net} prefers the {faceside} side, but {count} of its {total} connections are wired on the {faceside_b} side: its pins there are under {refs}.": "{net} {faceside} yüzünü tercih ediyor, ama {total} bağlantısından {count} tanesi {faceside_b} yüzünde kablolandı: oradaki pinleri {refs} altında.",
    "{net} prefers the {faceside} side, but {count} of its {total} connections are wired on the {faceside_b} side: no clear way was found for them there.": "{net} {faceside} yüzünü tercih ediyor, ama {total} bağlantısından {count} tanesi {faceside_b} yüzünde kablolandı: onlar için orada açık bir yol bulunamadı.",
    "{net} prefers the {faceside} side, but {count} of its {total} connections are wired on the {faceside_b} side: {covered} because its pins there are under {refs}, {open} because no clear way was found for them there.": "{net} {faceside} yüzünü tercih ediyor, ama {total} bağlantısından {count} tanesi {faceside_b} yüzünde kablolandı: {covered} tanesi oradaki pinleri {refs} altında olduğu için, {open} tanesi orada açık bir yol bulunamadığı için.",
    "{net} prefers the {faceside} side, but it is wired on the {faceside_b} side: {covered} of its connections because its pins there are under {refs}, {open} because no clear way was found for them there.": "{net} {faceside} yüzünü tercih ediyor, ama {faceside_b} yüzünde kablolandı: bağlantılarından {covered} tanesi oradaki pinleri {refs} altında olduğu için, {open} tanesi orada açık bir yol bulunamadığı için.",
    "{net} is wired on the {faceside} side; its pins under {refs} are reached through a via beside them.": "{net} {faceside} yüzünde kablolandı; {refs} altındaki pinlerine yanlarındaki bir via ile ulaşıldı.",
    "{net} is wired on the {faceside} side on {count} of its {total} connections; its pins under {refs} are reached through a via beside them.": "{net} {total} bağlantısından {count} tanesinde {faceside} yüzünde kablolandı; {refs} altındaki pinlerine yanlarındaki bir via ile ulaşıldı.",
    "Its pins under {refs} are reached through a via beside them.": "{refs} altındaki pinlerine yanlarındaki bir via ile ulaşıldı.",
    "bottom": "alt",
    "paste": "yapıştırın",
    "duplicate": "çoğaltın",
    # A finding on one board of a system, the board said before it.
    "On {board}: {finding}": "{board} üzerinde: {finding}",
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


def hole_grid(cols: int, rows: int) -> str:
    """A board's size in holes, said the one way everywhere: "60 × 40 holes".

    A bare "60 × 40" beside a stock board's "5 x 7 cm" read as millimetres -- in the step
    bar, the status bar, the board question and the board strip alike.
    """
    return t("{cols} × {rows} holes").format(cols=cols, rows=rows)


def counted(count: int, one: str, many: str, **fields: object) -> str:
    """``one`` or ``many`` -- each already through ``t()``, so the catalogue scan sees both --
    with the count in it, and any other ``fields`` the sentence has. "3 part(s)" read like a
    machine. English needs the two forms; Turkish says the singular after a number, so its
    two entries are the same words."""
    return (one if count == 1 else many).format(count=count, **fields)


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
