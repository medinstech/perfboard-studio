"""What the build guide says, in each language it can say it in.

The guide is the one piece of engine output a person follows with an iron in their hand,
and until this module it existed only in English while the window around it spoke
Turkish. It is translated HERE, in the engine, rather than by the interface's catalogue
(``ui/i18n.py``), for two reasons that are both about the engine's own rules:

  THE WORDS ARE BUILT FROM FACTS. "C7 → C11, 4 holes apart" is assembled from a board,
  not looked up, so there is no finished English sentence for the interface to translate
  after the fact -- only a template the engine fills. The template has to be chosen where
  it is filled.

  THE EXPORTS HAVE NO INTERFACE. The MCP server and a headless run write the same guide
  the window does, with no Qt and no catalogue loaded.

The rules are the interface catalogue's, for the same reasons:

  EVERY KEY IS THE ENGLISH TEMPLATE, and a template's fields are named -- ``{hole}``,
  ``{count}`` -- so a translation may put them in whatever order its grammar needs. English
  is never "missing": it is the key, which is why ``language="en"`` writes exactly the
  guide it always did and every guide golden held still while this was built.

  WORDS THAT ARE DATA STAY DATA. An archetype, a conductor kind, a checkpoint kind, a
  warning code and a wire colour are identifiers in the guide's model and in its JSON;
  they are translated where they are SHOWN (a tag, a table cell), by looking the id up
  here like any other key.

Pure, like the rest of the engine: a table and a lookup, no clock, no I/O, no locale. A
language is chosen by the caller and carried on the guide, never read from the process.

``tests/test_phrasebook.py`` holds the table to the code in both directions -- every
template the guide can say has its Turkish, every Turkish entry is still said -- and
builds a Turkish guide for every board in the repository to look for English left in it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import cache
from typing import Literal, TypeAlias

#: The languages a guide can be written in. A ``TypeAlias`` rather than a PEP 695 alias
#: because it is read at run time by ``get_args`` -- see CLAUDE.md on the others.
GuideLanguage: TypeAlias = Literal["en", "tr"]  # noqa: UP040

GUIDE_LANGUAGES: tuple[GuideLanguage, ...] = ("en", "tr")


def guide_language(code: str | None) -> GuideLanguage:
    """The guide language for an interface language code, English for anything else.

    Lenient on purpose: the window's language comes from the environment and the system
    locale (``tr_TR``, ``tr-TR``), and a guide in English is a working guide.
    """
    prefix = (code or "").replace("-", "_").split("_")[0].lower()
    return "tr" if prefix == "tr" else "en"


class Phrasebook:
    """``say(template, **fields)``: the template in this book's language, filled.

    Callable so that a call site reads as the sentence it produces. A template with no
    Turkish entry falls through to English rather than raising -- a guide with one English
    line in it is still a guide -- and the tests are what make that never happen.
    """

    __slots__ = ("_table", "language")

    def __init__(self, language: GuideLanguage) -> None:
        self.language: GuideLanguage = language
        self._table: dict[str, str] = TURKISH if language == "tr" else {}

    def __call__(self, template: str, /, **fields: object) -> str:
        text = self._table.get(template, template)
        return text.format(**fields) if fields else text

    def joined(self, items: Sequence[str]) -> str:
        """``a and b and c``, one ``and`` at a time, as the English always joined them."""
        if not items:
            return ""
        text = items[0]
        for item in items[1:]:
            text = self("{first} and {second}", first=text, second=item)
        return text

    def footprint(self, name: str) -> str:
        """A footprint's name as this book says it. See :data:`NAME_TEMPLATES`."""
        template = matching_template(name)
        if template is None:
            return name
        fields = _name_pattern(template).fullmatch(name)
        assert fields is not None
        return self(template).format(*fields.groups())


ENGLISH = Phrasebook("en")


def phrasebook(language: GuideLanguage) -> Phrasebook:
    return ENGLISH if language == "en" else Phrasebook(language)


# ---------------------------------------------------------------------------
# Footprint names
# ---------------------------------------------------------------------------

#: The phrasings ``footprints.py`` names a footprint in, with each number or size as a
#: numbered field. The engine keeps its English names -- they are in the footprint golden
#: and in every ``.perf`` a generated part's name is derived from -- so a name is
#: recognised and RE-SAID rather than translated at the source. Written out as that file
#: writes them, the most specific first where one is a prefix of another. The Parts panel
#: reads these too (``ui/partnames.py``), so a part is called one thing in the window and
#: in the guide it was fitted from.
NAME_TEMPLATES: tuple[str, ...] = (
    "Resistor (axial, {0}-hole span)",
    "Axial ({0}-hole span, {1} mm body)",
    "Axial, standing on pin {0} ({1}-hole span, {2} mm body)",
    "Diode, {0}",
    "Electrolytic capacitor, {0} mm dia, {1}-hole pitch",
    "Disc ceramic capacitor, {0} mm dia, {1}-hole pitch",
    "Disc ceramic capacitor, {0}-hole pitch",
    "Film capacitor, {0} mm, {1}-hole pitch",
    "Film capacitor, {0}-hole pitch",
    'DIP-{0} (0.6" wide)',
    '{0} on a DIP adapter (0.6" wide)',
    "{0} on a DIP adapter, rows {1} holes apart",
    "{0} on a DIP adapter",
    "TO-92 (inline, on-grid)",
    "RGB LED, {0} mm round, 4 legs",
    "LED, {0} mm round",
    "Pin header, {0}",
    "IDC box header, {0}",
    "Screw terminal, {0}-way, 5.08 mm pitch, vertical (wires from above)",
    "Screw terminal, {0}-way, 5.08 mm pitch",
    "Screw terminal, {0}-way",
    "Potentiometer, 3-pin inline",
    "Tactile switch, 4-pin",
    "Tactile switch, {0} mm",
    "Crystal, HC-49/U",
    "Small SPDT relay",
    "Custom part, {0} pins, {1} mm, body offset {2} mm, numbered as a DIP",
    "Custom part, {0} pins, {1} mm, numbered as a DIP",
    "Custom part, {0} pins, {1} mm, body offset {2} mm",
    "Custom part, {0} pins, {1} mm",
    "Module, {0} pins, {1} mm, seated {2} mm up",
    "Flying leads, {0} wires to a part off the board, {1} mm",
    "Flying leads, {0} wires to a part off the board",
    "Flying leads, 1 wire to a part off the board, {0} mm",
    "Flying leads, 1 wire to a part off the board",
)

#: What a field may hold: a number, a size like "15x10x8" or "5 x 3", an offset pair
#: "-2, 1.5", a package like "DO-41". Never a whole clause -- a field that could swallow
#: ", 5.08 mm pitch" would let a short template claim a longer name.
_FIELD = r"([-0-9A-Za-z.]+(?:\s?x\s?[-0-9.]+)*(?:, [-0-9.]+)?)"


@cache
def _name_pattern(template: str) -> re.Pattern[str]:
    parts = re.split(r"\{\d\}", template)
    return re.compile(_FIELD.join(re.escape(part) for part in parts))


def matching_template(name: str) -> str | None:
    """Which of the engine's phrasings ``name`` is, or None for a name somebody typed."""
    for template in NAME_TEMPLATES:
        if _name_pattern(template).fullmatch(name):
            return template
    return None


# ---------------------------------------------------------------------------
# Turkish
# ---------------------------------------------------------------------------

