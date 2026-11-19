"""
Catalogue of everything ScrapTrust can name in a photo.

Each entry is described in plain words. The zero-shot CLIP model compares a photo
with these descriptions, so adding a new material means adding an entry here:
no images, labels or retraining are needed.

Fields:
  group     top-level answer ("Metal", "Plastic", "Glass", "Mineral / rock", ...)
  family    finer class used for guidance ("non-ferrous metal", "silicate mineral", ...)
  category  matching folder in the waste-image dataset (None if the dataset has no such folder)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Material:
    key: str
    name: str
    group: str
    family: str
    dataset_category: Optional[str]
    prompts: tuple
    guidance: str
    kb_query: str = ""


def M(key, name, group, family, category, prompts, guidance, kb=""):
    return Material(key, name, group, family, category, tuple(prompts), guidance, kb)


METAL, ELEC, BATT, LAMP, GLASS, PLASTIC, PAPER, ORGANIC, AUTO, BUILD, OTHER, MINERAL, ROCK, NONE = (
    "Metal", "Electronics", "Battery", "Lamp", "Glass", "Plastic", "Paper", "Organic", "Automotive",
    "Construction material", "Other material", "Mineral", "Rock", "Not scrap",
)
MW, EW, BW, LB, GW, PW, PAW, OW, AW = (
    "metal waste", "E-waste", "battery waste", "light bulbs", "glass waste", "plastic waste", "paper waste",
    "organic waste", "automobile wastes",
)

MATERIALS: List[Material] = [
    # ------------------------------------------------------------------ metals
    M("copper", "Copper", METAL, "non-ferrous metal", MW,
      ["bare copper scrap", "pieces of reddish-orange copper sheet metal", "copper sheet offcuts", "copper pipes and tubes",
       "shiny bare copper wire", "oxidised copper with brown patina"],
      "Non-magnetic and heavy, reddish-orange when clean. Keep it separate from brass (more yellow) and remove solder, "
      "paint and attachments: clean, uncoated copper earns the top grade. Confirm alloys with XRF.", "copper scrap grades"),
    M("insulated_wire", "Insulated copper wire / cable", METAL, "non-ferrous metal", MW,
      ["insulated copper wire and electrical cables", "a bundle of plastic-coated electric cables", "cable scrap with insulation"],
      "Valued on expected copper recovery (gauge and insulation thickness). Keep it apart from bare copper and remove plugs.",
      "copper scrap grades insulated wire"),
    M("brass", "Brass", METAL, "non-ferrous metal", MW,
      ["yellow brass plumbing fittings and valves", "brass scrap", "golden yellow brass taps", "brass shell casings"],
      "Copper-zinc alloy: yellow, heavy, non-magnetic. Separate from copper and remove steel parts; XRF confirms the alloy.",
      "brass and bronze"),
    M("bronze", "Bronze", METAL, "non-ferrous metal", MW,
      ["bronze scrap", "brown bronze castings and bushings", "a bronze statue or bearing"],
      "Copper-tin alloy, reddish-brown and non-magnetic; worth more than yellow brass. Confirm with XRF.", "brass and bronze"),
    M("aluminium", "Aluminium", METAL, "non-ferrous metal", MW,
      ["aluminium scrap", "aluminium extrusions and window frames", "light grey aluminium sheet metal", "aluminium profiles"],
      "Light, non-magnetic, silvery grey. Separate extrusions, sheet and cast pieces; remove steel screws (magnet test). "
      "Alloy grade needs XRF or OES.", "aluminium scrap types"),
    M("aluminium_cans", "Aluminium cans (UBC)", METAL, "non-ferrous metal", MW,
      ["crushed aluminium drink cans", "used beverage cans", "a bale of aluminium soda cans"],
      "Used beverage cans: keep them dry and free of steel cans (magnet test) and plastic.", "aluminium scrap types"),
    M("cast_aluminium", "Cast aluminium", METAL, "non-ferrous metal", MW,
      ["cast aluminium engine parts", "aluminium car wheels and rims", "cast aluminium gearbox housing"],
      "Higher-silicon cast alloys: keep them separate from wrought aluminium; remove steel inserts.", "aluminium scrap types"),
    M("steel", "Steel", METAL, "ferrous metal", MW,
      ["ferrous steel scrap", "heavy melting steel scrap", "steel beams, plates and bars", "a pile of steel scrap"],
      "Magnetic. Sorted by size, thickness and cleanliness; remove non-ferrous attachments, which are paid separately.",
      "ferrous vs non-ferrous magnet test"),
    M("iron", "Iron / rusty iron", METAL, "ferrous metal", MW,
      ["rusty iron scrap", "corroded rusty metal", "old rusty machinery parts", "rusted iron chains and tools"],
      "Rust-brown can look like copper in photos: a magnet settles it (iron is magnetic, copper is not).",
      "ferrous vs non-ferrous magnet test"),
    M("cast_iron", "Cast iron", METAL, "ferrous metal", MW,
      ["cast iron scrap", "cast iron pipes and radiators", "a cast iron engine block", "broken cast iron pieces"],
      "Magnetic, brittle, dark grey with a granular fracture. Keep it apart from steel; grades differ.",
      "ferrous vs non-ferrous magnet test"),
    M("stainless", "Stainless steel", METAL, "ferrous metal", MW,
      ["shiny stainless steel scrap", "stainless steel sinks and sheets", "brushed stainless steel pipes"],
      "300-series is non- or weakly magnetic; 400-series is magnetic. 304 and 316 look identical: only XRF separates them.",
      "stainless steel grades"),
    M("galvanised", "Galvanised steel", METAL, "ferrous metal", MW,
      ["galvanised steel sheet with zinc coating", "galvanised corrugated roofing sheets", "galvanised steel pipes"],
      "Zinc-coated steel: magnetic. Avoid cutting it with torches indoors, because zinc fumes are toxic.",
      "ferrous vs non-ferrous magnet test"),
    M("tin_cans", "Steel food cans (tinplate)", METAL, "ferrous metal", MW,
      ["steel food tin cans", "empty tinplate food cans", "crushed steel cans"],
      "Magnetic tinplate cans: separate them from aluminium cans with a magnet and rinse out food residue.",
      "ferrous vs non-ferrous magnet test"),
    M("lead", "Lead", METAL, "non-ferrous metal", MW,
      ["lead scrap, dull grey soft metal", "lead wheel weights", "lead sheet and flashing"],
      "Very heavy, dull grey, soft. Toxic: wear gloves, avoid dust, never melt without controls.", "lead scrap"),
    M("zinc", "Zinc", METAL, "non-ferrous metal", MW,
      ["zinc scrap", "bluish-grey zinc die-cast parts", "zinc sheet and roofing"],
      "Bluish-grey, non-magnetic, medium weight. Die-cast zinc often contains steel inserts; remove them.", "zinc"),
    M("titanium", "Titanium", METAL, "non-ferrous metal", MW,
      ["titanium scrap", "titanium turnings and plates", "grey titanium aerospace parts"],
      "Light, strong, non-magnetic, dull grey; gives white sparks on a grinder. Confirm grade with XRF.", "stainless titanium"),
    M("chrome", "Chrome-plated metal", METAL, "plated metal", MW,
      ["chrome-plated metal parts", "shiny chrome bumpers and taps", "mirror-finish chromed metal"],
      "The base metal may be steel, brass or zinc under the plating: check with a magnet and XRF.", "plated metal"),
    M("precious", "Gold / silver items", METAL, "precious metal", MW,
      ["gold jewellery scrap", "silver jewellery and cutlery", "gold-plated connector pins"],
      "Precious metal content needs an assay; plating is common. Store securely and record the source.", "precious metals"),
    # ------------------------------------------------------------- electronics
    M("pcb", "Printed circuit boards", ELEC, "electronics", EW,
      ["printed circuit boards", "green computer motherboards", "a pile of electronic circuit boards"],
      "Precious-metal bearing. Remove batteries and capacitors; boards are sold by grade (high-grade vs low-grade).",
      "e-waste composition hazards"),
    M("ewaste", "Electronic waste", ELEC, "electronics", EW,
      ["electronic waste", "old computer parts and electronics", "keyboards, monitors and computer components",
       "broken household appliances and electronics"],
      "Remove batteries first and keep CRTs intact; send boards to specialised refiners.", "e-waste composition hazards"),
    M("phones", "Mobile phones", ELEC, "electronics", EW,
      ["old mobile phones and smartphones", "a pile of used cell phones"],
      "Remove the lithium battery before processing; phones are high-grade e-scrap.", "e-waste composition hazards"),
    M("crt", "CRT monitors / TVs", ELEC, "electronics", EW,
      ["old CRT television sets", "cathode ray tube computer monitors"],
      "CRT glass contains lead: keep tubes intact and send them to a licensed CRT recycler.", "e-waste composition hazards"),
    # ----------------------------------------------------------------- batteries
    M("li_battery", "Lithium-ion batteries", BATT, "battery", BW,
      ["lithium-ion batteries", "laptop and phone batteries", "cylindrical 18650 battery cells",
       "power tool and e-bike battery packs"],
      "Fire risk: never crush or puncture. Tape terminals, store separately in non-combustible containers, isolate swollen cells.",
      "lithium-ion battery safety"),
    M("lead_acid", "Lead-acid batteries", BATT, "battery", BW,
      ["car batteries", "lead-acid batteries", "old vehicle batteries on a pallet"],
      "Lead and sulfuric acid: keep upright, don't drain, send to an authorised recycler.", "lead-acid batteries"),
    M("alkaline", "Household batteries (AA/AAA)", BATT, "battery", BW,
      ["AA and AAA household batteries", "a pile of alkaline batteries", "used single-use batteries"],
      "Collect separately by chemistry; tape lithium primaries; recycle for zinc, manganese and steel.", "other battery chemistries"),
    M("button_cells", "Button cell batteries", BATT, "battery", BW,
      ["button cell batteries", "small coin cell lithium batteries"],
      "Keep away from children; tape them; some older types contain mercury or silver.", "other battery chemistries"),
    # --------------------------------------------------------------------- lamps
    M("fluorescent", "Fluorescent tubes / CFLs", LAMP, "lamps", LB,
      ["fluorescent light tubes", "compact fluorescent lamps", "long fluorescent tube lights"],
      "Contain mercury: store intact and send to a lamp recycler.", "fluorescent lamps light bulbs"),
    M("bulbs", "Light bulbs", LAMP, "lamps", LB,
      ["incandescent light bulbs", "LED light bulbs", "a box of used light bulbs"],
      "LED bulbs go to e-waste; incandescent bulbs are not container glass.", "fluorescent lamps light bulbs"),
    # --------------------------------------------------------------------- glass
    M("glass_clear", "Clear glass", GLASS, "container glass", GW,
      ["clear glass bottles and jars", "transparent glass containers"], "Flint glass: keep it free of coloured glass and ceramics.",
      "glass recycling"),
    M("glass_green", "Green glass", GLASS, "container glass", GW,
      ["green glass bottles", "green wine bottles"], "Sort by colour; remove caps and corks.", "glass recycling"),
    M("glass_brown", "Brown (amber) glass", GLASS, "container glass", GW,
      ["brown amber glass bottles", "brown beer bottles"], "Sort by colour; remove caps.", "glass recycling"),
    M("glass_broken", "Broken glass / cullet", GLASS, "glass", GW,
      ["broken glass shards", "crushed glass cullet", "a pile of broken glass"],
      "Handle with gloves. Keep window glass, Pyrex and ceramics out of container-glass cullet.", "glass recycling"),
    M("window_glass", "Window / flat glass", GLASS, "flat glass", GW,
      ["flat window glass panes", "broken window glass sheets"],
      "Flat glass has a different chemistry from bottles: recycle it separately.", "glass recycling"),
    # ------------------------------------------------------------------- plastic
    M("pet", "PET plastic bottles (#1)", PLASTIC, "plastic", PW,
      ["clear PET plastic water bottles", "plastic drink bottles", "crushed PET bottles"],
      "Resin code 1, highly recyclable. Remove caps (PP) and keep PVC out.", "plastics resin identification codes"),
    M("hdpe", "HDPE containers (#2)", PLASTIC, "plastic", PW,
      ["HDPE milk jugs and detergent bottles", "opaque plastic jerry cans"],
      "Resin code 2, highly recyclable: rinse and remove labels where possible.", "plastics resin identification codes"),
    M("pvc", "PVC pipes (#3)", PLASTIC, "plastic", PW,
      ["PVC plastic pipes", "grey and white PVC pipes and fittings"],
      "Resin code 3: keep it away from PET. Recycled in dedicated PVC streams.", "plastics resin identification codes"),
    M("film", "Plastic film / bags (#4 LDPE)", PLASTIC, "plastic", PW,
      ["plastic bags and film", "plastic wrap and shrink film", "a pile of plastic carrier bags"],
      "LDPE film: collect clean and dry, separately from rigid plastics.", "plastics resin identification codes"),
    M("pp", "Polypropylene items (#5)", PLASTIC, "plastic", PW,
      ["polypropylene plastic tubs and caps", "plastic crates and containers"],
      "Resin code 5 (caps, tubs, crates): widely recyclable when clean.", "plastics resin identification codes"),
    M("polystyrene", "Polystyrene / foam (#6)", PLASTIC, "plastic", PW,
      ["white polystyrene foam packaging", "styrofoam cups and trays"],
      "Bulky and light: compact it and keep it clean; many curbside schemes reject it.", "plastics resin identification codes"),
    M("mixed_plastic", "Mixed plastic", PLASTIC, "plastic", PW,
      ["plastic bottles and containers", "plastic packaging waste", "a pile of mixed plastic waste"],
      "Check the resin codes (1-7); PET and HDPE recycle best. Keep it clean and separate films.",
      "plastics resin identification codes"),
    # --------------------------------------------------------------------- paper
    M("cardboard", "Cardboard", PAPER, "paper", PAW,
      ["cardboard boxes", "flattened corrugated cardboard", "a bale of cardboard"],
      "Old corrugated containers (OCC): keep them dry and free of tape-heavy, waxed or food-soiled board.", "paper and cardboard"),
    M("paper", "Paper / newspapers", PAPER, "paper", PAW,
      ["paper waste and newspapers", "office paper and magazines", "a stack of old newspapers"],
      "Keep it dry and clean; separate it from cardboard.", "paper and cardboard"),
    # ------------------------------------------------------------------- organic
    M("food", "Food waste", ORGANIC, "organic", OW,
      ["food waste and kitchen scraps", "rotting fruit and vegetable scraps"],
      "Compost or anaerobic digestion; remove packaging.", "organic waste"),
    M("garden", "Garden waste", ORGANIC, "organic", OW,
      ["garden waste, leaves and branches", "grass clippings and hedge trimmings"],
      "Green waste for composting; keep plastic and stones out.", "organic waste"),
    M("wood", "Wood", OTHER, "wood", None,
      ["wood scrap and pallets", "wooden planks and offcuts", "a pile of timber"],
      "Untreated wood can be recycled or composted; keep treated or painted wood separate.", ""),
    M("textiles", "Textiles", OTHER, "textiles", None,
      ["textile waste and old clothes", "a pile of fabric scraps"],
      "Separate reusable clothing from recycling-grade textiles.", ""),
    # ---------------------------------------------------------------- automotive
    M("car_parts", "Car parts", AUTO, "automotive", AW,
      ["car parts and automotive scrap", "car engine parts", "scrapped car bodies"],
      "Depollute first (fluids, refrigerant, battery, airbags); remove converters, alloy wheels, radiators and wiring.",
      "end-of-life vehicles automobile waste"),
    M("catalytic", "Catalytic converter", AUTO, "automotive", AW,
      ["catalytic converters", "a car catalytic converter with honeycomb ceramic"],
      "Contains platinum, palladium and rhodium; value needs an assay. Record the source.", "catalytic converters"),
    M("tyres", "Rubber tyres", AUTO, "rubber", AW,
      ["rubber tyres", "a pile of old car tyres"], "Send to tyre recyclers; never burn them.", "end-of-life vehicles tyres"),
    # -------------------------------------------------------------- construction
    M("concrete", "Concrete / rubble", BUILD, "construction", None,
      ["concrete rubble", "broken concrete and bricks", "construction demolition debris"],
      "Inert construction waste: can be crushed into aggregate; remove steel rebar (magnet).", ""),
    M("ceramics", "Ceramics / porcelain", BUILD, "construction", None,
      ["broken ceramic tiles", "porcelain toilets and sinks", "broken pottery"],
      "Not glass: keep it out of glass recycling; it goes to inert or aggregate streams.", "glass recycling"),
    # ------------------------------------------------------------------ minerals
    M("quartz", "Quartz", MINERAL, "silicate mineral", None,
      ["a clear quartz crystal", "white milky quartz rock", "hexagonal quartz crystals"],
      "SiO2, hardness 7 (scratches glass), glassy lustre, no cleavage. Spectrally almost featureless in VNIR-SWIR.",
      "reflectance spectroscopy basics"),
    M("amethyst", "Amethyst (purple quartz)", MINERAL, "silicate mineral", None,
      ["purple amethyst crystals", "an amethyst geode"], "Purple quartz coloured by iron and irradiation; hardness 7.",
      "reflectance spectroscopy basics"),
    M("feldspar", "Feldspar", MINERAL, "silicate mineral", None,
      ["pink feldspar mineral", "white feldspar crystals", "orthoclase feldspar specimen"],
      "Common rock-forming mineral, hardness 6, two cleavages at about 90°.", "reflectance spectroscopy basics"),
    M("muscovite", "Mica (muscovite)", MINERAL, "silicate mineral", None,
      ["silvery muscovite mica sheets", "flaky transparent mica mineral"],
      "Splits into thin flexible sheets. In SWIR: sharp Al-OH feature near 2200 nm plus 2350 and 2440 nm.",
      "distinguishing kaolinite from muscovite"),
    M("biotite", "Biotite mica", MINERAL, "silicate mineral", None,
      ["black biotite mica flakes", "dark brown biotite mineral"], "Dark mica that splits into thin sheets; Fe-Mg bearing.",
      "key mineral absorption features"),
    M("kaolinite", "Kaolinite (clay)", MINERAL, "clay mineral", None,
      ["white kaolin clay", "soft white kaolinite clay mineral", "chalky white clay lumps"],
      "Soft white clay. In SWIR: doublet near 2165 and 2205 nm and near 1395 and 1415 nm.",
      "distinguishing kaolinite from muscovite"),
    M("calcite", "Calcite", MINERAL, "carbonate mineral", None,
      ["calcite crystals", "rhombohedral calcite mineral", "white calcite specimen"],
      "Fizzes in dilute acid, hardness 3. In SWIR: carbonate feature near 2340 nm.", "key mineral absorption features"),
    M("dolomite", "Dolomite", MINERAL, "carbonate mineral", None,
      ["dolomite mineral crystals", "pinkish dolomite rock"],
      "Fizzes weakly in acid (powdered). In SWIR: carbonate feature near 2320 nm.", "key mineral absorption features"),
    M("gypsum", "Gypsum", MINERAL, "sulfate mineral", None,
      ["gypsum crystals", "selenite gypsum blades", "desert rose gypsum"],
      "Very soft (fingernail scratches it). Strong water features near 1450 and 1940 nm.", "key mineral absorption features"),
    M("halite", "Halite (rock salt)", MINERAL, "halide mineral", None,
      ["halite rock salt cubes", "cubic salt crystals"], "Salty taste, cubic cleavage, dissolves in water.", ""),
    M("fluorite", "Fluorite", MINERAL, "halide mineral", None,
      ["purple and green fluorite cubes", "fluorite crystals"], "Cubic crystals, hardness 4, often purple or green; may fluoresce.", ""),
    M("pyrite", "Pyrite (fool's gold)", MINERAL, "sulfide mineral", None,
      ["brassy gold pyrite cubes", "pyrite fool's gold crystals", "metallic yellow pyrite mineral"],
      "Brassy yellow metallic cubes, hardness 6, greenish-black streak. Iron sulfide; weathers to iron oxides.", ""),
    M("chalcopyrite", "Chalcopyrite (copper ore)", MINERAL, "sulfide mineral", None,
      ["chalcopyrite copper ore with brassy iridescent tarnish", "chalcopyrite mineral specimen"],
      "Main copper ore mineral: brassy yellow, softer than pyrite, often iridescent tarnish.", ""),
    M("galena", "Galena (lead ore)", MINERAL, "sulfide mineral", None,
      ["galena lead ore with silvery cubic crystals", "heavy grey metallic galena cubes"],
      "Lead sulfide: very heavy, silvery grey cubes with perfect cubic cleavage. Wash hands after handling.", "lead scrap"),
    M("sphalerite", "Sphalerite (zinc ore)", MINERAL, "sulfide mineral", None,
      ["sphalerite zinc ore", "resinous brown sphalerite crystals"], "Zinc sulfide: resinous lustre, brown to black.", "zinc"),
    M("malachite", "Malachite", MINERAL, "copper carbonate mineral", None,
      ["green banded malachite", "bright green malachite copper mineral"],
      "Banded bright-green copper carbonate; fizzes in acid. A copper ore and indicator mineral.", ""),
    M("azurite", "Azurite", MINERAL, "copper carbonate mineral", None,
      ["deep blue azurite crystals", "azurite copper mineral"], "Deep blue copper carbonate, often with malachite.", ""),
    M("native_copper", "Native copper (mineral)", MINERAL, "native element", None,
      ["native copper mineral specimen with dendritic shapes", "natural copper nugget in rock"],
      "Natural metallic copper in rock, often dendritic, with a green patina. It's an ore specimen, not processed scrap.",
      "copper scrap grades"),
    M("native_gold", "Gold (native)", MINERAL, "native element", None,
      ["a natural gold nugget", "gold flakes in quartz"], "Soft, heavy and malleable; does not tarnish. Pyrite is harder and brittle.",
      "precious metals"),
    M("hematite", "Hematite (iron ore)", MINERAL, "oxide mineral", None,
      ["hematite iron ore", "reddish-black hematite with red streak", "kidney ore hematite"],
      "Iron oxide with a red-brown streak. In VNIR: Fe3+ absorption near 860-880 nm.", "key mineral absorption features"),
    M("magnetite", "Magnetite (iron ore)", MINERAL, "oxide mineral", None,
      ["black magnetite iron ore", "magnetic black octahedral magnetite crystals"],
      "Black, strongly magnetic iron oxide with a black streak; a magnet picks it up.", "key mineral absorption features"),
    M("goethite", "Goethite / limonite", MINERAL, "oxide mineral", None,
      ["yellow-brown goethite limonite", "rusty brown iron hydroxide mineral"],
      "Yellow-brown iron hydroxide (rust-like). In VNIR: Fe3+ absorption near 900-930 nm.", "key mineral absorption features"),
    M("bauxite", "Bauxite (aluminium ore)", MINERAL, "ore", None,
      ["reddish bauxite aluminium ore", "pisolitic bauxite rock"], "Main aluminium ore: red-brown, earthy, often pisolitic.", ""),
    M("coal", "Coal", MINERAL, "fuel mineral", None,
      ["black coal lumps", "shiny black anthracite coal"], "Black, light for its size, burns; dusty. Not a metal ore.", ""),
    M("garnet", "Garnet", MINERAL, "silicate mineral", None,
      ["dark red garnet crystals", "garnet mineral in rock"], "Hard (6.5-7.5), dodecahedral red-brown crystals.", ""),
    M("olivine", "Olivine", MINERAL, "silicate mineral", None,
      ["olive green olivine crystals", "peridot olivine grains"], "Olive green, glassy; Fe2+ absorption near 1050 nm.",
      "key mineral absorption features"),
    M("talc", "Talc", MINERAL, "silicate mineral", None,
      ["soft white talc mineral", "greasy soapstone talc"], "Softest mineral (hardness 1), soapy feel. Mg-OH near 2310 nm.",
      "key mineral absorption features"),
    # ---------------------------------------------------------------------- rocks
    M("granite", "Granite", ROCK, "igneous rock", None,
      ["speckled granite rock", "pink and grey granite with crystals"], "Coarse igneous rock of quartz, feldspar and mica.", ""),
    M("basalt", "Basalt", ROCK, "igneous rock", None,
      ["dark grey basalt rock", "black volcanic basalt"], "Fine-grained dark volcanic rock; Fe2+ features near 1000 nm.", ""),
    M("obsidian", "Obsidian", ROCK, "volcanic glass", None,
      ["black shiny obsidian volcanic glass", "glassy black volcanic rock with sharp curved conchoidal fractures"], "Natural volcanic glass with conchoidal fracture.", ""),
    M("limestone", "Limestone", ROCK, "sedimentary rock", None,
      ["grey limestone rock", "fossil-bearing limestone"], "Mostly calcite: fizzes in acid; carbonate feature near 2340 nm.",
      "key mineral absorption features"),
    M("sandstone", "Sandstone", ROCK, "sedimentary rock", None,
      ["layered sandstone rock", "red sandstone"], "Cemented sand grains, mostly quartz; gritty feel.", ""),
    M("marble", "Marble", ROCK, "metamorphic rock", None,
      ["white marble stone", "polished veined marble"], "Metamorphosed limestone: fizzes in acid; crystalline sugary texture.", ""),
    M("slate", "Slate / shale", ROCK, "sedimentary rock", None,
      ["grey slate rock splitting into flat sheets", "dark shale rock"], "Fine-grained, splits into flat sheets; clay-mineral rich.", ""),
    M("ore_rock", "Ore-bearing rock", ROCK, "ore", None,
      ["mineral ore rock with metallic grains", "mining ore samples"],
      "Mineralised rock: confirm with assay or XRF; spectral scanning helps identify alteration minerals.", ""),
    # ----------------------------------------------------------------- not scrap
    M("not_scrap", "Not scrap or waste", NONE, "none", None,
      ["a photo of a person", "a landscape photo", "a photo of an animal", "a screenshot of text or a document",
       "a clean room interior"],
      "This doesn't look like scrap, waste or a mineral. Upload a clear photo of the material.", ""),
]

GROUP_ORDER = [METAL, MINERAL, ROCK, PLASTIC, GLASS, PAPER, ELEC, BATT, LAMP, AUTO, ORGANIC, BUILD, OTHER]


def catalogue_by_group() -> dict:
    """{group: [names]} for listing what ScrapTrust can identify."""
    out: dict = {g: [] for g in GROUP_ORDER}
    for m in MATERIALS:
        if m.group in out:
            out[m.group].append(m.name)
    return {g: names for g, names in out.items() if names}
