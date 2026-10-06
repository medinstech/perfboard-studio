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
    "&Draw": "&Çiz",
    "&Place": "&Yerleştir",
    "&Route": "Yön&lendir",
    "&View": "&Görünüm",
    "&Help": "Y&ardım",
    # -- file ----------------------------------------------------------------
    "&New Board…": "&Yeni Kart…",
    "&Open…": "&Aç…",
    "&Save": "&Kaydet",
    "Save &As…": "&Farklı Kaydet…",
    "Re&load from Disk": "Diskten Ye&niden Yükle",
    "Reload from disk?": "Diskten yeniden yüklensin mi?",
    # Ayar&ları, not &Ayarları: "&Aç…" already claims A in this menu, and two items with
    # the same accelerator means one of them cannot be reached from the keyboard at all.
    "&Board Setup…": "Kart Ayar&ları…",
    "Board &Features…": "Kart &Öğeleri…",
    "Open &Recent": "&Son Kullanılanlar",
    "(nothing yet)": "(henüz yok)",
    "&Clear List": "Listeyi &Temizle",
    "&Import KiCad Netlist…": "KiCad Netlist &İçe Aktar…",
    "Export &Build Guide…": "&Montaj Rehberini Dışa Aktar…",
    # Ş rather than S: "&Son Kullanılanlar" has S in this menu, and Turkish treats the two
    # as different letters -- which is exactly what makes it a free accelerator here.
    "Export Sc&hematic…": "&Şemayı Dışa Aktar…",
    "Write the circuit as a sheet: SVG to embed or edit, PDF to print, PNG to "
    "paste into a message asking somebody what is wrong with it.": (
        "Devreyi bir sayfa olarak yaz: gömmek ya da düzenlemek için SVG, basmak için PDF, "
        "birine neyin yanlış olduğunu sormak üzere mesaja yapıştırmak için PNG."
    ),
    "Export 1:1 PDF (component + solder side)…": "1:1 PDF Dışa Aktar (komponent + lehim yüzü)…",
    "Export 3D Snapshot PNG…": "3D Görüntü PNG Dışa Aktar…",
    "Export 3D Model (STEP)…": "3D Modeli Dışa Aktar (STEP)…",
    "Write the board as solids for a mechanical CAD program: the board with its holes "
    "and every part as the room it takes, named by its reference -- to draw the "
    "enclosure round.": (
        "Kartı mekanik bir CAD programı için katı olarak yaz: delikleriyle kart ve her "
        "parça kapladığı hacim olarak, referansıyla adlandırılmış -- kutusunu çevresine "
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
    "Solder Trace with S&pine": "&Omurgalı Lehim Yolu",
    "&Bare Wire": "&Çıplak Tel",
    "&Insulated Wire": "İ&zoleli Tel",
    "Top &Jumper": "Üst Yüz &Jumper",
    "Join adjacent pads with solder. Orthogonal steps only — solder spans the "
    "0.6 mm gap to the next pad and not the 1.7 mm diagonal one. Click each "
    "pad, then Enter or right-click to finish.": (
        "Komşu pedleri lehimle birleştirir. Yalnızca düz adımlar — lehim yandaki pede "
        "olan 0,6 mm boşluğu kapatır, çaprazdaki 1,7 mm boşluğu kapatmaz. Her pede tıkla, "
        "bitirmek için Enter veya sağ tık."
    ),
    "The same over a tinned-wire spine: about ten times lower resistance, and "
    "what a power or ground rail longer than five or six pads wants.": (
        "Aynısı, kalaylı bir tel omurganın üzerinde: yaklaşık on kat düşük direnç; beş altı "
        "pedden uzun bir güç ya da toprak rayının istediği de budur."
    ),
    "Tinned wire on the solder side. Cannot cross other copper. Click both "
    "ends.": (
        "Lehim yüzünde kalaylı tel. Başka bakırın üzerinden geçemez. İki ucuna da tıkla."
    ),
    "May cross anything, at the cost of stripping it. Click both ends.": (
        "Her şeyin üzerinden geçebilir; bedeli uçlarını soymaktır. İki ucuna da tıkla."
    ),
    "Insulated, routed over the component side. Occupies body space.": (
        "İzoleli, komponent yüzünün üzerinden gider. Gövdelerin yerini kaplar."
    ),
    "&Cut Track": "Şeridi &Kes",
    "&Stop the Current Tool": "Aracı &Bırak",
    # -- nets ----------------------------------------------------------------
    # "&Net" becomes the plural "Netler": a menu named with the same word in both
    # languages would be an untranslated entry, which the catalogue tests refuse.
    "&Net": "&Netler",
    "&Connect Two Pins": "&İki Pini Bağla",
    "&New Net…": "&Yeni Net…",
    "&Add Pins to Net": "Nete &Pin Ekle",
    "&Finish Adding Pins": "Pin Eklemeyi &Bitir",
    "&Edit Net…": "Neti &Düzenle…",
    "&Disconnect Selected Pins": "Seçili Pinleri &Ayır",
    "De&lete Net": "Neti Si&l",
    "New Net": "Yeni Net",
    "Edit Net": "Neti Düzenle",
    "Delete net": "Neti sil",
    "Name": "Ad",
    "Class": "Sınıf",
    "Signal": "Sinyal",
    "Ground — routed first, and wants a rail": "Toprak — önce yönlendirilir, ray ister",
    "Power — routed after ground, same reason": "Güç — topraktan sonra yönlendirilir, aynı sebeple",
    "Current": "Akım",
    "Voltage": "Gerilim",
    "not stated": "belirtilmedi",
    "state a voltage": "gerilim belirt",
    # -- place and route -----------------------------------------------------
    "&Auto-place Board": "&Otomatik Yerleştir",
    "&Try Another Arrangement": "&Başka Bir Yerleşim Dene",
    "&Autoroute All Nets": "Tüm Netleri &Otomatik Yönlendir",
    "Route Nets of &Selection": "&Seçimin Netlerini Yönlendir",
    "Re-route &Everything": "Her Şeyi &Yeniden Yönlendir",
    "Re-route Nets of Se&lection": "Seçimin Netlerini Yeniden Yönl&endir",
    "Remove S&tale Conductors": "&Artık İletkenleri Kaldır",
    "&Preferred Connection": "&Tercih Edilen Bağlantı",
    "&Try each and keep the best": "&Hepsini dene, en iyisini tut",
    "&Solder trace where possible": "Mümkün olan her yerde &lehim yolu",
    "&Balanced": "&Dengeli",
    "&Wire where possible": "Mümkün olan her yerde &kablo",
    "Bend component &legs where possible": "Mümkün olan her yerde &bacak bük",
    "Route the board once with every style, measure what each would cost to "
    "build -- traces, wires, wire length, bridging risk -- and keep the best. "
    "Takes about as long as two ordinary routes; the comparison is reported.": (
        "Kartı her stille bir kez yönlendir, her birinin yapım maliyetini ölç — lehim "
        "yolları, teller, tel uzunluğu, köprüleme riski — ve en iyisini tut. İki sıradan "
        "yönlendirme kadar sürer; karşılaştırma raporlanır."
    ),
    "Every connection a solder trace can make, IS one -- wire only where a "
    "trace physically cannot get there. A short jumper carries a run over "
    "anything it must cross. On the NE555 fixture: all 14 connections, not one "
    "wire.": (
        "Bir lehim yolunun yapabildiği her bağlantı lehim yolu olur — tel yalnızca lehim "
        "yolunun fiziksel olarak ulaşamadığı yerde. Kesmesi gereken her şeyin üzerinden "
        "kısa bir atlama teli geçirir. NE555 örneğinde: 14 bağlantının hepsi, tek tel yok."
    ),
    "No commitment: weigh each primitive on its own cost and take the cheapest "
    "each time. The default, and what every golden fixture is routed with. On "
    "a populated board this comes out as wire far more often than people "
    "expect.": (
        "Bağlılık yok: her bağlantı türünü kendi maliyetiyle tart ve her seferinde en "
        "ucuzunu al. Varsayılan budur, altın örneklerin hepsi bununla yönlendirilir. Dolu bir "
        "kartta beklenenden çok daha sık tel çıkar."
    ),
    "For anyone assembling with wire: every connection a wire can make is a "
    "wire, including the rails. Solder only where a wire cannot reach.": (
        "Telle kuranlar için: bir telin yapabildiği her bağlantı tel olur, raylar dahil. "
        "Lehim yalnızca telin ulaşamadığı yerde."
    ),
    "Fold a component's own leg to a nearby hole first, then solder, then wire. "
    "The cheapest connection there is -- no wire to cut, and already soldered "
    "at one end.": (
        "Önce parçanın kendi bacağını yakındaki bir deliğe bük, sonra lehim, sonra tel. "
        "Olabilecek en ucuz bağlantı — kesilecek tel yok, bir ucu zaten lehimli."
    ),
    "Preferred connection": "Tercih edilen bağlantı",
    "applies to the next route": "bir sonraki yönlendirmede geçerli olur",
    "Lay Wires Along the &Grid": "Telleri &Izgara Boyunca Döşe",
    "&Crossings": "&Kesişmeler",
    "Crossings": "Kesişmeler",
    "&Hop over it with a short jumper": "Kısa bir &atlama teliyle üstünden geç",
    "Make the whole connection one &wire": "Bağlantının tamamını tek bir &tel yap",
    "&Never use wire; leave it unrouted": "&Hiç tel kullanma; yönlendirilmeden bırak",
    "Solder trace as far as it goes, and one short insulated jumper over each "
    "thing it may not cross -- what somebody building by hand does. Most of the "
    "run is solder and only the crossing costs a piece of wire. The default.": (
        "Lehim yolu gidebildiği yere kadar gider, geçemeyeceği her şeyin üstünden de "
        "kısa bir yalıtımlı atlama teli geçer -- elle kart yapan birinin yaptığı gibi. "
        "Yolun çoğu lehimdir, yalnızca kesişme bir parça tele mal olur. Varsayılan."
    ),
    "A connection that has to cross something becomes one insulated wire from "
    "end to end, for anybody who would rather run one clean wire than solder up "
    "to a jumper.": (
        "Bir şeyin üstünden geçmesi gereken bağlantı baştan sona tek bir yalıtımlı tel "
        "olur; bir atlama teline kadar lehim çekmektense tek temiz bir tel döşemeyi "
        "tercih eden için."
    ),
    "No wire of any kind, whichever connection is preferred: solder traces "
    "only. A connection a trace cannot make is left unrouted and named, rather "
    "than made with wire you did not ask for. On a crowded board that can be "
    "several, and moving parts is usually the answer.": (
        "Tercih edilen bağlantı ne olursa olsun hiçbir türde tel yok: yalnızca lehim "
        "yolu. Bir yolun yapamadığı bağlantı, istemediğiniz bir telle yapılmak yerine "
        "yönlendirilmeden bırakılır ve adıyla bildirilir. Kalabalık bir kartta bunlar "
        "birkaç tane olabilir; çözüm çoğu zaman parçaları taşımaktır."
    ),
    "Run every wire square to the grid, along the rows and columns of holes, "
    "with as few bends as the board allows -- the way wire is dressed on "
    "perfboard. Off, a wire is one straight run at whatever angle, which is "
    "shorter and crosses everything near it.": (
        "Her teli ızgaraya dik olarak, delik satırları ve sütunları boyunca, kartın izin "
        "verdiği en az bükümle döşer -- perfboard'da tel böyle döşenir. Kapalıyken tel, "
        "açısı ne olursa olsun tek bir düz parçadır; daha kısadır ve yakınındaki her şeyi "
        "keser."
    ),
    "on": "açık",
    "off": "kapalı",
    # -- view ----------------------------------------------------------------
    "Flip Board (component / solder side)": "Kartı Çevir (komponent / lehim yüzü)",
    "&Fit Board": "Karta &Sığdır",
    "Zoom &In": "&Yakınlaştır",
    "Zoom &Out": "&Uzaklaştır",
    "Show &Ratsnest": "&Bağlantı Ağını Göster",
    "Show Hole &Addresses": "Delik &Adreslerini Göster",
    "&Hatch Copper on the Far Side": "Karşı Yüzdeki Bakırı &Taralı Göster",
    "Measure &Distance": "&Mesafe Ölç",
    "&Go to Part…": "Parçaya &Git…",
    "Go to Part": "Parçaya Git",
    "Filter parts…  (R37, 10k, TO-220, C7)": "Parçaları süz…  (R37, 10k, TO-220, C7)",
    "Show &3D View": "&3D Görünümü Göster",
    # Ca&mera, not &Camera: "Board &Colour" has C in the same menu.
    "Reset 3D Ca&mera": "3D &Kamerayı Sıfırla",
    # &Listesini / &Netleri / L&VS: L, N and V are the free letters in the Turkish View
    # menu, where S, Y, U, B, D, T, M, G, K, R, P and Ş are all already spoken for.
    "Show &Parts": "Parça &Listesini Göster",
    "Show &Nets": "&Netleri Göster",
    "Show DRC / L&VS": "DRC / L&VS'yi Göster",
    "Board &Colour": "Kart &Rengi",
    "Follow the &material": "&Malzemeye göre",
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
    "Undo": "Geri al:",
    "Nothing to undo": "Geri alınacak bir şey yok",
    "Redo": "Yinele:",
    "Nothing to redo": "Yinelenecek bir şey yok",
    "Placing": "Yerleştiriliyor:",
    "click a hole, Esc cancels": "bir deliğe tıkla, Esc iptal eder",
    "Drawing": "Çiziliyor:",
    "click both ends, Esc cancels": "iki ucu da tıkla, Esc iptal eder",
    "click each pad, Enter or right-click finishes, Esc cancels":
        "her pede tıkla, Enter veya sağ tık bitirir, Esc iptal eder",
    "Cutting tracks": "Şerit kesiliyor",
    "click a hole, Esc ends": "bir deliğe tıkla, Esc bitirir",
    "Measuring": "Ölçülüyor",
    "click two holes": "iki deliğe tıkla",
    "from": "başlangıç",
    "Esc ends": "Esc bitirir",
    "Adding pins to": "Pin ekleniyor:",
    "Enter or right-click finishes, Esc cancels": "Enter veya sağ tık bitirir, Esc iptal eder",
    "no pins yet": "henüz pin yok",
    "Nothing on this board yet.": "Bu kartta henüz bir şey yok.",
    "Filter nets…  (gnd, power, U1)": "Netleri süz…  (gnd, power, U1)",
    "Filter parts…  (resistor, dip, 5mm)": "Parçaları süz…  (direnç, dip, 5mm)",
    # -- toolbar ---------------------------------------------------------------
    # Short labels for the buttons; the menus keep the full wording. Qt draws an action's
    # iconText on a toolbar and its text in a menu, so these are the only place they differ.
    "Connect": "Bağla",
    "Trace": "Lehim Yolu",
    "Spine": "Omurga",
    "Bare": "Çıplak",
    "Insulated": "İzoleli",
    "Jumper": "Üst Jumper",
    "Auto-place": "Oto-yerleşim",
    "Autoroute": "Oto Yönlendir",
    "Rotate": "Döndür",
    "Mirror": "Aynala",
    "Delete": "Sil",
    # "Flip Side" was here until the toolbar stopped making its own action for it and
    # started sharing the View menu's, whose button label is "Flip".
    "Flip": "Çevir",
    "Ratsnest": "Bağlantı Ağı",
    "3D": "3B",
    "Fit": "Sığdır",
    # -- the connect tool ------------------------------------------------------
    "Connecting": "Bağlanıyor",
    "click the first pin, Esc cancels": "ilk pine tıkla, Esc iptal eder",
    "Connecting from": "Bağlantı başlangıcı:",
    "click the pin it joins, Esc cancels": "birleşeceği pine tıkla, Esc iptal eder",
    # -- docks ---------------------------------------------------------------
    "Parts": "Parçalar",
    "Nets": "Netler",
    "3D View": "3D Görünüm",
    "DRC / LVS": "DRC / LVS",
    # -- dialogs -------------------------------------------------------------
    "New Board": "Yeni Kart",
    "Board Setup": "Kart Ayarları",
    "Columns": "Sütun",
    "Rows": "Satır",
    "Material": "Malzeme",
    # -- board setup: which kind of board this is -----------------------------
    "Type": "Tip",
    "Strips run": "Şeritler",
    "Pad per hole — every hole is its own island": (
        "Delik başına ada — her delik kendi adası"
    ),
    "Stripboard — whole rows joined; you cut the track to separate": (
        "Şeritli plaket — satırlar baştan bağlı; ayırmak için şerit kesilir"
    ),
    # -- board setup: the sizes you can buy -----------------------------------
    "Board": "Kart",
    "Custom size": "Özel ölçü",
    "Double-sided green, plated holes": "Çift yüz yeşil, metalize delikli",
    "Single-sided orange phenolic": "Tek yüz turuncu pertinaks",
    # -- board setup: pad shape and the printed legend ------------------------
    "Pad shape": "Pad şekli",
    "Pad length": "Pad uzunluğu",
    "Long axis": "Uzun eksen",
    "Round": "Yuvarlak",
    "Oblong — solder bridges easily along the long axis": (
        "Oval — lehim uzun eksen boyunca kolayca köprü yapar"
    ),
    "Down a column": "Sütun boyunca",
    "Along a row": "Satır boyunca",
    "Addresses printed on the board": "Adresler kartın üzerine basılı",
    "Boards carrying their own A-Z / 01-22 legend, printed on the board itself.": (
        "Kendi A-Z / 01-22 cetvelini taşıyan, cetveli kartın üzerine basılı kartlar."
    ),
    "Row digits": "Satır basamağı",
    '2 prints row 7 as "07", the way most such boards do.': (
        '2, 7. satırı "07" olarak basar; bu kartların çoğu böyle yapar.'
    ),
    # -- board features: mounting holes and edge connectors -------------------
    "Board Features": "Kart Öğeleri",
    "Feature": "Öğe",
    "Where": "Yer",
    "Size": "Ölçü",
    "Remove": "Kaldır",
    "Mounting hole": "Montaj deliği",
    "Edge connector": "Kenar konnektörü",
    "Hole diameter": "Delik çapı",
    "Inset (holes)": "İçeri kaçıklık (delik)",
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
    "Finished board": "Bitmiş kart",
    "Bare board": "Boş kart",
    "Lift every part off the board, with a line down to the holes it goes in.": (
        "Her parçayı karttan kaldırır; girdiği deliklere inen bir çizgi ile birlikte."
    ),
    "Height limit": "Yükseklik sınırı",
    "No limit": "Sınırsız",
    "Set Height Limit": "Yükseklik Sınırını Uygula",
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
        "{ref} yalnızca bir nette adı geçiyor; kaldırmak için neti düzenle."
    ),
    "{count} would not fit": "{count} tanesi sığmadı",
    "Ctrl+R routes it; Ctrl+Shift+A arranges it again from a different seed.": (
        "Ctrl+R yönlendirir; Ctrl+Shift+A farklı bir tohumla yeniden yerleştirir."
    ),
    "Pressing Auto-place again searches from another seed.": (
        "Otomatik Yerleştir'e yeniden basmak başka bir tohumla arar."
    ),
    "Everything is routed already, so Autoroute plans it again.": (
        "Her şey zaten yönlendirilmiş; Otomatik Yönlendir hepsini yeniden planlıyor."
    ),
    "Routed again, and it came out exactly as it is ({elapsed:.0f} ms). "
    "A different Route ▸ Preferred Connection or Route ▸ Crossings gives a "
    "different routing.": (
        "Yeniden yönlendirildi ve tıpatıp aynısı çıktı ({elapsed:.0f} ms). Farklı bir "
        "yönlendirme için Yönlendir ▸ Tercih Edilen Bağlantı ya da Yönlendir ▸ Kesişmeler "
        "ayarını değiştirin."
    ),
    "Nothing to re-route": "Yeniden yönlendirilecek bir şey yok",
    "Ctrl+Z puts them back.": "Ctrl+Z geri getirir.",
    "Nothing to route:": "Yönlendirilecek bir şey yok:",
    "Move or delete whatever is in the way and try again.": (
        "Yolda ne varsa taşı ya da sil, sonra yeniden dene."
    ),
    "From {pin} — click the pin it joins.": "{pin} pininden — birleşeceği pine tıkla.",
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
    "{moved} of {movable} movable part(s) move": (
        "Taşınabilir {movable} parçadan {moved} tanesi yer değiştiriyor"
    ),
    "{locked} locked part(s) stay put.": "kilitli {locked} parça yerinde kalıyor.",
    "Estimated connection length: {before} mm → {after} mm.": (
        "Tahmini bağlantı uzunluğu: {before} mm → {after} mm."
    ),
    "Each arrangement found was routed, and this is the one cheapest to "
    "build (cost {cost}; seed {seed}).": (
        "Bulunan her yerleşim yönlendirildi; bu, kurulması en ucuz olanı "
        "(maliyet {cost}; tohum {seed})."
    ),
    "Overlapping bodies: {before} → {after}.": "Çakışan gövdeler: {before} → {after}.",
    "Pins sharing a hole: {before} → {after}.": "Aynı deliği paylaşan pinler: {before} → {after}.",
    "{count} problem(s):": "{count} sorun:",
    "{count} connection(s) were left unrouted:": "{count} bağlantı yönlendirilemedi:",
    "{ref} is in the design, not on the board yet.": "{ref} tasarımda var, ama henüz kartta değil.",
    "{ref} is named by a net and is not in the design at all.": (
        "{ref} yalnızca bir nette adı geçiyor; tasarımda hiç yok."
    ),
    "Could not read the file.": "Dosya okunamadı.",
    # -- what the findings panel calls each rule ---------------------------------
    "Parts overlap": "Parçalar çakışıyor",
    "Part off the board": "Parça kartın dışında",
    "Part hangs past the edge": "Parça kenardan taşıyor",
    "Part too tall for the case": "Parça kutuya göre fazla yüksek",
    "Conductors cross": "İletkenler kesişiyor",
    "Conductor off the board": "İletken kartın dışında",
    "Too close for the voltage": "Gerilime göre fazla yakın",
    "Conductors share a hole": "İletkenler aynı deliği paylaşıyor",
    "Too thin for the current": "Akıma göre fazla ince",
    "Pin on a cut track": "Kesik yol üzerinde pin",
    "Two pins in one hole": "Bir delikte iki pin",
    "Pin on an edge finger": "Kenar parmağında pin",
    "Heat source too close": "Isı kaynağı fazla yakın",
    "Jumper under a part": "Parçanın altında jumper",
    "Bent lead too long": "Bükülen bacak fazla uzun",
    "Too close to a mounting hole": "Montaj deliğine fazla yakın",
    "Pin on a mounting hole": "Montaj deliğinde pin",
    "Pads may lift": "Pedler kalkabilir",
    "Pin connected to nothing": "Hiçbir yere bağlı olmayan pin",
    "Solder trace skips a hole": "Lehim yolu bir deliği atlıyor",
    "Solder next to another net": "Başka bir netin yanında lehim",
    "Solder trace too long": "Lehim yolu fazla uzun",
    "Terminal entry blocked": "Klemens girişi kapalı",
    "Terminal faces into the board": "Klemens kartın içine bakıyor",
    "Unknown footprint": "Bilinmeyen footprint",
    "Bare wire on a joint": "Lehim noktası üzerinde çıplak tel",
    "Wire too thick for the hole": "Tel delik için fazla kalın",
    "Open: a net in pieces": "Açık devre: net parçalı",
    "Short: two nets joined": "Kısa devre: iki net birleşik",
    "Copper joined to no pin": "Hiçbir pine bağlı olmayan bakır",
    "Part not on the board": "Parça kartta değil",
    "Net not wired yet": "Net henüz kablolanmadı",
    "error": "hata",
    "warning": "uyarı",
    "Design rules checked in {ms} ms. Click to see the findings.": (
        "Tasarım kuralları {ms} ms'de denetlendi. Bulguları görmek için tıkla."
    ),
    "Export 1:1 PDF — the solder side is written beside it": (
        "1:1 PDF Dışa Aktar — lehim tarafı yanına yazılır"
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
        "{name} örneği açıldı. Kaydet, kendi kopyanı saklar."
    ),
    "Drawing step {done} of {total}…": "{total} adımın {done}. adımı çiziliyor…",
    "Skip the Pictures": "Görselleri Atla",
    "without its pictures": "görselleri olmadan",
    "Cancel": "İptal",
    "Delete parts": "Parçaları sil",
    "Delete conductors": "İletkenleri sil",
    "Apply this placement?": "Bu yerleşim uygulansın mı?",
    "Re-route?": "Yeniden yönlendirilsin mi?",
    "Re-route": "Yeniden Yönlendir",
    "{removed} existing conductor(s) will be removed and {planned} planned "
    "in their place. Copper with no net assigned is left alone.": (
        "Mevcut {removed} iletken kaldırılacak ve yerlerine {planned} iletken "
        "planlanacak. Neti atanmamış bakıra dokunulmaz."
    ),
    "One Ctrl+Z puts it all back.": "Tek bir Ctrl+Z hepsini geri getirir.",
    "Placement refused": "Yerleşim reddedildi",
    "Routing refused": "Yönlendirme reddedildi",
    "Re-route refused": "Yeniden yönlendirme reddedildi",
    "Board not changed": "Kart değiştirilmedi",
    "The guide has gaps": "Rehberde eksikler var",
    "About Perfboard Studio": "Perfboard Studio Hakkında",
    # -- status bar ----------------------------------------------------------
    "hole": "delik",
    "component side": "komponent yüzü",
    "solder side": "lehim yüzü",
    "mirrored": "aynalanmış",
    # -- a part's own properties ----------------------------------------------
    "Proper&ties…": "Ö&zellikler…",
    "Part Properties": "Parça Özellikleri",
    "Reference": "Referans",
    "Value": "Değer",
    "Footprint": "Ayak izi",
    "Pin 1 at": "1. pin",
    "Height": "Yükseklik",
    "locked — auto-placement leaves it where it is": (
        "kilitli — otomatik yerleşim onu yerinde bırakır"
    ),
    "A part needs a reference": "Parçanın bir referansı olmalı",
    "Every part is identified by its reference, so it cannot be blank.": (
        "Her parça referansıyla tanınır, dolayısıyla boş bırakılamaz."
    ),
    "Cannot change this part": "Bu parça değiştirilemedi",
    "Properties edits one part at a time — select a single part.": (
        "Özellikler tek seferde tek parçayı düzenler — tek bir parça seç."
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
    "Value for parts placed now…  (10k, 100nF)": (
        "Şimdi yerleştirilecek parçaların değeri…  (10k, 100nF)"
    ),
    "Given to each part as it is placed. Leave it blank and the part is placed "
    "without one; F2 sets it afterwards either way.": (
        "Yerleştirilen her parçaya verilir. Boş bırakılırsa parça değersiz yerleştirilir; "
        "her hâlükârda F2 ile sonradan da girilebilir."
    ),
    "Click a hole to place": "Yerleştirmek için bir deliğe tıkla:",
    "Esc cancels.": "Esc iptal eder.",
    "Pick a part, then click the board. Esc cancels.": (
        "Bir parça seç, sonra karta tıkla. Esc iptal eder."
    ),
    # -- panel headings --------------------------------------------------------
    "Part": "Parça",
    "Pins": "Pin",
    "Rule / Kind": "Kural / Tür",
    "Message": "Mesaj",
    "Filter findings…  (error, short, R5', C7)": "Bulguları süz…  (error, short, R5', C7)",
    "pads": "ped",
    "a pin has no pad there — see DRC": "orada bir pinin pedi yok — DRC'ye bak",
    "it overlaps an existing pin — see DRC": "mevcut bir pinle çakışıyor — DRC'ye bak",
    # "To route", not "Left": the board edge in Board Features is already called Left,
    # and one English key cannot carry two meanings in a catalogue whose keys ARE the
    # English strings. Saying what the number counts is better English anyway.
    "To route": "Kalan",
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
    "Every view is closed. Board (Ctrl+1) and Schematic (Ctrl+2) are on the "
    "toolbar, beside 3D — and each of them can be dragged anywhere in "
    "the window, or out of it.": (
        "Bütün görünümler kapalı. Kart (Ctrl+1) ve Şema (Ctrl+2) araç çubuğunda, 3B'nin "
        "yanında — ve her biri pencerenin herhangi bir yerine ya da dışına "
        "sürüklenebılir."
    ),
    # The strip the update check puts across the top. Its title is never drawn -- the panel
    # has no title bar -- but it is what Qt calls the dock, so it is named like one.
    "Update": "Güncelleme",
    "Export…": "Dışa Aktar…",
    "Write the sheet beside the document as SVG, PDF and PNG. All three are "
    "drawn from the same file, so they cannot disagree about the circuit.": (
        "Sayfayı belgenin yanına SVG, PDF ve PNG olarak yazar. Üçü de aynı dosyadan "
        "çizilir, bu yüzden devre konusunda birbiriyle çelişemezler."
    ),
    "Add Part…": "Parça Ekle…",
    "Put a part in the design without deciding where it goes on the board yet.": (
        "Kart üzerinde nereye geleceğine karar vermeden tasarıma bir parça ekler."
    ),
    "Wire": "Bağla",
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
    "Place on the Board": "Kart Üzerine Yerleştir",
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
    "Turn": "Döndür",
    "Turn the selected symbols a quarter clockwise. R does the same.": (
        "Seçili sembolleri saat yönünde çeyrek döndürür. R tuşu da aynısını yapar."
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
    "Write on the Sheet": "Sayfaya Yaz",
    "Text:": "Metin:",
    "No footprint called {id}.": "{id} adında bir ayak izi yok.",
    "Fix the sheet layout": "Sayfa düzenini sabitle",
    "Drag a part onto the board or the sheet — or pick one and click. Esc cancels.": (
        "Bir parçayı kartın ya da sayfanın üzerine sürükleyin — ya da birini seçip "
        "tıklayın. Esc iptal eder."
    ),
    # -- the welcome dialog, and autosave that writes the file itself ----------
    # "Perfboard Studio" is deliberately absent: it is the product's name, and a name is
    # the one string that must read the same in every language.
    "Draw the circuit, let the tool arrange it on a board a supplier stocks, "
    "and build it from the guide it writes.": (
        "Devreyi çiz, aracın onu satılan hazır bir kart üzerine yerleştirmesine izin ver "
        "ve yazdığı kılavuza bakarak kur."
    ),
    "New Project…": "Yeni Proje…",
    "A folder for the board and everything generated from it.": (
        "Kart ve ondan üretilen her şey için bir klasör."
    ),
    "Open Project…": "Proje Aç…",
    "A folder built around one board.": "Tek bir kartın etrafında kurulmuş klasör.",
    "Open a Board…": "Kart Aç…",
    "A single .perf file.": "Tek bir .perf dosyası.",
    "Where you left off": "Kaldığın yer",
    "Show this when Perfboard Studio starts": "Perfboard Studio açılırken bunu göster",
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
    "Arrange": "Diz",
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
    "Float the Panel": "Paneli Ayır",
    "Back to the Window": "Pencereye Geri Al",
    "Put the sheet in a window of its own, so it and the board can sit side by "
    "side. Dragging its title bar does the same, and so does dropping it back.": (
        "Sayfayı kendi penceresine alır, böylece kartla yan yana durabilirler. Başlık "
        "çubuğundan sürüklemek de aynı işi yapar, geri bırakmak da."
    ),
    # -- editing the circuit from the sheet, by right-clicking the thing that is wrong -
    # Three menus, chosen by what the pointer is over. The accelerators are checked as
    # three groups in tests/test_i18n.py, since the pin entry shares the symbol's menu.
    "&Properties…": "Ö&zellikler…",
    "What this part is, what it is called and what it is worth — including "
    "swapping its footprint for a different one.": (
        "Bu parçanın ne olduğu, adı ve değeri — ayak izini bir başkasıyla değiştirmek "
        "de dahil."
    ),
    "Re&name…": "Yeniden Adlandı&r…",
    "A new designator. Every net it is wired into comes with it.": (
        "Yeni bir etiket. Bağlı olduğu her net onunla birlikte gelir."
    ),
    "D&uplicate": "&Çoğalt",
    "Another part of the same kind and value, with the next free designator "
    "and no connections of its own.": (
        "Aynı türden ve aynı değerde bir parça daha; sıradaki boş etiketle ve kendine "
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
    "Out of the design, along with its connections.": (
        "Bağlantılarıyla birlikte tasarımın dışına."
    ),
    "&Disconnect {pin} from {net}": "{pin} pinini {net} netinden A&yır",
    "Rename Part": "Parçayı Yeniden Adlandır",
    "New designator": "Yeni etiket",
    "&Rub Out This Wire": "Bu Teli &Sil",
    "Take the line off the sheet. The pins stay connected — the net says so by "
    "name instead.": (
        "Çizgiyi sayfadan kaldırır. Pinler bağlı kalır — net bunu artık adıyla söyler."
    ),
    "Re&name Net…": "Neti Yeniden Adlandı&r…",
    "A new name. The pins on it, and any copper laid for it, stay.": (
        "Yeni bir ad. Üzerindeki pinler ve onun için döşenmiş bakır yerinde kalır."
    ),
    "Rename Net": "Neti Yeniden Adlandır",
    "New name": "Yeni ad",
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
    "Arran&ge the Sheet": "Sayfayı &Düzenle",
    "&Fit the Sheet": "Sayfayı &Sığdır",
    # -- board setup: the product first, the consequences behind Advanced ------
    "Advanced": "Gelişmiş",
    "Everything a stocked board already decides: its grid, what it is made of, "
    "its pads and whether it prints its own addresses. Worth opening for a "
    "board you cut yourself.": (
        "Hazır satılan bir kartın zaten belirlediği her şey: ızgarası, neyden yapıldığı, "
        "pedleri ve kendi adreslerini basıp basmadığı. Kendi kestiğiniz bir kart için "
        "açmaya değer."
    ),
    # -- projects: the folder a board and everything made from it live in ------
    "New &Project…": "Yeni &Proje…",
    "Name the board, choose what it is built on, and start in the schematic. "
    "Makes a folder to keep the board and everything generated from it.": (
        "Karta bir ad ver, neyin üzerine kurulacağını seç ve şematikten başla. Kartı ve "
        "ondan üretilen her şeyi bir arada tutacak bir klasör oluşturur."
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
        "Kartı kaydeder ve ondan üretilen her şeyi — 1:1 baskıları, şematiği, montaj "
        "kılavuzunu, malzeme listesini — yanındaki outputs/ klasörüne yeniden yazar."
    ),
    "New Project": "Yeni Proje",
    "What is this board called?": "Bu kartın adı ne?",
    "My Board": "Kartım",
    "Where should the project go?": "Proje nereye kurulsun?",
    "That folder is not empty": "O klasör boş değil",
    "{path} already has something in it. Pick another place, or another name.": (
        "{path} içinde zaten bir şeyler var. Başka bir yer ya da başka bir ad seçin."
    ),
    "Board for {name}": "{name} için kart",
    "Could not make the folder": "Klasör oluşturulamadı",
    "New project in {path}. Draw the circuit, then Place on the Board.": (
        "{path} içinde yeni proje. Devreyi çiz, sonra Kart Üzerine Yerleştir."
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
    "Everything else is saved. These had nothing to write:\n\n{lines}": (
        "Diğer her şey kaydedildi. Bunların yazacak bir şeyi yoktu:\n\n{lines}"
    ),
    # -- choosing the board the circuit goes on --------------------------------
    "Which board is this going on?": "Bu devre hangi karta girecek?",
    "Your circuit was placed, wired and checked on the roomy board and on the "
    "sizes below it. The suggested one is the smallest that builds as well: every "
    "part placed, every connection made, no warning the roomy board does not have, "
    "and at most {percent}% dearer to wire.": (
        "Devreniz geniş kartta ve ondan küçük boylarda yerleştirildi, tellendi ve "
        "denetlendi. Önerilen, aynı iyilikte kurulan en küçük boy: her parça yerinde, "
        "her bağlantı yapılmış, geniş kartta olmayan hiçbir uyarı yok, ve tellemesi en "
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
    "builds as well, at {percent}% of its wiring cost": (
        "aynı iyilikte kuruluyor, telleme maliyeti geniş karta göre %{percent}"
    ),
    "wires dearer: {percent}% of the roomy board's cost": (
        "tellemesi pahalı: geniş karta göre %{percent}"
    ),
    "warns: {rules}": "uyarı veriyor: {rules}",
    "{count} connection(s) would not route": "{count} bağlantı yönlendirilemiyor",
    "{count} DRC error(s) once wired": "tellenince {count} DRC hatası",
    "not tried · a quick layout had no room for {count} part(s)": (
        "denenmedi · hızlı yerleşimde {count} parçaya yer çıkmadı"
    ),
    "Keep the board I have  ·  {cols} × {rows}": "Mevcut kartım kalsın  ·  {cols} × {rows}",
    "fits, {percent}% full": "sığıyor, %{percent} dolu",
    "too small — {count} part(s) will not fit": "çok küçük — {count} parça sığmıyor",
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
    "Add a Part": "Parça Ekle",
    "Edit a Part": "Parçayı Düzenle",
    "Filter parts…  (555, BC547, resistor, dip-8)": "Parçaları süz…  (555, BC547, direnç, dip-8)",
    "The designator this part is known by, on the schematic and on the board. "
    "It has to be free on both — the two are one namespace.": (
        "Bu parçanın hem şemada hem kartta bilindiği ad. İkisinde de boş olmalı — "
        "ikisi tek bir ad uzayı."
    ),
    "What is printed on the part. It reaches the bill of materials, the guide's "
    "step text and a resistor's colour bands in 3D, so it is worth filling in.": (
        "Parçanın üzerinde yazan değer. Malzeme listesine, rehberin adım metnine ve 3D'de "
        "bir direncin renk bantlarına kadar gider; doldurmaya değer."
    ),
    "Put the whole schematic back in the view. The sheet is not re-fitted "
    "when the board changes, so an edit cannot move what you were looking at.": (
        "Şemanın tamamını panele geri sığdırır. Kart değiştiğinde sayfa yeniden "
        "sığdırılmaz; böylece bir düzenleme baktığınız yeri kaydıramaz."
    ),
    # -- the build guide, in the window ----------------------------------------
    "Build Guide": "Montaj Rehberi",
    # M&ontaj, not &Montaj: "&Mesafe Ölç" is in the same menu.
    "Show &Build Guide": "M&ontaj Rehberini Göster",
    "The soldering order, in the window: shortest part first, jumpers before "
    "whatever stands on them, ICs last. Picking a step shows it on the board.": (
        "Lehimleme sırası, pencerenin içinde: önce en alçak parça, üzerinde bir şey duran "
        "jumperlar ondan önce, entegreler en sonda. Bir adımı seçmek onu kart üzerinde gösterir."
    ),
    "Export the Guide…": "Rehberi Dışa Aktar…",
    "Build guide written": "Montaj rehberi yazıldı",
    "Written to {folder}, with {count} other files.": (
        "{folder} içine yazıldı, {count} dosya daha."
    ),
    "Open the Guide": "Rehberi Aç",
    "Schematic written": "Şema yazıldı",
    "Open the Sheet": "Sayfayı Aç",
    "Nothing to export": "Dışa aktarılacak bir şey yok",
    "This document has no parts to draw yet.": "Bu belgede henüz çizilecek parça yok.",
    "Show the Folder": "Klasörü Göster",
    "Close": "Kapat",
    # -- right-click -----------------------------------------------------------
    "&Copy This Finding": "Bu Bulguyu &Kopyala",
    "Copy &All Findings": "&Tüm Bulguları Kopyala",
    "findings copied to the clipboard": "bulgu panoya kopyalandı",
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
    "Discard It": "At",
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
    "this board": "bu kart",
    "{count} pin(s)": "{count} pin",
    # -- the Parts panel's package families (main._archetype_headings) -------------------
    "Axial resistors and diodes": "Eksenel dirençler ve diyotlar",
    "Ceramic disc capacitors": "Seramik disk kondansatörler",
    "Film capacitors": "Film kondansatörler",
    "Electrolytic capacitors": "Elektrolitik kondansatörler",
    "LEDs": "LED'ler",
    "Crystals": "Kristaller",
    "TO-92 packages": "TO-92 kılıflar",
    "TO-220 packages": "TO-220 kılıflar",
    "DIP packages": "DIP kılıflar",
    "Pin headers": "Pin başlıkları",
    "IDC box headers": "IDC kutu başlıklar",
    "Screw terminals": "Vidalı klemensler",
    "Screw terminals, wires from above": "Dik klemensler, kablo yukarıdan",
    "Potentiometers": "Potansiyometreler",
    "Tactile switches": "Tact butonlar",
    "Relays": "Röleler",
    "Module boards": "Modül kartları",
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
    "&Language": "&Dil",
    "English": "İngilizce",
    "Turkish": "Türkçe",
    "Language changed": "Dil değişti",
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
        "Izgara ölçüsü ve taban malzemesi. Malzeme süs değildir: montaj rehberindeki "
        "havya sıcaklığını ve pad kalkması kuralının geçerli olup olmadığını belirler."
    ),
    "Mounting holes and edge-connector fingers. A mounting bore takes the copper "
    "off the pads around it, so DRC treats a pin left there as an error.": (
        "Montaj delikleri ve kenar konnektörü parmakları. Montaj deliği çevresindeki "
        "padlerin bakırını alır; bu yüzden orada kalan bir pini DRC hata sayar."
    ),
    "Write the step-by-step soldering guide: one offline HTML file, the wire cut "
    "list and BOM as CSV, and the whole thing as JSON.": (
        "Adım adım lehimleme rehberini yazar: çevrimdışı tek bir HTML dosyası, kablo "
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
        "Şeridi bir delikte koparır. Kesik padin içinden delinir, dolayısıyla o deliğin "
        "ardından lehimlenecek bir şeyi kalmaz — kesiği geri almak için tekrar tıkla."
    ),
    "Leave any board mode: placing a part, drawing a conductor, connecting pins.": (
        "Hangi kart kipindeysen bırakır: parça yerleştirme, iletken çizme, pin bağlama."
    ),
    "Rearrange the unlocked parts to shorten the connections and make them "
    "solderable as traces rather than wires. Shows the result before applying it.": (
        "Kilitli olmayan parçaları, bağlantıları kısaltmak ve kabloyla değil lehim yoluyla "
        "yapılabilir kılmak için yeniden düzenler. Sonucu uygulamadan önce gösterir."
    ),
    "Search again from a different seed. Annealing is a random walk, so this is "
    "a real second answer rather than the same one twice.": (
        "Farklı bir tohumdan yeniden arar. Tavlama rastgele bir yürüyüştür; bu yüzden bu, "
        "aynı cevabın tekrarı değil gerçek bir ikinci cevaptır."
    ),
    "Click one pin, then another. They end up on the same net: an existing one if "
    "either pin is already on it, or a new one named for you if neither is.": (
        "Bir pine, sonra bir başkasına tıkla. İkisi aynı nete girer: pinlerden biri zaten "
        "bir netteyse o net, hiçbiri değilse senin için adlandırılan yeni bir net."
    ),
    "Name a net, then click its pins on the board. Nothing here needs KiCad.": (
        "Bir nete ad ver, sonra pinlerine kart üzerinde tıkla. Burada KiCad gerekmez."
    ),
    "Click each pin that belongs to the selected net. Right-click or Enter "
    "finishes, and the whole session goes on the history as one step.": (
        "Seçili nete ait her pine tıkla. Sağ tık veya Enter bitirir ve oturumun tamamı "
        "geçmişe tek adım olarak geçer."
    ),
    "Name, class, and the current and voltage it carries — which nothing else in "
    "the application can set, and which DRC's capacity and creepage rules need.": (
        "Ad, sınıf ve taşıdığı akım ile gerilim — bunları uygulamada başka hiçbir şey "
        "belirleyemez ve DRC'nin kapasite ile yüzeysel kaçak kuralları bunlara ihtiyaç duyar."
    ),
    "Take the pins selected in the Nets panel off their net. Expand a net to "
    "see them.": (
        "Netler panelinde seçili pinleri netlerinden çıkarır. Görmek için neti genişlet."
    ),
    "Forget what the net was for. Copper already laid for it stays on the board, "
    "and stops being anything re-route or the stale sweep will touch.": (
        "Netin ne için olduğunu unutur. Onun için döşenmiş bakır kartta kalır ve artık ne "
        "yeniden yönlendirmenin ne de artık temizliğinin dokunacağı bir şey olur."
    ),
    "Rip up the existing routing and plan it again from nothing. Use this after "
    "moving parts: autoroute only adds, so it leaves the copper laid out for "
    "where things used to be. Hand-drawn copper with no net is never touched.": (
        "Mevcut yönlendirmeyi söküp sıfırdan yeniden planlar. Parçaları taşıdıktan sonra bunu "
        "kullan: otomatik yönlendirme yalnızca ekler, dolayısıyla eski konumlar için döşenmiş "
        "bakırı yerinde bırakır. Neti olmayan elle çizilmiş bakıra asla dokunulmaz."
    ),
    "Draw conductors on the face you are NOT looking at as hatched, the way a part "
    "on the far side already is. Turn it off to see them solid.": (
        "Bakmadığın yüzdeki iletkenleri, karşı yüzdeki bir parçanın çizildiği gibi taralı "
        "çizer. Dolu görmek için kapat."
    ),
    "Click two holes. Says how many holes across they are, how far apart in mm, "
    "and how many steps of solder trace it would take to join them — three "
    "different numbers that answer three different questions.": (
        "İki deliğe tıkla. Kaç delik ötede olduklarını, mm cinsinden aralarındaki mesafeyi "
        "ve birleştirmek için kaç adım lehim yolu gerektiğini söyler — üç ayrı soruyu "
        "yanıtlayan üç ayrı sayı."
    ),
    "Find a part by reference, value or footprint and centre the view on it. "
    "On a dense board there is otherwise no way to answer “where is R37”.": (
        "Bir parçayı referansından, değerinden ya da ayak izinden bulur ve görünümü ona "
        "ortalar. Kalabalık bir kartta “R37 nerede” sorusunun başka yanıtı yoktur."
    ),
    "Open the 3D board view (Ctrl+3). Closed by default: it is the "
    "most expensive thing in the window to keep up to date.": (
        "3D kart görünümünü açar (Ctrl+3). Varsayılan olarak kapalıdır: pencerede güncel "
        "tutulması en pahalı şeydir."
    ),
    "Green for FR-4 and brown for phenolic, which is what those substrates "
    "actually look like.": (
        "FR-4 için yeşil, pertinaks için kahverengi; bu tabanlar gerçekten böyle görünür."
    ),
    "Every binding, read off this menu bar — plus the board gestures, which are "
    "on no menu and were previously only in the source.": (
        "Her kısayol, bu menü çubuğundan okunarak — artı hiçbir menüde olmayan ve daha "
        "önce yalnızca kaynak kodda bulunan kart hareketleri."
    ),
    "Wakes DRC's current-capacity rule and picks the wire gauge on the build "
    "guide's cut list. Nothing else in the application can set it.": (
        "DRC'nin akım kapasitesi kuralını uyandırır ve montaj rehberinin kesim listesindeki "
        "kablo kalınlığını seçer. Uygulamada bunu başka hiçbir şey belirleyemez."
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
    "Only stripboard has tracks to cut. File ▸ Board Setup ▸ Type.": (
        "Yalnızca şeritli plakette kesilecek şerit vardır. Dosya ▸ Kart Ayarları ▸ Tip."
    ),
    # -- the status bar's fixed sentences --------------------------------------
    "Nothing to place: the board is empty.": "Yerleştirilecek bir şey yok: kart boş.",
    "Select a net in the Nets panel, or a part on the board, then route.": (
        "Netler panelinden bir net ya da kart üzerinden bir parça seç, sonra yönlendir."
    ),
    "Select a net in the Nets panel, or a part on the board, then re-route.": (
        "Netler panelinden bir net ya da kart üzerinden bir parça seç, sonra yeniden yönlendir."
    ),
    "No netlist imported, so there is nothing to route.": (
        "İçe aktarılmış netlist yok, dolayısıyla yönlendirilecek bir şey de yok."
    ),
    "No stale conductors: every one still connects the net it claims.": (
        "Artık iletken yok: her biri hâlâ iddia ettiği neti bağlıyor."
    ),
    "Select a part or a conductor on the board first, then copy it.": (
        "Önce kart üzerinden bir parça ya da iletken seç, sonra kopyala."
    ),
    "Select a part or a conductor on the board first, then duplicate it.": (
        "Önce kart üzerinden bir parça ya da iletken seç, sonra çoğalt."
    ),
    "There is no block on the clipboard. Copy a part or some copper first.": (
        "Panoda blok yok. Önce bir parça ya da biraz bakır kopyala."
    ),
    "That block does not fit on this board.": "O blok bu karta sığmıyor.",
    "There are no parts on this board yet.": "Bu kartta henüz parça yok.",
    "Click a hole to cut the strip there; click a cut again to take it back. "
    "Esc ends.": (
        "Şeridi kesmek için bir deliğe tıkla; kesiği geri almak için tekrar tıkla. "
        "Esc bitirir."
    ),
    "This board has never been saved, so there is nothing on disk to reload.": (
        "Bu kart hiç kaydedilmedi, dolayısıyla diskte yeniden yüklenecek bir şey yok."
    ),
    "Click a pin, then the pin it joins. Neither on a net yet? One gets made. "
    "Esc cancels.": (
        "Bir pine, sonra birleşeceği pine tıkla. Hiçbiri bir nette değilse yeni bir net "
        "oluşturulur. Esc iptal eder."
    ),
    "Select the pins to disconnect in the Nets panel — expand a net to see "
    "them.": (
        "Ayrılacak pinleri Netler panelinden seç — görmek için bir neti genişlet."
    ),
    "Select one net in the Nets panel first.": "Önce Netler panelinden tek bir net seç.",
    "Opening the 3D view builds it — this takes a moment.": (
        "3D görünümü açmak onu kurar — bu biraz sürer."
    ),
    # -- dialog titles ---------------------------------------------------------
    "Re-route the nets whose parts moved?": (
        "Parçaları taşınan netler yeniden yönlendirilsin mi?"
    ),
    "<b>{names}</b> still carry the copper laid out before a part moved."
    "<p>Autoroute only adds, so routing now leaves that copper in place "
    "and puts more beside it. Re-routing them rips it up and plans "
    "again.</p>": (
        "<b>{names}</b> hâlâ bir parça taşınmadan önce döşenen bakırı taşıyor."
        "<p>Otomatik yönlendirme yalnızca ekler; şimdi yönlendirmek o bakırı yerinde bırakıp "
        "yanına yenisini koyar. Yeniden yönlendirmek onu söküp yeniden planlar.</p>"
    ),
    "Some connections could not be made": "Bazı bağlantılar yapılamadı",
    "Some connections could not be routed": "Bazı bağlantılar yönlendirilemedi",
    "Imported with warnings": "Uyarılarla içe aktarıldı",
    "Imported {count} net(s) from {name}": "{name} dosyasından {count} net içe aktarıldı",
    "with warnings:": "uyarılar:",
    "… and {count} more": "… ve {count} tane daha",
    # -- the status bar and the panels' summaries ---------------------------------
    # These were the last English left on a Turkish screen: the menus were translated
    # and the numbers under them were not.
    "DRC {errors} err / {warnings} warn": "DRC {errors} hata / {warnings} uyarı",
    "LVS {matched}/{total} · {opens} open · {shorts} short": (
        "LVS {matched}/{total} · {opens} açık · {shorts} kısa"
    ),
    "{count} to route · {length:.0f} mm": "{count} yönlendirilecek · {length:.0f} mm",
    "no netlist": "netlist yok",
    "done": "bitti",
    "Not on the board: {pins}": "Kartta değil: {pins}",
    "not on the board": "kartta değil",
    "{count} violation(s)": "{count} ihlal",
    "{matched}/{total} matched, {opens} open, {shorts} short, {physical} physical nets": (
        "{matched}/{total} eşleşti, {opens} açık, {shorts} kısa, {physical} fiziksel net"
    ),
    "{parts} part(s), {nets} net(s)": "{parts} parça, {nets} net",
    "{count} not on the board yet": "{count} tanesi henüz kartta değil",
    "power and ground drawn as {count} rail symbol(s)": (
        "güç ve toprak {count} ray simgesi olarak çizildi"
    ),
    "…and {count} more": "…ve {count} tane daha",
    "Nothing in the design yet. Add Part… describes one, or "
    "File ▸ Import KiCad Netlist… brings a whole circuit in.": (
        "Tasarımda henüz bir şey yok. Parça Ekle… bir tane tanımlar; "
        "Dosya ▸ KiCad Netlist İçe Aktar… bütün bir devreyi getirir."
    ),
    "3D view unavailable:": "3D görünüm kullanılamıyor:",
    "conductor(s) selected": "iletken seçili",
    "locked": "kilitli",
    "parts": "parça",
    "selected": "seçili",
    # -- the selection verbs, spliced into one sentence -----------------------------
    "Select a part on the board first, then {what}.": "Önce kartta bir parça seç, sonra {what}.",
    "rotate it": "döndür",
    "mirror it": "aynala",
    "delete it": "sil",
    "lock or unlock it": "kilitle ya da kilidini aç",
    "edit its properties": "özelliklerini düzenle",
    "{count} refused: {reasons}": "{count} reddedildi: {reasons}",
    "Rotated {count} part(s)": "{count} parça döndürüldü",
    "Mirrored {count} part(s)": "{count} parça aynalandı",
    "Locked {count} part(s)": "{count} parça kilitlendi",
    "Unlocked {count} part(s)": "{count} parçanın kilidi açıldı",
    "Deleted {count} part(s)": "{count} parça silindi",
    "Disconnected {count} pin(s)": "{count} pin ayrıldı",
    # -- confirmations, with the verb on the button ------------------------------------
    "Delete {count} conductor(s)?": "{count} iletken silinsin mi?",
    "Delete {refs}?": "{refs} silinsin mi?",
    "The {count} selected conductor(s) go with them.": (
        "Seçili {count} iletken de onlarla birlikte silinir."
    ),
    "Other wires and traces are left in place -- DRC and LVS will point at "
    "anything left dangling.": (
        "Diğer teller ve lehim yolları yerinde kalır -- boşta kalan ne varsa DRC ve LVS gösterir."
    ),
    "Delete net {name}?": "{name} neti silinsin mi?",
    "{count} conductor(s) already laid for it stay on the board, and stop "
    "being anything re-route or the stale sweep will touch.": (
        "Onun için döşenmiş {count} iletken kartta kalır ve artık ne yeniden yönlendirmenin "
        "ne de bayat temizliğinin dokunacağı bir şey olur."
    ),
    "{name} has changes that are not saved.": "{name} üzerinde kaydedilmemiş değişiklikler var.",
    "Saving keeps them; discarding loses them for good.": (
        "Kaydetmek korur; vazgeçmek temelli kaybettirir."
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
    "New {cols}×{rows} {material} board": "Yeni {cols}×{rows} {material} kart",
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
    "Trying arrangements, and routing each one to compare them…": (
        "Yerleşimler deneniyor, karşılaştırmak için her biri yönlendiriliyor…"
    ),
    "Ripping up and routing again…": "Sökülüp yeniden yönlendiriliyor…",
    "Routing every style…": "Her tarz yönlendiriliyor…",
    "Routing…": "Yönlendiriliyor…",
    "Planning cuts and links…": "Kesikler ve bağlantılar planlanıyor…",
    "Stopping, and keeping the best found so far…": (
        "Durduruluyor; şimdiye kadar bulunan en iyisi tutuluyor…"
    ),
    # -- the board materials, as Board Setup lists them --------------------------------
    "FR-4 — glass epoxy, the green kind. Tolerates heat well.": (
        "FR-4 — cam epoksi, yeşil olan. Isıya iyi dayanır."
    ),
    "FR-2 — phenolic paper (\"pertinaks\"), the brown kind. Pads lift easily.": (
        "FR-2 — fenolik kâğıt (\"pertinaks\"), kahverengi olan. Padler kolay kalkar."
    ),
    "FR-1 — phenolic paper, as FR-2.": "FR-1 — fenolik kâğıt, FR-2 gibi.",
    # -- the file watcher, the planner and the nets ------------------------------------
    "Still planning — cancel it or wait for it before closing.": (
        "Planlama sürüyor — kapatmadan önce iptal et ya da bitmesini bekle."
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
    "Cannot create this net": "Bu net oluşturulamıyor",
    "Cannot change this net": "Bu net değiştirilemiyor",
    # -- the board's own prose: measuring, picking pins, joining them -----------------
    "{hole} — the same hole.": "{hole} — aynı delik.",
    "holes": "delik",
    "{mm:.2f} mm apart": "{mm:.2f} mm arayla",
    "{steps} step(s) by trace": "lehim yoluyla {steps} adım",
    "Click the first hole.": "İlk deliğe tıkla.",
    "From {hole} — click the second hole.": "{hole} deliğinden — ikinci deliğe tıkla.",
    "No component pin at {hole}.": "{hole} deliğinde parça pini yok.",
    "{pin} is already on the list.": "{pin} zaten listede.",
    "{pin} is already on {net}.": "{pin} zaten {net} üzerinde.",
    "{pin} belongs to {net}. Disconnect it there first -- a pin can only "
    "be on one net.": (
        "{pin} {net} netine ait. Önce oradan ayır -- bir pin yalnızca bir nette olabilir."
    ),
    "{pin} is already the pin you started from.": "{pin} zaten başladığın pin.",
    "{a} and {b} are both already on {net}.": "{a} ve {b} zaten {net} üzerinde.",
    "{a} is on {net_a} and {b} is on {net_b}. Joining two nets is a change to "
    "the circuit — disconnect one of the pins first.": (
        "{a} {net_a} üzerinde, {b} ise {net_b} üzerinde. İki neti birleştirmek devreyi "
        "değiştirmektir — önce pinlerden birini ayır."
    ),
    # -- the sheet -----------------------------------------------------------------------
    "not in the design": "tasarımda yok",
    "not placed yet": "henüz yerleştirilmedi",
    # -- custom part: a body off its pins, and the IDC box header ------------------------
    "Body offset along the pins (mm)": "Gövde kayması, pin sırası boyunca (mm)",
    "Body offset across the pins (mm)": "Gövde kayması, pin sırasına dik (mm)",
    "IDC box header (ribbon cable)": "IDC kutu başlık (şerit kablo)",
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
    "The footprint calls this pin {name}.": "Footprint bu pini {name} olarak adlandırıyor.",
    # -- naming the board ------------------------------------------------------------
    "Rena&me Board…": "Kar&tı Yeniden Adlandır…",
    "The board's title, printed on the build guide, on the schematic and on "
    "the project folder. A board is named after its file when first saved.": (
        "Kartın başlığı: montaj rehberine, şemaya ve proje klasörüne basılır. Kart ilk "
        "kaydedildiğinde dosyasının adını alır."
    ),
    "Rename Board": "Kartı Yeniden Adlandır",
    "Board name:": "Kartın adı:",
    "Screw terminal, wires from above (vertical)": "Klemens, kablo yukarıdan (dik)",
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
        "Karta yazılmış etiketleri kartta ve 3B'de gösterir."
    ),
    "Add La&bel…": "&Etiket Ekle…",
    "Write something on the board -- \"MOTOR 24V\" beside the terminal that "
    "takes it. Printed on the 1:1 sheet and in the guide's pictures; drag it "
    "into place, double-click it to change it.": (
        "Karta bir şey yazar -- onu alan klemensin yanına \"MOTOR 24V\" gibi. 1:1 çıktıda "
        "ve rehberin resimlerinde basılır; sürükleyerek yerleştirin, değiştirmek için çift "
        "tıklayın."
    ),
    "Board Label": "Kart Etiketi",
    "What to write on the board: MOTOR 24V, CAN →…": "Karta ne yazılacak: MOTOR 24V, CAN →…",
    "Component side (top)": "Parça yüzü (üst)",
    "Solder side (bottom)": "Lehim yüzü (alt)",
    "A label on the solder side is written where the wiring is checked, and reads "
    "the right way round from underneath.": (
        "Lehim yüzündeki etiket, kabloların kontrol edildiği yere yazılır ve alttan "
        "bakınca düz okunur."
    ),
    "Height:": "Yükseklik:",
    "Rotation:": "Dönüş:",
    "Face:": "Yüz:",
    "Edit Label…": "Etiketi Düzenle…",
    "Add Label Here…": "Buraya Etiket Ekle…",
    "Print each part's pin names beside its pins, on the board and in 3D. Turn "
    "it off while placing or routing a crowded board.": (
        "Her parçanın pin adlarını pinlerinin yanına yazar, kartta ve 3B'de. Kalabalık "
        "bir kartı yerleştirirken ya da iz çekerken kapatın."
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
    "Temperature sensor, 1-Wire, needs a 4.7k pull-up on DQ": (
        "Sıcaklık sensörü, 1-Wire, DQ hattında 4,7k pull-up ister"
    ),
    "Timer": "Zamanlayıcı",
    "Switches": "Anahtarlar",
    "Momentary push button, legs 6.5 x 4.5 mm": (
        "Basılı tutulduğunda kapanan buton, bacaklar arası 6,5 x 4,5 mm"
    ),
    "Momentary push button, legs 12.5 x 5.0 mm": (
        "Basılı tutulduğunda kapanan buton, bacaklar arası 12,5 x 5,0 mm"
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
    "ESP32-WROOM-32 dev board, 38 pins, rows 25.4 mm apart": (
        "ESP32-WROOM-32 geliştirme kartı, 38 pin, sıralar arası 25,4 mm"
    ),
    "ESP32-C3 dev board, 30 pins, rows 22.86 mm apart": (
        "ESP32-C3 geliştirme kartı, 30 pin, sıralar arası 22,86 mm"
    ),
    "ATmega328P board, 30 pins, rows 15.24 mm apart": (
        "ATmega328P kartı, 30 pin, sıralar arası 15,24 mm"
    ),
    "RP2040 board, 40 pins, rows 17.78 mm apart": "RP2040 kartı, 40 pin, sıralar arası 17,78 mm",
    "ESP8266 board, 16 pins, rows 22.86 mm apart": (
        "ESP8266 kartı, 16 pin, sıralar arası 22,86 mm"
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
    "Wiring": "Yönlendirme",
    "Verify": "Kontrol",
    "Build": "Montaj",
    "Steps": "Adımlar",
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
    # -- the empty board --------------------------------------------------------------
    "{count} part(s) in the design, none on the board yet.": (
        "Tasarımda {count} parça var, kartta henüz hiçbiri yok."
    ),
    "Choose a Board and Place on the Board, in the steps above, put them here.": (
        "Üstteki adımlardan Kart Seç ve Kart Üzerine Yerleştir onları buraya getirir."
    ),
    "Draw the circuit on the sheet (Ctrl+2): the steps above take it to the board.": (
        "Devreyi şemada çizin (Ctrl+2): üstteki adımlar onu karta taşır."
    ),
    "Or drag parts onto the board from the Parts panel and Connect their pins.": (
        "Ya da parçaları Parçalar panelinden karta sürükleyip pinlerini Bağla ile birleştirin."
    ),
    "An existing circuit: File ▸ Import KiCad Netlist, or File ▸ Open Example.": (
        "Hazır bir devre için: Dosya ▸ KiCad Netlist İçe Aktar ya da Dosya ▸ Örnek Aç."
    ),
    "{count} part(s) are in the design: {catalog} known from the catalog, {kicad} "
    "matched by their KiCad footprint, {guess} guessed from their reference -- check "
    "those. Next: choose a board and place them.": (
        "{count} parça tasarımda: {catalog} tanesi katalogdan tanındı, {kicad} tanesi KiCad "
        "footprint'inden eşleşti, {guess} tanesi referansından tahmin edildi -- onları "
        "kontrol edin. Sıradaki: bir kart seçip parçaları yerleştirin."
    ),
    # -- the welcome dialog --------------------------------------------------------
    "Start": "Başla",
    "Examples": "Örnekler",
    "Draw a New Circuit": "Yeni Devre Çiz",
    "Start on the sheet: add parts and join their pins. The board comes after.": (
        "Şemadan başlayın: parçaları ekleyin ve pinlerini bağlayın. Kart ondan sonra gelir."
    ),
    "Import a KiCad Netlist…": "KiCad Netlist İçe Aktar…",
    "A circuit drawn in KiCad: its parts and connections come in as the design.": (
        "KiCad'de çizilmiş bir devre: parçaları ve bağlantıları tasarım olarak gelir."
    ),
    "The steps the bar across the top of the window walks through, in order.": (
        "Pencerenin üstündeki adım çubuğunun sırayla yürüdüğü adımlar."
    ),
    "{parts} part(s) on a {size} board": "{size} kart üzerinde {parts} parça",
    "{parts} part(s), drawn and not yet placed": "{parts} parça, çizilmiş ama henüz yerleşmemiş",
    # -- the board dialogs' pictures and their one line of numbers -----------------
    "The board as it will be drawn, component side up.": (
        "Kart, çizileceği hâliyle, bileşen yüzü üstte."
    ),
    "{width} × {height} mm ({holes} holes)": "{width} × {height} mm ({holes} delik)",
    "{gap} mm between pads": "pedler arası {gap} mm",
    "{along} mm between pads along a row, {down} mm down a column": (
        "pedler arası sıra boyunca {along} mm, sütun boyunca {down} mm"
    ),
    "See the Findings": "Bulguları Gör",
    "Open the Build Guide": "Montaj Rehberini Aç",
    "no parts yet": "henüz parça yok",
    "{parts} part(s) · {nets} net(s)": "{parts} parça · {nets} net",
    "nothing to place": "yerleştirilecek parça yok",
    "{placed}/{total} on the board": "{placed}/{total} kartta",
    "nothing to wire yet": "henüz bağlanacak bir şey yok",
    "{count} connection(s) left": "{count} bağlantı kaldı",
    "all joined": "hepsi bağlı",
    "nothing to check yet": "henüz denetlenecek bir şey yok",
    "{errors} error(s) · {warnings} warning(s)": "{errors} hata · {warnings} uyarı",
    "guide · 3D": "rehber · 3B",
    "What the board is: its parts and what joins them. Drawn on the sheet, or by "
    "placing parts on the board and connecting their pins.": (
        "Kartın ne olduğu: parçaları ve onları neyin birleştirdiği. Şemada çizilir ya da "
        "parçalar karta konup pinleri bağlanarak girilir."
    ),
    "Which perfboard it goes on. Chosen before the parts go down, while the size is "
    "still free: every stock size is tried with your circuit laid out on it.": (
        "Devrenin hangi delikli karta gideceği. Parçalar yerleşmeden, boyut hâlâ serbestken "
        "seçilir: satılan her boy, devreniz üzerine gerçekten yerleştirilerek denenir."
    ),
    "Where each part goes. Arranged for you, then yours to move.": (
        "Her parçanın nereye gideceği. Sizin için dizilir, sonra istediğiniz gibi taşırsınız."
    ),
    "What joins the pins on the board: solder traces, wires and jumpers. Autoroute "
    "lays them; the Draw menu lays them by hand.": (
        "Karttaki pinleri neyin birleştirdiği: lehim yolları, teller ve jumper'lar. Oto "
        "Yönlendir bunları döşer; Çiz menüsüyle elle döşenir."
    ),
    "Whether it can be built as drawn: design rules (DRC) and whether the board is "
    "the circuit (LVS).": (
        "Çizildiği gibi kurulup kurulamayacağı: tasarım kuralları (DRC) ve kartın devreyle "
        "aynı olup olmadığı (LVS)."
    ),
    "The soldering guide, step by step, with the board in 3D beside it.": (
        "Adım adım lehimleme rehberi, yanında kartın 3B görünümüyle."
    ),
    # -- what the engine says it did (ui/engine_text.py) ---------------------------
    "Place {parts} part(s) and {links} connection(s)": "{parts} parça ve {links} bağlantı yerleştir",
    "Place and arrange {count} part(s) from the schematic": "Şemadaki {count} parçayı karta yerleştir ve diz",
    "Place {count} part(s) on the board": "{count} parçayı karta yerleştir",
    "Place {ref} at {hole}": "{ref} parçasını {hole} deliğine yerleştir",
    "Move {count} component(s)": "{count} parçayı taşı",
    "Move {count} symbol(s) on the sheet": "Şemada {count} sembolü taşı",
    "Move {count} symbols on the sheet": "Şemada {count} sembolü taşı",
    "Move {ref} on the sheet": "{ref} sembolünü şemada taşı",
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
    "Route {net} ({count} connection)": "{net} netini yönlendir ({count} bağlantı)",
    "Route {net} ({count} connections)": "{net} netini yönlendir ({count} bağlantı)",
    "Autoroute {nets} nets ({count} connection)": "{nets} neti otomatik yönlendir ({count} bağlantı)",
    "Autoroute {nets} nets ({count} connections)": "{nets} neti otomatik yönlendir ({count} bağlantı)",
    "Autoroute (no matching nets)": "Otomatik yönlendirme (eşleşen net yok)",
    "Autoroute (no netlist imported)": "Otomatik yönlendirme (netlist yok)",
    "Re-route {count} net(s)": "{count} neti yeniden yönlendir",
    "Re-route {net}": "{net} netini yeniden yönlendir",
    "Autoroute stripboard: {cuts} cut(s), {links} link(s)": "Şeritli kartı otomatik yönlendir: {cuts} kesim, {links} köprü",
    "Cut track at {hole}": "{hole} deliğinde şeridi kes",
    "Cut {cuts} track(s) and fit {links} link(s)": "{cuts} şerit kes, {links} köprü tak",
    "Remove cut {id}": "{id} kesimini kaldır",
    "Set board to {cols}x{rows} {material}": "Kartı {cols}x{rows} {material} yap",
    "Use a {cols}x{rows} {material} board": "{cols}x{rows} {material} kart kullan",
    "Use a {preset} board": "{preset} kart kullan",
    "Drill 4 corner mounting holes ({mm} mm)": "Köşelere 4 montaj deliği del ({mm} mm)",
    "Drill {mm} mm mounting hole at {hole}": "{hole} deliğine {mm} mm montaj deliği del",
    "Drill {count} mounting holes": "{count} montaj deliği del",
    "Remove mounting hole {id}": "{id} montaj deliğini kaldır",
    "Add {count}-finger edge connector on the {edge} edge": "{edge} kenara {count} parmaklı kenar konnektörü ekle",
    "Remove edge connector {id}": "{id} kenar konnektörünü kaldır",
    "Limit build height to {mm} mm": "Montaj yüksekliğini {mm} mm ile sınırla",
    "Remove the build height limit": "Montaj yüksekliği sınırını kaldır",
    "Name the board {name}": "Karta {name} adını ver",
    "Write “{text}” on the board at {hole}": "Karta, {hole} deliğine “{text}” yaz",
    "Edit a label on the board": "Karttaki bir etiketi düzenle",
    "Delete {count} label(s) from the board": "Karttan {count} etiketi sil",
    "Delete {ref}": "{ref} parçasını sil",
    "Update {ref}": "{ref} parçasını güncelle",
    "Placement unchanged ({movable} movable part(s), {moves} moves tried) — nothing found would be cheaper to build than the board you have ({cost} against {other})": "Yerleşim değişmedi ({movable} taşınabilir parça, {moves} hamle denendi) — elinizdeki karttan daha ucuza kurulacak bir düzen bulunamadı (sizinki {cost}, en iyi aday {other})",
    "Placement unchanged ({movable} movable part(s), {moves} moves tried)": "Yerleşim değişmedi ({movable} taşınabilir parça, {moves} hamle denendi)",
    "{count} part(s) placed": "{count} parça yerleşti",
    "{count} turned": "{count} tanesi döndü",
    "~{mm} mm less connection length": "bağlantı uzunluğu ~{mm} mm kısaldı",
    "~{mm} mm more connection length": "bağlantı uzunluğu ~{mm} mm uzadı",
    "about the same connection length": "bağlantı uzunluğu hemen hemen aynı",
    "{count} overlap(s) cleared": "{count} çakışma giderildi",
    "{count} part(s) brought back over the board": "{count} parça kartın üstüne geri getirildi",
    "{count} blocked wire entr(ies) cleared": "kapalı {count} tel girişi açıldı",
    "{count} terminal(s) turned to face their edge": "{count} klemens kenarına bakacak şekilde döndü",
    "{count} hot pair(s) moved apart": "ısınan {count} parça çifti birbirinden uzaklaştırıldı",
    "{count} part(s) moved out from under a screw head": "{count} parça vida başının altından çıkarıldı",
    "routing cost {cost}": "yönlendirme maliyeti {cost}",
    "{made} connection(s) routed across {closed}/{considered} nets": "{closed}/{considered} nette {made} bağlantı yönlendirildi",
    "{count} could NOT be routed": "{count} tanesi YÖNLENDİRİLEMEDİ",
    "{count} needed an insulated wire or jumper": "{count} tanesi izoleli tel ya da jumper istedi",
    "{count} pad(s) to measure for isolation": "yalıtım için ölçülecek {count} ped",
    "{count} ordering passes": "{count} sıralama turu",
    "{count} old conductor(s) ripped up": "{count} eski iletken söküldü",
    "{count} connection(s) re-routed": "{count} bağlantı yeniden yönlendirildi",
    "{count} conductor(s) now": "şimdi {count} iletken",
    "Nothing to do: every net is already right on this board.": "Yapılacak bir şey yok: bu karttaki her net zaten doğru.",
    "{count} cut(s)": "{count} kesim",
    "{count} link(s)": "{count} köprü",
    "{count} problem(s)": "{count} sorun",
    "line": "çizgi",
    "rectangle": "dikdörtgen",
    "circle": "daire",
    "text": "metin",
    "left": "sol",
    "right": "sağ",
    "top": "üst",
    "bottom": "alt",
    "paste": "yapıştır",
    "duplicate": "çoğalt",
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