#: Vocabulary is the interface catalogue's, so the guide and the window it is read beside
#: say one thing one way: a "lehim yolu" is a trace, a "hat" is a run of it, a "ped" a pad,
#: "komponent yüzü" and "lehim yüzü" the two faces. An address is never given a suffix --
#: "C7'ye" would need the reader's pronunciation of a letter to get the vowel harmony right
#: -- so the suffix goes on the word beside it: "C7 deliğine". Numbers keep their point,
#: as they do everywhere else in the window, because a board has "0.6 mm" printed on it.
TURKISH: dict[str, str] = {
    # -- joining things -----------------------------------------------------------------
    "{first} and {second}": "{first} ve {second}",
    "{items}, and {last}.": "{items} ve {last}.",
    # -- phases -------------------------------------------------------------------------
    "Preparation": "Hazırlık",
    "Lowest profile": "En alçak parçalar",
    "IC sockets": "Entegre soketleri",
    "Small bodies": "Küçük gövdeler",
    "Medium bodies": "Orta gövdeler",
    "Tall and mechanical": "Uzun ve mekanik parçalar",
    "Solder side: traces and bare wire": "Lehim yüzü: lehim yolları ve çıplak tel",
    "Long insulated wires": "Uzun izoleli teller",
    # -- a solderless breadboard (guide.BREADBOARD_PHASE_TITLES and the steps on one) --
    "Jumpers, then what lies flat": "Önce jumper'lar, sonra yatık parçalar",
    "ICs across the groove": "Oluğun üstüne entegreler",
    "Wires to the parts off the board": "Kart dışındaki parçaların telleri",
    "Checks and power": "Kontroller ve enerji",
    "The jumper wires first, laid flat on the plastic and pushed down into their holes, so "
    "nothing has to be lifted later to reach a hole under a part. Then the parts that lie "
    "flat: axial resistors and diodes.": (
        "Önce jumper telleri: plastiğin üstüne düz yatırılıp deliklerine bastırılarak, "
        "böylece sonradan bir parçanın altındaki deliğe ulaşmak için hiçbir şeyi kaldırmak "
        "gerekmez. Ardından yatık duran parçalar: eksenel dirençler ve diyotlar."
    ),
    "The ICs, each straddling the groove down the middle: one row of pins in row e, the "
    "other in row f. Touch something earthed before you pick one up.": (
        "Entegreler, her biri ortadaki oluğun iki yanında: bir sıra pin e sırasında, "
        "öbürü f sırasında. Birini eline almadan önce topraklı bir şeye dokun."
    ),
    "The wires to the parts off the board: into their holes here first, then to the "
    "parts themselves once they are mounted.": (
        "Kart dışındaki parçaların telleri: önce buradaki deliklerine, sonra parçalar "
        "yerine takılınca parçaların kendisine."
    ),
    "Run the final checks, and power up under current limit.": (
        "Son kontrolleri yap ve akım sınırı altında enerji ver."
    ),
    "Lay the board down with column 1 on the left and row j at the top: every address in "
    "this guide is printed on it, row letter first — e12 is row e, column 12.": (
        "Kartı 1. kolon solda, j sırası üstte olacak şekilde yatır: bu rehberdeki her adres "
        "üstünde basılı, önce sıra harfi — e12, e sırası ve 12. kolon demek."
    ),
    "Lay the breadboard down with column 1 on the left and row j at the top: every "
    "address in this guide is printed on it, row letter first — e12 is row e, column "
    "12. Then get the parts ready.": (
        "Breadboard'u 1. kolon solda, j sırası üstte olacak şekilde yatır: bu "
        "rehberdeki her adres üstünde basılı, önce sıra harfi — e12, e sırası ve 12. "
        "kolon demek. Sonra parçaları hazırla."
    ),
    "On some boards each rail is broken in the middle — a gap in its red or blue line. "
    "If yours is, bridge the two halves of every rail with a short jumper before "
    "anything else.": (
        "Bazı kartlarda her ray ortada kesiktir — kırmızı ya da mavi çizgisinde bir "
        "boşluk olur. Seninki öyleyse, her şeyden önce her rayın iki yarısını kısa bir "
        "jumper'la birleştir."
    ),
    "A solderless breadboard, {points} points. Nothing on it is cut, drilled or soldered: "
    "every part and every wire is pushed into its holes.": (
        "Lehimsiz bir breadboard, {points} nokta. Üzerinde hiçbir şey kesilmez, delinmez "
        "ya da lehimlenmez: her parça ve her tel deliklerine itilerek takılır."
    ),
    "A solderable breadboard, {points} points: a breadboard's holes and strips in copper. "
    "Nothing on it is cut: every part goes through its holes and is soldered to the strip "
    "under it.": (
        "Lehimlenebilir bir breadboard, {points} nokta: bir breadboard'un delikleri ve "
        "şeritleri, bakırda. Üzerinde hiçbir şey kesilmez: her parça deliklerinden geçer ve "
        "altındaki şeride lehimlenir."
    ),
    "Soldering guide · solderable breadboard, {points} points · {steps} steps, {checks} "
    "checks · Perfboard Studio {version}": (
        "Lehimleme rehberi · lehimlenebilir breadboard, {points} nokta · {steps} adım, "
        "{checks} kontrol · Perfboard Studio {version}"
    ),
    "Building guide · solderless breadboard, {points} points · {steps} steps, {checks} "
    "checks · Perfboard Studio {version}": (
        "Kurulum rehberi · lehimsiz breadboard, {points} nokta · {steps} adım, {checks} "
        "kontrol · Perfboard Studio {version}"
    ),
    "A solderless breadboard, {points} points": "Lehimsiz bir breadboard, {points} nokta",
    "Solid-core hookup wire, AWG {gauges} in {colours} — about {metres:.2f} m in total. "
    "Not stranded: a stranded end frays in the clip instead of going in.": (
        "Tek telli (solid) bağlantı teli, AWG {gauges}, renkler: {colours} — toplam "
        "yaklaşık {metres:.2f} m. Çok telli değil: çok telli bir uç klibe girmek yerine "
        "dağılır."
    ),
    "Across the groove, pin 1 in {hole}. Line both rows of legs up over their holes and "
    "press the body down evenly, so that no leg folds under it.": (
        "Oluğun üstünden, 1. pin {hole} deliğinde. İki sıra bacağı da deliklerinin "
        "üstüne hizala ve gövdeyi eşit bastır; hiçbir bacak altına kıvrılmasın."
    ),
    "A {package} on its DIP adapter, which should already carry the chip (phase 0). "
    "From here on it is a DIP.": (
        "DIP adaptörü üzerinde bir {package}; çip adaptöre 0. aşamada lehimlenmiş "
        "olmalı. Bundan sonrası bir DIP gibi."
    ),
    "It plugs straight into the breadboard on its own pins: check its orientation "
    "against the pin names, line every pin up over its hole and press it down evenly.": (
        "Kendi pinleriyle doğrudan breadboard'a takılır: yönünü pin adlarıyla "
        "karşılaştır, her pini deliğinin üstüne hizala ve eşit bastır."
    ),
    "The jumpers {wheres} run underneath this part. They went in first, in phase 1; "
    "check they are pressed down flat before this goes over them.": (
        "{wheres} jumper'ları bu parçanın altından geçiyor. Önce, 1. aşamada "
        "takıldılar; bu parça üstlerine gelmeden önce düz bastırıldıklarını kontrol et."
    ),
    "The wire entries face the {side} edge of the board — the screws on top, the "
    "openings towards the {side}. Check before pushing it in: it fits the holes either "
    "way round.": (
        "Kablo girişleri kartın {side} kenarına bakıyor — vidalar üstte, ağızlar {side} "
        "tarafa. Takmadan önce kontrol et: deliklere iki yönde de oturur."
    ),
    "{height:.0f} mm tall — check it clears anything meant to go over the board before "
    "you push it in.": (
        "{height:.0f} mm yüksekliğinde — takmadan önce kartın üstüne gelecek hiçbir "
        "şeye değmeyeceğini kontrol et."
    ),
    "{height:g} mm tall, and this build has {limit:g} mm of room. It will not fit as it "
    "stands — lay it down or swap it before you push it in.": (
        "{height:g} mm yüksekliğinde, bu montajda ise {limit:g} mm yer var. Bu hâliyle "
        "sığmaz — takmadan önce yatır ya da değiştir."
    ),
    "Strip {strip:g} mm off each end, bend both ends straight down and push them into "
    "their holes until the insulation meets the plastic.": (
        "Her iki uçtan {strip:g} mm soy, iki ucu da dik aşağı bük ve izolasyon plastiğe "
        "değene kadar deliklerine it."
    ),
    "Closing up": "Kapanış",
    "Cut the board, mark hole A1, and get the iron and the parts ready.": (
        "Kartı kes, A1 deliğini işaretle ve havyayı ısıtıp parçaları hazırla."
    ),
    "Anything that lies flat: axial resistors and diodes. These go first because a board "
    "with a tall part on it will not sit flat on the bench, and a part that cannot be "
    "pressed down solders at an angle.": (
        "Düz yatan her şey: eksenel dirençler ve diyotlar. Önce bunlar takılır, çünkü "
        "üzerinde uzun bir parça olan kart tezgâhta düz durmaz ve bastırılamayan bir parça "
        "eğri lehimlenir."
    ),
    "IC sockets. The ICs themselves go in at the very end -- heat and static are the two "
    "things that kill them, and both are avoidable by fitting them last.": (
        "Entegre soketleri. Entegrelerin kendisi en sonda takılır — onları öldüren iki şey "
        "ısı ve statik elektriktir ve en son takılarak ikisinden de kaçınılır."
    ),
    "Small bodies: ceramic and film capacitors, TO-92 transistors, LEDs.": (
        "Küçük gövdeler: seramik ve film kondansatörler, TO-92 transistörler, LED'ler."
    ),
    "Medium bodies: electrolytics, TO-220 packages, crystals.": (
        "Orta gövdeler: elektrolitikler, TO-220 kılıflar, kristaller."
    ),
    "Tall and mechanical: connectors, terminals, potentiometers, switches, relays.": (
        "Uzun ve mekanik parçalar: konnektörler, klemensler, potansiyometreler, anahtarlar, "
        "röleler."
    ),
    "Turn the board over. Solder traces and bare wire, worked one net at a time so each is "
    "finished and checked before the next crosses it.": (
        "Kartı ters çevir. Lehim yolları ve çıplak tel, her net bir sonraki onun üzerinden "
        "geçmeden önce bitsin ve kontrol edilsin diye birer birer."
    ),
    "Insulated wire, which may cross anything already on the solder side.": (
        "Lehim yüzünde zaten olan her şeyin üzerinden geçebilen izoleli tel."
    ),
    "Then the wires to the parts off the board: into their pads here first, then to the "
    "parts themselves once they are mounted.": (
        "Ardından kart dışındaki parçaların telleri: önce buradaki pedlerine, sonra parçalar "
        "yerine takılınca parçaların kendisine."
    ),
    "Fit the ICs, run the final checks, and power up under current limit.": (
        "Entegreleri tak, son kontrolleri yap ve akım sınırı altında enerji ver."
    ),
    "Cut the board": "Kartı kes",
    "drill the {count} mounting hole ({sizes} at {where})": (
        "{count} montaj deliğini del ({sizes}, yeri: {where})"
    ),
    "drill the {count} mounting holes ({sizes} at {where})": (
        "{count} montaj deliğini del ({sizes}, yerleri: {where})"
    ),
    "mark hole A1": "A1 deliğini işaretle",
    "check which corner the board's printed A1 is in": (
        "kartta basılı A1 işaretinin hangi köşede olduğuna bak"
    ),
    "check which corner the board's own numbering starts in": (
        "kartın kendi numaralandırmasının hangi köşeden başladığına bak"
    ),
    "This board prints a numbering of its own, and this guide keeps to its own "
    "addresses — {axes}.": (
        "Bu kart kendi numaralandırmasını basıyor; bu rehber ise kendi adreslerini "
        "kullanıyor — {axes}."
    ),
    "the columns: {runs}": "sütunlarda {runs}",
    "the rows: {runs}": "satırlarda {runs}",
    "{guide} are printed {printed}": "{guide} kartta {printed} olarak basılı",
    "{guide} is printed {printed}": "{guide} kartta {printed} olarak basılı",
    "{guide} are not printed": "{guide} için baskı yok",
    "{guide} is not printed": "{guide} için baskı yok",
    "{runs}, with a mark every {every} holes": "{runs}, her {every} delikte bir işaretle",
    "get the iron and the parts ready": "havyayı ısıtıp parçaları hazırla",
    "Drill before anything is soldered — the board can still go in a vice, and swarf "
    "brushes off a bare board instead of having to be picked out of a built one.": (
        "Delme işini hiçbir şey lehimlenmeden yap — kart hâlâ mengeneye takılabilir ve "
        "talaş, kurulmuş bir karttan tek tek ayıklanmak yerine çıplak karttan fırçayla "
        "silinir."
    ),
    "along a row": "satır boyunca",
    "down a column": "sütun boyunca",
    "This board's pads are oblong ({length:g} × {width:g} mm), so neighbouring pads "
    "{along} nearly touch while pads {across} are well clear. Solder flows between them "
    "far more easily in the first direction than the second — which is what makes the "
    "traces below quick, and what makes an accidental bridge {along} quick too.": (
        "Bu kartın pedleri oval ({length:g} × {width:g} mm): {along} komşu pedler neredeyse "
        "birbirine değer, {across} ise arada bol boşluk vardır. Lehim ilk yönde ikinciye "
        "göre çok daha kolay akar — aşağıdaki lehim yollarını çabuk yapan da budur, {along} "
        "kazara bir köprüyü çabuk yapan da."
    ),
    # -- the iron -----------------------------------------------------------------------
    "FR-4 tolerates heat well; the limit here is the component, not the board.": (
        "FR-4 ısıya iyi dayanır; buradaki sınır kart değil, parçadır."
    ),
    "Phenolic paper board. Its pads lift easily -- work in short touches, let a pad cool "
    "before returning to it, and never drag heat along a long run in one pass.": (
        "Fenolik kâğıt kart. Pedleri kolay kalkar — kısa dokunuşlarla çalış, bir pede geri "
        "dönmeden önce soğumasını bekle ve uzun bir hat boyunca ısıyı asla tek seferde "
        "sürükleme."
    ),
    # -- fitting a part -----------------------------------------------------------------
    "The top jumpers {wheres} run underneath this part, so they have to be soldered first "
    "— they are in phase 1 for that reason. Check they are down and lying flat before "
    "this goes in.": (
        "{wheres} üst yüz jumper'ları bu parçanın altından geçiyor, bu yüzden önce onların "
        "lehimlenmesi gerekir — 1. aşamada olmalarının sebebi bu. Bu parça takılmadan önce "
        "yerlerine oturduklarını ve düz yattıklarını kontrol et."
    ),
    "The top jumper {where} runs underneath this part, so it has to be soldered first — it "
    "is in phase 1 for that reason. Check it is down and lying flat before this goes in.": (
        "{where} üst yüz jumper'ı bu parçanın altından geçiyor, bu yüzden önce onun "
        "lehimlenmesi gerekir — 1. aşamada olmasının sebebi bu. Bu parça takılmadan önce "
        "yerine oturduğunu ve düz yattığını kontrol et."
    ),
    "on this board": "bu karttaki",
    "from {start} to {end}": "{start} → {end} arasındaki",
    "the part next to it": "yanındaki parça",
    "{source} runs hot and sits close by. Fit a 105 °C-rated part here if you have one — "
    "an 85 °C electrolytic beside a heatsink is the first thing on the board to dry out.": (
        "{source} ısınıyor ve hemen yakında duruyor. Varsa buraya 105 °C'lik bir parça tak — "
        "bir soğutucunun yanındaki 85 °C'lik elektrolitik, kartta kuruyan ilk şey olur."
    ),
    "This part sits under {module}'s board. Press it right down onto the board so it "
    "clears the underside, and check it before {module} goes in: once that is on, this "
    "part is out of reach.": (
        "Bu parça {module} modülünün kartının altında kalıyor. Kartın alt yüzüne değmemesi "
        "için karta tam bastır ve {module} takılmadan önce kontrol et: modül takıldıktan "
        "sonra bu parçaya ulaşılamaz."
    ),
    "Fit a socket here if you have one — this phase is the sockets. The IC itself does not "
    "go in until the closing checks in phase 8, socket or no socket: it is the last thing "
    "on the board that should meet an iron.": (
        "Varsa buraya bir soket tak — bu aşama soketlerin aşaması. Entegrenin kendisi, soket "
        "olsun olmasın, 8. aşamadaki kapanış kontrollerine kadar takılmaz: kartta havyayla "
        "karşılaşması gereken son şey odur."
    ),
    "This part is mirrored: it goes in from the SOLDER side, not the component side. Check "
    "the pin order against the board before soldering.": (
        "Bu parça aynalanmış: komponent yüzünden değil, LEHİM yüzünden takılır. "
        "Lehimlemeden önce pin sırasını kartla karşılaştır."
    ),
    "The wire entries face the {side} edge of the board — the screws on top, the openings "
    "towards the {side}. Check before soldering: it fits the holes either way round.": (
        "Kablo girişleri kartın {side} kenarına bakıyor — vidalar üstte, ağızlar {side} "
        "tarafa. Lehimlemeden önce kontrol et: deliklere iki yönde de oturur."
    ),
    "The wires go in from ABOVE: this is the header, and the screw plug is pushed down "
    "into it. Keep the space over it clear for the plug and a screwdriver.": (
        "Kablolar YUKARIDAN girer: bu kısım başlıktır, vidalı fiş bunun içine aşağı doğru "
        "itilir. Üstünü fiş ve tornavida için boş bırak."
    ),
    "{ref} is not on this board: it is mounted off it, on the panel or in the enclosure, "
    "and these pads are where its wires land. Solder a wire into each pad from the "
    "component side and lead them all out over the {side} edge.": (
        "{ref} bu kartın üzerinde değil: kartın dışında, panelde ya da kutunun içinde duruyor; "
        "bu pedler tellerinin geldiği yer. Her pede komponent yüzünden bir tel lehimle ve "
        "hepsini {side} kenardan dışarı çıkar."
    ),
    "{hole} to {lead}": "{hole} → {lead}",
    "{hole} to {lead} — {net}, {colour} wire": "{hole} → {lead} — {net}, {colour} tel",
    "Wire by wire: {pairs}.": "Tel tel: {pairs}.",
    "Cut each wire {length:g} mm and strip {strip:g} mm at both ends.": (
        "Her teli {length:g} mm kes ve iki ucundan {strip:g} mm soy."
    ),
    "Cut each wire long enough to reach {ref} where it is mounted, with enough slack to "
    "open the enclosure, and strip {strip:g} mm at both ends.": (
        "Her teli {ref} parçasının takıldığı yere uzanacak, kutuyu açmaya yetecek kadar pay "
        "bırakarak kes ve iki ucundan {strip:g} mm soy."
    ),
    "{lead}: the wire in {hole}": "{lead}: {hole} deliğindeki tel",
    "{hole}, 1 wire": "{hole}, 1 tel",
    "{start} → {end}, {count} wires": "{start} → {end}, {count} tel",
    "Solder the female header strips here, not the module: it plugs in last, after the "
    "power-up checks, and can come out again. Seat each strip square on the board before "
    "soldering its end pins.": (
        "Buraya modülü değil, dişi pin başlığı şeritlerini lehimle: modül en son, enerji "
        "kontrollerinden sonra takılır ve yeniden çıkarılabilir. Uç pinlerini lehimlemeden "
        "önce her şeridi karta dik ve düzgün oturt."
    ),
    "Soldered straight in on its own pins, so it cannot come out again without desoldering "
    "every pin: check its orientation against the pin names first.": (
        "Kendi pinleriyle doğrudan lehimlenir, yani her pini sökmeden bir daha çıkmaz: "
        "önce yönünü pin adlarıyla karşılaştır."
    ),
    "{height:g} mm tall, and this build has {limit:g} mm of room. It will not fit as it "
    "stands — lay it down or swap it before you solder it in.": (
        "{height:g} mm yüksekliğinde, bu montajda ise {limit:g} mm yer var. Bu hâliyle "
        "sığmaz — lehimlemeden önce yatır ya da değiştir."
    ),
    "{height:.0f} mm tall — check it clears anything meant to go over the board before you "
    "solder it down.": (
        "{height:.0f} mm yüksekliğinde — lehimlemeden önce kartın üstüne gelecek hiçbir şeye "
        "değmeyeceğini kontrol et."
    ),
    # -- where a part goes, and which way round ------------------------------------------
    "no pins": "pin yok",
    "{start} → {end}, {steps} holes apart": "{start} → {end}, {steps} delik ara",
    "{start} → {end}, 1 hole apart": "{start} → {end}, 1 delik ara",
    "{start} → {end}, {count} pins": "{start} → {end}, {count} pin",
    "{start} → {end}, {count} pins with pin 1 at {hole}": (
        "{start} → {end}, {count} pin, 1. pin {hole} deliğinde"
    ),
    "{lead} in {hole}": "{lead}: {hole} deliğine",
    "{legs} — check against the part's datasheet": (
        "{legs} — parçanın datasheet'iyle karşılaştır"
    ),
    "Pin 1 (the notched end, marked with a dot) in {hole}": (
        "1. pin (çentikli, noktayla işaretli uç): {hole} deliğine"
    ),
    'Pin 1 (the adapter\'s "1", beside the chip\'s dot) in {hole}': (
        '1. pin (adaptörün üzerindeki "1", çipin noktasının yanında): {hole} deliğine'
    ),
    "A {package} on its DIP adapter, which should already carry the chip (phase 0). Solder "
    "the header pins to the adapter with their long ends pushed into a breadboard or into "
    "these holes, so they come out square and the right distance apart. From here on it is "
    "a DIP: fit a socket here if you have one, and the adapter itself goes in with the other "
    "ICs in phase 8.": (
        "DIP adaptörü üzerinde bir {package}; çip adaptöre 0. aşamada lehimlenmiş olmalı. Pin "
        "başlığını adaptöre, uzun uçları bir breadboard'a ya da bu deliklere takılıyken "
        "lehimle: pinler böylece dik ve doğru aralıkla çıkar. Bundan sonrası bir DIP gibi: "
        "varsa buraya bir soket tak; adaptörün kendisi diğer entegrelerle birlikte 8. "
        "aşamada takılır."
    ),
    "Solder the surface-mount chips onto their adapters first: {chips}. Line each chip's "
    "pin-1 dot up with the adapter's pin 1, tack one corner leg, check it is square, then do "
    "the rest with plenty of flux — and look along every leg under a magnifier for a bridge. "
    "Once the adapter is on the board, nobody can reach those legs.": (
        "Önce yüzey montaj çipleri adaptörlerine lehimle: {chips}. Her çipin 1. pin noktasını "
        "adaptörün 1. piniyle hizala, bir köşe bacağını puntala, düz durduğunu kontrol et, "
        "sonra kalanını bol flux ile lehimle — ve her bacağı büyüteçle köprü var mı diye "
        "kontrol et. Adaptör karta takıldıktan sonra o bacaklara kimse ulaşamaz."
    ),
    "{ref} ({package})": "{ref} ({package})",
    "Key slot on the side of the pin-1 row; pin 1 in {hole} (the cable's red stripe goes "
    "to pin 1)": (
        "Kilit yuvası 1. pin sırası tarafında; 1. pin {hole} deliğine (kablonun kırmızı "
        "şeridi 1. pine gelir)"
    ),
    "Cathode — the banded end — in {hole}": "Katot — bantlı uç — {hole} deliğine",
    # An axial part stood on end, over one hole, its top lead bent back down into the next.
    "Stand it on end over {hole} and bend the top lead back over and down into {other}.": (
        "{hole} deliğinin üstüne dik oturt; üstteki bacağı geri kıvırıp {other} deliğine "
        "indir."
    ),
    "Stand it on end over {hole}, the banded end down, and bend the top lead back over "
    "and down into {other}.": (
        "{hole} deliğinin üstüne bantlı ucu altta kalacak şekilde dik oturt; üstteki "
        "bacağı geri kıvırıp {other} deliğine indir."
    ),
    "Stand it on end over {hole}, the banded end up, and bend the top lead back over and "
    "down into {other}.": (
        "{hole} deliğinin üstüne bantlı ucu üstte kalacak şekilde dik oturt; üstteki "
        "bacağı geri kıvırıp {other} deliğine indir."
    ),
    "Pin 1 in {hole}; check the package outline against the board": (
        "1. pin {hole} deliğine; kılıfın dış hatlarını kartla karşılaştır"
    ),
    "Positive (long) lead": "Pozitif (uzun) bacak",
    "Positive lead": "Pozitif bacak",
    "Negative lead": "Negatif bacak",
    "Anode": "Anot",
    "Cathode (the banded end)": "Katot (bantlı uç)",
    "Negative lead (the side with the printed stripe)": "Negatif bacak (baskılı şeritli taraf)",
    "Anode (long lead)": "Anot (uzun bacak)",
    "Cathode (short lead, flat on the rim)": "Katot (kısa bacak, kenardaki düz taraf)",
    "Common anode (the longest leg)": "Ortak anot (en uzun bacak)",
    "Common cathode (the longest leg)": "Ortak katot (en uzun bacak)",
    "Red leg": "Kırmızı bacak",
    "Note: {note}": "Not: {note}",
    "gate": "kapı",
    "drain": "akaç",
    "source": "kaynak",
    "base": "baz",
    "collector": "kolektör",
    "emitter": "emiter",
    "anode": "anot",
    "cathode": "katot",
    # -- laying copper ------------------------------------------------------------------
    "(unassigned)": "(atanmamış)",
    "(empty path)": "(boş yol)",
    "{ends}, {pads} pads": "{ends}, {pads} ped",
    "Lay the {gauge} mm {material} along the pads first and solder it at each one. Work in "
    "one direction and do not go back over a section that has cooled.": (
        "{gauge} mm {material} omurgayı önce pedler boyunca yatır ve her pedde lehimle. Tek "
        "yönde ilerle, soğumuş bir bölümün üzerinden geri dönme."
    ),
    "Consider laying a lead offcut along these pads as a spine rather than building the "
    "run out of solder alone: it drops the resistance by roughly an order of magnitude "
    "and is far easier to make repeatable.": (
        "Hattı yalnızca lehimden oluşturmak yerine bu pedler boyunca omurga olarak bir "
        "bacak artığı yatırmayı düşün: direnci kabaca on kat düşürür ve aynı kalitede "
        "tekrarlamak çok daha kolaydır."
    ),
    "Tin each pad lightly first, then join them.": (
        "Önce her pedi hafifçe kalayla, sonra birleştir."
    ),
    "Flux is not optional on a run this long.": "Bu uzunlukta bir hatta flux şarttır.",
    "AWG {awg} is {copper:.2f} mm of copper and will not go through this board's {drill:g} "
    "mm holes. Lap-solder each end onto the face of its pad instead of passing it "
    "through.": (
        "AWG {awg}, {copper:.2f} mm bakırdır ve bu kartın {drill:g} mm deliklerinden geçmez. "
        "Her ucu delikten geçirmek yerine pedin yüzeyine bindirerek lehimle."
    ),
    "This one runs over the COMPONENT side, not the solder side. Keep it clear of anything "
    "that has to be reachable later.": (
        "Bu tel lehim yüzünden değil, KOMPONENT yüzünden geçer. Sonradan erişilmesi gereken "
        "her şeyden uzak tut."
    ),
    "Bare wire: it must not touch any other conductor along its length. Keep it flat "
    "against the board and check it against the neighbouring runs.": (
        "Çıplak tel: boyunca başka hiçbir iletkene değmemeli. Karta düz yatır ve komşu "
        "hatlarla arasını kontrol et."
    ),
    "No extra wire: bend the component's own lead over to reach the second hole, and "
    "solder both ends.": (
        "Ek tel yok: parçanın kendi bacağını ikinci deliğe ulaşacak şekilde bük ve iki ucunu "
        "da lehimle."
    ),
    "{hole} sits about one pad gap from {neighbour}, which is on another net. Do not let "
    "solder run across.": (
        "{hole} deliği, başka bir netteki {neighbour} deliğinden yalnızca bir ped aralığı "
        "uzakta. Lehimin aradan akmasına izin verme."
    ),
    # -- stripboard -----------------------------------------------------------------------
    "row {label}": "satır {label}",
    "column {label}": "sütun {label}",
    "After cutting the track at {cut}, measure resistance between {a} and {b}.": (
        "{cut} deliğindeki şeridi kestikten sonra {a} ile {b} arasındaki direnci ölç."
    ),
    "Open circuit. Anything below a few hundred kΩ means copper is still bridging the cut "
    "— clear it before soldering anything.": (
        "Açık devre. Birkaç yüz kΩ'un altındaki her değer, kesiği hâlâ bakırın "
        "köprülediğini gösterir — bir şey lehimlemeden önce temizle."
    ),
    # -- checks ---------------------------------------------------------------------------
    "{a} ↔ {b} must be open": "{a} ↔ {b} açık devre olmalı",
    "With the trace for {net} finished, measure resistance between {a} and {b}.": (
        "{net} lehim yolu bittikten sonra {a} ile {b} arasındaki direnci ölç."
    ),
    "Open circuit. Any reading at all means solder has bridged them.": (
        "Açık devre. Herhangi bir değer okunursa lehim ikisini köprülemiş demektir."
    ),
    "Probe {a} and {b}.": "{a} ile {b} arasını ölç.",
    "Continuous — they are both on net {net}.": "Sürekli — ikisi de {net} netinde.",
    "{net} run {span}: about {milliohm:.1f} mΩ end to end": (
        "{net} hattı {span}: uçtan uca yaklaşık {milliohm:.1f} mΩ"
    ),
    "Measure between {start} and {end}. Subtract the reading with the probes touched "
    "together, or use four-wire mode if your meter has it.": (
        "{start} ile {end} arasını ölç. Uçlar birbirine değerken okunan değeri çıkar ya da "
        "ölçü aletinde varsa dört telli modu kullan."
    ),
    "About {milliohm:.1f} mΩ (accept {low:.1f}–{high:.1f} mΩ). Much higher means a cold "
    "joint or a crack in the run.": (
        "Yaklaşık {milliohm:.1f} mΩ ({low:.1f}–{high:.1f} mΩ arası kabul). Çok daha yüksekse "
        "soğuk lehim ya da hatta bir çatlak var demektir."
    ),
    "{net} run {span} must read as a dead short": "{net} hattı {span} tam kısa devre okumalı",
    "Measure between {start} and {end}, then touch the probes together and compare. A good "
    "run adds nothing you can read.": (
        "{start} ile {end} arasını ölç, sonra uçları birbirine değdirip karşılaştır. İyi bir "
        "hat okunabilir hiçbir şey eklemez."
    ),
    "The same as your probes touched together, give or take one count. This run should be "
    "about {milliohm:.1f} mΩ, far below what a hand meter resolves — so any reading you "
    "can actually distinguish is a cold joint or a crack, not the copper.": (
        "Uçlar birbirine değerken okunanla aynı, bir basamak artı eksi. Bu hat yaklaşık "
        "{milliohm:.1f} mΩ olmalı, el tipi bir ölçü aletinin çözebildiğinin çok altında — "
        "yani gerçekten ayırt edebildiğin her değer bakır değil, soğuk lehim ya da çatlaktır."
    ),
    # The same in Turkish, and on purpose: "J1 pin 1" is how a Turkish bench says it, and
    # "J1 (1. pin)" collided with the net name the isolation probes put in brackets after it.
    "{ref} pin {pin} ({name})": "{ref} pin {pin} ({name})",
    "{ref} pin {pin}": "{ref} pin {pin}",
    "{a} ↔ {b} must be separate": "{a} ↔ {b} ayrı olmalı",
    "Probe {a} ({net_a}) and {b} ({net_b}).": "{a} ({net_a}) ile {b} ({net_b}) arasını ölç.",
    "Open, or at least the circuit's own resistance — never a short.": (
        "Açık devre ya da en az devrenin kendi direnci — asla kısa devre değil."
    ),
    "Polarity sweep before power": "Enerji vermeden önce kutup taraması",
    "Look at every polarised part once more and compare it against the component-side "
    "sheet: {parts}.": (
        "Kutuplu her parçaya bir kez daha bak ve komponent yüzü çıktısıyla karşılaştır: "
        "{parts}."
    ),
    "Every stripe, band and flat facing the way the sheet shows. A backwards electrolytic "
    "fails loudly and a backwards diode fails silently.": (
        "Her şerit, bant ve düz taraf çıktının gösterdiği yöne bakıyor. Ters takılmış bir "
        "elektrolitik gürültüyle bozulur, ters bir diyot ise sessizce."
    ),
    "Fit the ICs, pin 1 as shown": "Entegreleri tak, 1. pin gösterildiği gibi",
    "Only now put {parts} into its socket, or straight into the board if you did not fit "
    "one, notch to the end the sheet marks. Straighten the legs on a flat surface first.": (
        "{parts} entegresini ancak şimdi soketine — soket takmadıysan doğrudan karta — "
        "çentiği çıktının işaretlediği uca gelecek şekilde tak. Önce bacaklarını düz bir "
        "yüzeyde düzelt."
    ),
    "Only now put {parts} into their sockets, or straight into the board if you did not "
    "fit one, notch to the end the sheet marks. Straighten the legs on a flat surface "
    "first.": (
        "{parts} entegrelerini ancak şimdi soketlerine — soket takmadıysan doğrudan karta — "
        "çentikleri çıktının işaretlediği uca gelecek şekilde tak. Önce bacaklarını düz bir "
        "yüzeyde düzelt."
    ),
    "Every notch and dot pointing the same way as the sheet.": (
        "Her çentik ve nokta çıktıdakiyle aynı yöne bakıyor."
    ),
    "First power-up, current limited": "İlk enerji, akım sınırlı",
    "Set the supply to the circuit's voltage and the current limit to a little above what "
    "you expect it to draw. Watch the current as it comes up, and keep a hand on the "
    "switch.": (
        "Güç kaynağını devrenin gerilimine, akım sınırını da devrenin çekmesini beklediğin "
        "değerin biraz üstüne ayarla. Açarken akımı izle ve elin şalterde olsun."
    ),
    "Current settles at roughly what you expected. If it runs into the limit, power down "
    "at once and go back to the isolation checks — something is bridged.": (
        "Akım aşağı yukarı beklediğin değerde oturur. Sınıra dayanırsa hemen kapat ve "
        "yalıtım kontrollerine geri dön — bir yerde köprü var."
    ),
    # -- the bench ------------------------------------------------------------------------
    "Soldering iron with a fine tip, set to {temperature} °C": (
        "İnce uçlu havya, {temperature} °C'ye ayarlı"
    ),
    "60/40 or lead-free solder, 0.7–1.0 mm": "60/40 ya da kurşunsuz lehim teli, 0.7–1.0 mm",
    "Flux — a pen or a small pot. Solder traces are not reliably makeable without it": (
        "Flux — kalem ya da küçük bir kutu. Lehim yolları onsuz güvenilir biçimde yapılamaz"
    ),
    "Side cutters and small pliers": "Yan keski ve küçük bir pense",
    "A multimeter with a continuity buzzer (every checkpoint below uses it)": (
        "Süreklilik buzzer'ı olan bir multimetre (aşağıdaki her kontrol noktası onu kullanır)"
    ),
    "Hookup wire, AWG {gauges} in {colours} — about {metres:.2f} m in total": (
        "Bağlantı teli, AWG {gauges}, renkler: {colours} — toplam yaklaşık {metres:.2f} m"
    ),
    "Hookup wire, AWG {gauges} in {colours} — about {metres:.2f} m, plus the wires to the "
    "parts off the board, cut to fit": (
        "Bağlantı teli, AWG {gauges}, renkler: {colours} — yaklaşık {metres:.2f} m, artı "
        "kart dışındaki parçaların telleri, ölçüye göre kesilir"
    ),
    "Bare tinned copper wire, AWG {gauges} — about {metres:.2f} m in total": (
        "Çıplak kalaylı bakır tel, AWG {gauges} — toplam yaklaşık {metres:.2f} m"
    ),
    "Wire strippers": "Tel sıyırıcı",
    "For the chips on adapters: the adapter boards, {pins} male header pins (2.54 mm), and a "
    "magnifier to check the chips' legs for bridges": (
        "Adaptör üzerindeki çipler için: adaptör kartları, {pins} erkek pin (2.54 mm) ve "
        "çiplerin bacaklarında köprü olup olmadığına bakmak için bir büyüteç"
    ),
    "A drill and {sizes} bits for the mounting holes, plus a deburring tool or a larger "
    "bit turned by hand": (
        "Montaj delikleri için bir matkap ve {sizes} uçlar, ayrıca bir çapak alma aleti ya "
        "da elle çevrilen daha büyük bir uç"
    ),
    "A drill and {sizes} bit for the mounting holes, plus a deburring tool or a larger bit "
    "turned by hand": (
        "Montaj delikleri için bir matkap ve {sizes} uç, ayrıca bir çapak alma aleti ya da "
        "elle çevrilen daha büyük bir uç"
    ),
    "Tinned copper wire for the trace spines, {gauges} — about {length:.0f} mm (component "
    "lead offcuts do the job just as well)": (
        "Lehim yolu omurgaları için kalaylı bakır tel, {gauges} — yaklaşık {length:.0f} mm "
        "(parça bacağı artıkları da aynı işi görür)"
    ),
    # -- what the guide could not cover --------------------------------------------------
    "No step was written for {parts}: their footprint is not in the library, so this guide "
    "cannot say which holes they go in.": (
        "{parts} için adım yazılmadı: kılıfları kütüphanede yok, bu yüzden bu rehber hangi "
        "deliklere gireceklerini söyleyemez."
    ),
    "{count} fingers on the {edge} edge from {hole}": (
        "{edge} kenarda {hole} deliğinden başlayan {count} parmak"
    ),
    "This board has edge-connector fingers ({runs}). No step below covers them: they are "
    "part of the board, not something to make. Fit whatever mates with them last, and "
    "keep the iron off them until then — a tinned finger no longer fits a connector.": (
        "Bu kartta kenar konnektörü parmakları var ({runs}). Aşağıdaki hiçbir adım bunları "
        "kapsamaz: kartın bir parçasıdırlar, yapılacak bir şey değil. Onlara takılacak şeyi "
        "en son tak ve o zamana kadar havyayı onlardan uzak tut — kalaylanmış bir parmak "
        "artık konnektöre girmez."
    ),
    "No netlist has been imported, so there are no continuity checks. The steps describe "
    "what to build; nothing here can confirm it is the right circuit. Import the "
    "schematic's netlist to get the verification half.": (
        "Netlist içe aktarılmadığı için süreklilik kontrolü yok. Adımlar neyin kurulacağını "
        "anlatır; burada hiçbir şey bunun doğru devre olduğunu doğrulayamaz. Doğrulama "
        "yarısını almak için şemanın netlistini içe aktar."
    ),
    "{count} net(s) are not fully connected on this board. Following this guide will "
    "reproduce the board as it is, including those gaps — route them first.": (
        "Bu kartta {count} net tam bağlı değil. Bu rehberi izlemek kartı bu boşluklarla "
        "birlikte olduğu gibi üretir — önce onları yönlendir."
    ),
    "{count} short(s) between nets the schematic keeps apart. Do not build this board "
    "until they are gone.": (
        "Şemanın ayrı tuttuğu netler arasında {count} kısa devre var. Bunlar giderilmeden "
        "bu kartı kurma."
    ),
    "{count} error(s) in the circuit itself ({parts}) — a chip or a module with its supply "
    "or ground on nothing, a part drawn the wrong way round, or a pin the part does not have. "
    "This guide builds the circuit as drawn, those included: fix the circuit first.": (
        "Devrenin kendisinde {count} hata var ({parts}) — beslemesi ya da toprağı hiçbir yere "
        "bağlanmamış bir entegre ya da modül, ters çizilmiş bir parça ya da parçada olmayan bir "
        "pin. Bu rehber devreyi çizildiği gibi kurdurur, bunlar da dahil: önce devreyi düzeltin."
    ),
    "{count} DRC error(s) on this board — overlapping parts, crossing conductors or pins "
    "sharing a hole. The steps below describe it anyway; some of them will not be "
    "physically possible.": (
        "Bu kartta {count} DRC hatası var — üst üste binen parçalar, kesişen iletkenler ya "
        "da aynı deliği paylaşan pinler. Aşağıdaki adımlar kartı yine de anlatır; bazıları "
        "fiziksel olarak mümkün olmayacak."
    ),
    "Nothing is routed yet, so this guide covers fitting the parts and nothing else.": (
        "Henüz hiçbir şey yönlendirilmedi, bu yüzden bu rehber yalnızca parçaların "
        "takılmasını kapsıyor."
    ),
    "unknown-footprint": "bilinmeyen kılıf",
    "edge-connector": "kenar konnektörü",
    "no-netlist": "netlist yok",
    "erc-error": "devre hatası",
    "drc-error": "DRC hatası",
    "no-conductors": "iletken yok",
    "lvs-open": "LVS açık devre",
    "lvs-short": "LVS kısa devre",
    # -- the summary line -----------------------------------------------------------------
    "{steps} step(s) across {phases} phase(s)": "{phases} aşamada {steps} adım",
    "{count} check(s)": "{count} kontrol",
    "{count} track(s) to cut": "kesilecek {count} şerit",
    "{count} wire(s) to cut": "kesilecek {count} tel",
    "{count} warning(s)": "{count} uyarı",
    # -- the exported guide ---------------------------------------------------------------
    "{name} — build guide": "{name} — montaj rehberi",
    "Soldering guide · {cols} × {rows} {material} perfboard at {pitch:g} mm pitch · "
    "{steps} steps, {checks} checks · Perfboard Studio {version}": (
        "Lehimleme rehberi · {cols} × {rows} {material} delikli plaket, {pitch:g} mm aralık · "
        "{steps} adım, {checks} kontrol · Perfboard Studio {version}"
    ),
    "Phase {number}": "Aşama {number}",
    "Check before moving on": "Devam etmeden önce kontrol et",
    " of ": " / ",
    " done": " tamam",
    "Reset progress": "İlerlemeyi sıfırla",
    "Cut these tracks first": "Önce bu şeritleri kes",
    "{count} cut(s), made from the copper side with a spot-face cutter or a 3 mm drill "
    "turned by hand. Each one takes the pad with it, so the hole it is made in has nothing "
    "to solder to afterwards. Do them all before the first part goes in — once a part is "
    "over a hole there is no way back to it.": (
        "{count} kesik; bakır yüzden bir spot-face frezesiyle ya da elle çevrilen 3 mm "
        "matkap ucuyla açılır. Her biri pedi de götürür, yani açıldığı delikte sonradan "
        "lehimlenecek bir şey kalmaz. Hepsini ilk parça takılmadan önce yap — bir deliğin "
        "üstüne parça geldikten sonra ona geri dönmenin yolu yoktur."
    ),
    "Hole": "Delik",
    "Strip": "Şerit",
    "Separates": "Ayırdıkları",
    "On the bench": "Tezgâhta",
    "Iron": "Havya",
    "{temperature} °C, no more than {dwell:g} s on any one pad. {note}": (
        "{temperature} °C, bir pedde en fazla {dwell:g} s. {note}"
    ),
    "The board": "Kart",
    "Cut it to {cols} × {rows} holes ({size}) and mark hole {a1} in the top-left corner on "
    "the COMPONENT side. Every address below is counted from it, so if it is marked wrong, "
    "everything else is.": (
        "Kartı {cols} × {rows} delik olarak kes ({size}) ve KOMPONENT yüzünde sol üst "
        "köşedeki {a1} deliğini işaretle. Aşağıdaki her adres ondan sayılır; yanlış "
        "işaretlenirse geri kalan her şey de yanlış olur."
    ),
    "{footprint} · pins {holes}": "{footprint} · pinler {holes}",
    "Bend the leads to {pitch:.2f} mm ({holes:.0f} holes).": (
        "Bacakları {pitch:.2f} mm'ye bük ({holes:.0f} delik)."
    ),
    "{pads} pads": "{pads} ped",
    "about {milliohm:.1f} mΩ": "yaklaşık {milliohm:.1f} mΩ",
    "{drop:.0f} mV drop": "{drop:.0f} mV düşüm",
    "Path: {holes}": "Yol: {holes}",
    ", strip {strip:.0f} mm at each end": ", iki ucundan {strip:.0f} mm soy",
    "Cut {length:.0f} mm of {colour} AWG {awg}{strip}.": (
        "{length:.0f} mm {colour} AWG {awg} tel kes{strip}."
    ),
    "Spine: {length:.0f} mm of {gauge:g} mm {material}.": (
        "Omurga: {length:.0f} mm, {gauge:g} mm {material}."
    ),
    "Probe {holes}": "Ölçüm noktaları: {holes}",
    "Do not apply power until this passes.": "Bu geçmeden enerji verme.",
    "Expect: {expected}": "Beklenen: {expected}",
    "Lists": "Listeler",
    "Parts": "Parçalar",
    "Qty": "Adet",
    "Value": "Değer",
    "Package": "Kılıf",
    "References": "Referanslar",
    "Wire": "Tel",
    "Type": "Tür",
    "Net": "Net",
    "From": "Nereden",
    "To": "Nereye",
    "Cut": "Kesim",
    "AWG": "AWG",
    "Colour": "Renk",
    "trace spine": "yol omurgası",
    "wire off the board": "kart dışı tel",
    "{count} wire(s) to parts off the board": "kart dışı parçalara {count} tel",
    "cut to fit": "ölçüye göre kes",
    "bare wire": "çıplak tel",
    "insulated wire": "izoleli tel",
    "{gauge:g} mm, laid along {pads} pads": "{gauge:g} mm, {pads} ped boyunca",
    # The 1:1 wire templates at the end of the guide.
    "Wire templates (1:1)": "Tel şablonları (1:1)",
    "Print these pages at 100 % — actual size, not fit to page — and hold the bar "
    "below against a ruler: if it is not {ruler} mm, the printer has scaled them. "
    "Cut each wire to the length of its straight drawing and mark it there: a dark "
    "mark is where the insulation is cut, a solid blue one where the wire goes down "
    "through the board, a dashed one where it turns along it. Then bend it to the "
    "shape beside, drawn as seen from the face the wire lies on.": (
        "Bu sayfaları %100 ölçekte yazdır — gerçek boyutta, sayfaya sığdırmadan — ve "
        "aşağıdaki çubuğu bir cetvelle karşılaştır: {ruler} mm değilse yazıcı ölçeği "
        "değiştirmiştir. Her teli düz çizimindeki boya kes ve işaretlerini oradan al: koyu "
        "işaret izolasyonun kesileceği yer, düz mavi işaret telin kartın içinden aşağı "
        "geçtiği yer, kesikli mavi işaret kartın üzerinde döndüğü yer. Sonra yanındaki "
        "şekle göre bük; şekil, telin durduğu yüzden bakılmış hâliyle çizilmiştir."
    ),
    "{length:.0f} mm · {colour} · AWG {awg}": "{length:.0f} mm · {colour} · AWG {awg}",
    "from the component side": "komponent yüzünden bakış",
    "from the solder side": "lehim yüzünden bakış",
    "turned to fit the page": "sayfaya sığsın diye döndürüldü",
    # CSV headings: lower case and without spaces, as a spreadsheet column wants them.
    "type": "tür",
    "net": "net",
    "from": "nereden",
    "to": "nereye",
    "path_mm": "yol_mm",
    "cut_mm": "kesim_mm",
    "strip_mm": "soyma_mm",
    "awg": "awg",
    "colour": "renk",
    "note": "not",
    "quantity": "adet",
    "value": "değer",
    "footprint": "kılıf",
    "references": "referanslar",
    # -- ids, where a person reads them ---------------------------------------------------
    # Wire colours.
    "red": "kırmızı",
    "black": "siyah",
    "yellow": "sarı",
    "green": "yeşil",
    "blue": "mavi",
    "white": "beyaz",
    "orange": "turuncu",
    "violet": "mor",
    "grey": "gri",
    "brown": "kahverengi",
    # What copper is made of, as a step's tag says it.
    "lead bend": "bacak bükme",
    "solder trace": "lehim yolu",
    "solder trace wired": "omurgalı lehim yolu",
    "top jumper": "üst yüz jumper",
    "strip": "şerit",
    "tinned copper": "kalaylı bakır",
    "lead offcut": "bacak artığı",
    # A checkpoint's tag.
    "continuity": "süreklilik",
    "isolation": "yalıtım",
    "resistance": "direnç",
    "polarity": "kutup",
    "power-on": "enerji verme",
    # The four edges of a board.
    "top": "üst",
    "bottom": "alt",
    "left": "sol",
    "right": "sağ",
    # A part step's tag: the package family.
    "axial-cylinder": "eksenel",
    "radial-electrolytic": "elektrolitik",
    "disc-ceramic": "seramik disk",
    "box-film": "film",
    "dip": "DIP",
    "to92": "TO-92",
    "to220": "TO-220",
    "led-round": "LED",
    "pin-header": "pin başlığı",
    "screw-terminal": "klemens",
    "potentiometer": "potansiyometre",
    "tactile-switch": "tact buton",
    "crystal-hc49": "kristal",
    "relay-box": "röle",
    "generic-box": "kutu",
    "box-header": "IDC başlık",
    "screw-terminal-vertical": "dik klemens",
    "module-board": "modül",
    "flying-leads": "kart dışı parça",
    "smd-adapter": "SMD adaptör",
    "axial-upright": "dik eksenel",
    # -- footprint names (NAME_TEMPLATES) -------------------------------------------------
    "Flying leads, {0} wires to a part off the board, {1} mm": (
        "Kart dışındaki bir parçaya {0} tel, {1} mm"
    ),
    "Flying leads, {0} wires to a part off the board": "Kart dışındaki bir parçaya {0} tel",
    "Flying leads, 1 wire to a part off the board, {0} mm": (
        "Kart dışındaki bir parçaya 1 tel, {0} mm"
    ),
    "Flying leads, 1 wire to a part off the board": "Kart dışındaki bir parçaya 1 tel",
    "Resistor (axial, {0}-hole span)": "Direnç (eksenel, {0} delik açıklık)",
    "Axial ({0}-hole span, {1} mm body)": "Eksenel ({0} delik açıklık, {1} mm gövde)",
    "Axial, standing on pin {0} ({1}-hole span, {2} mm body)": (
        "Eksenel, {0}. pinin üstünde dik ({1} delik açıklık, {2} mm gövde)"
    ),
    "Diode, {0}": "Diyot, {0}",
    "Electrolytic capacitor, {0} mm dia, {1}-hole pitch": (
        "Elektrolitik kondansatör, {0} mm çap, {1} delik aralık"
    ),
    "Disc ceramic capacitor, {0} mm dia, {1}-hole pitch": (
        "Disk seramik kondansatör, {0} mm çap, {1} delik aralık"
    ),
    "Disc ceramic capacitor, {0}-hole pitch": "Disk seramik kondansatör, {0} delik aralık",
    "Film capacitor, {0} mm, {1}-hole pitch": "Film kondansatör, {0} mm, {1} delik aralık",
    "Film capacitor, {0}-hole pitch": "Film kondansatör, {0} delik aralık",
    'DIP-{0} (0.6" wide)': 'DIP-{0} (0.6" geniş)',
    '{0} on a DIP adapter (0.6" wide)': '{0}, DIP adaptöründe (0.6" geniş)',
    "{0} on a DIP adapter, rows {1} holes apart": "{0}, DIP adaptöründe, sıralar {1} delik arayla",
    "{0} on a DIP adapter": "{0}, DIP adaptöründe",
    "TO-92 (inline, on-grid)": "TO-92 (sıralı, ızgaraya oturan)",
    "RGB LED, {0} mm round, 4 legs": "RGB LED, {0} mm yuvarlak, 4 bacak",
    "LED, {0} mm round": "LED, {0} mm yuvarlak",
    "Pin header, {0}": "Pin başlığı, {0}",
    "IDC box header, {0}": "IDC kutu başlık, {0}",
    "Screw terminal, {0}-way, 5.08 mm pitch, vertical (wires from above)": (
        "Vidalı klemens, {0} yollu, 5.08 mm aralık, dik (kablo yukarıdan)"
    ),
    "Screw terminal, {0}-way, 5.08 mm pitch": "Vidalı klemens, {0} yollu, 5.08 mm aralık",
    "Screw terminal, {0}-way": "Vidalı klemens, {0} yollu",
    "Potentiometer, 3-pin inline": "Potansiyometre, 3 pin sıralı",
    "Tactile switch, 4-pin": "Tact buton, 4 pin",
    "Tactile switch, {0} mm": "Tact buton, {0} mm",
    "Crystal, HC-49/U": "Kristal, HC-49/U",
    "Small SPDT relay": "Küçük SPDT röle",
    "Custom part, {0} pins, {1} mm, body offset {2} mm, numbered as a DIP": (
        "Özel parça, {0} pin, {1} mm, gövde kaydırması {2} mm, DIP gibi numaralı"
    ),
    "Custom part, {0} pins, {1} mm, numbered as a DIP": (
        "Özel parça, {0} pin, {1} mm, DIP gibi numaralı"
    ),
    "Custom part, {0} pins, {1} mm, body offset {2} mm": (
        "Özel parça, {0} pin, {1} mm, gövde kaydırması {2} mm"
    ),
    "Custom part, {0} pins, {1} mm": "Özel parça, {0} pin, {1} mm",
    "Module, {0} pins, {1} mm, seated {2} mm up": "Modül, {0} pin, {1} mm, {2} mm yukarıda",
}


__all__ = [
    "ENGLISH",
    "GUIDE_LANGUAGES",
    "NAME_TEMPLATES",
    "TURKISH",
    "GuideLanguage",
    "Phrasebook",
    "guide_language",
    "matching_template",
    "phrasebook",
]
