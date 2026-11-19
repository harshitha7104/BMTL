"""Evidence fusion: a ranked candidate system turning rule hypotheses, absorption
features, nearest spectra and cluster context into one defensible decision.

CANDIDATES ("units") come from four sources:
  1. rule engine   – composite rules that fired on the extracted features,
                     grouped when the engine cannot separate them (same deepest
                     absorption feature and rule scores within 0.10)
  2. features      – plausible rules that did NOT fire but whose required
                     species are partly matched by measured absorptions
  3. neighbours    – rule-based hypotheses (pseudo-labels, NOT ground truth)
                     carried by the most similar reference spectra
  4. cluster       – the same pseudo-labels within the query's cluster

EVIDENCE CONFIDENCE (0–1) — not a probability, not an accuracy. Same formula
as before, so a given hypothesis gets exactly the confidence it had before:

    EC = Q × (0.5·E + 0.3·N + 0.2·C)

    E  own-spectrum evidence
         fired rule:    rule_score × feature_strength
         partial match: 0.5 × rule_score × feature_strength × matched share of
                        required features (share < 1 by construction, so E <= 0.29
                        < 0.40: a partial match never counts as a spectral source)
         feature_strength = min(1, mean depth of matched features / 0.05)
    N  similarity-weighted mean of (Jaccard overlap with a neighbour's
       pseudo-label × feature match) over the 5 most similar reference spectra
       (one per rock, own rock excluded)
    C  mean Jaccard overlap with pseudo-labels in the query's cluster × mean
       neighbour feature match
    Q  quality factor (dark 0.8, novel/out-of-distribution 0.7, gaps 0.9)

SOURCES that "support" a candidate: spectral (E >= 0.40), neighbours
(N >= 0.50), cluster (C >= 0.50).

DECISION LEVELS (best eligible candidate by EC):
  INFERRED / HIGH      EC >= 0.45, >= 2 supporting sources, own-spectrum evidence E > 0
  INFERRED / MODERATE  spectral source alone (E >= 0.40), or >= 2 sources with
                       EC < 0.45 and E > 0 — reported with alternatives
  OBSERVED             absorptions >= 2 % deep, but no candidate qualifies
  UNKNOWN              no usable absorption, conflicting evidence, or failed QC
Eligible = plausible for a rock spectrum and spanning at most 3 chemical
families. A candidate with one rule and >= 2 supporting sources is a SPECIFIC
prediction; otherwise a mineral GROUP (named by chemical family) is reported
with its members ranked by member-level support.
Pseudo-labels alone can never produce an INFERRED result (E > 0 is required).
"""
from __future__ import annotations

from .analysis import Analysis
from .engine import load_engine
from .features import Feature

W_RULE, W_NEIGHBOUR, W_CLUSTER = 0.5, 0.3, 0.2
FEATURE_DEPTH_REF = 0.05      # a 5 % continuum-removed depth counts as clearly measured
AMBIGUITY_MARGIN = 0.10       # rules sharing their deepest feature and this close in score are grouped
STRONG_RULE = 0.40            # E needed to count as a spectral source / pseudo-label
AGREE_NEIGHBOUR = 0.50
AGREE_CLUSTER = 0.50
INFER_THRESHOLD = 0.45        # HIGH support (unchanged from the previous INFERRED threshold)
CONFLICT_SHARE = 0.60
PARTIAL_MATCH_FACTOR = 0.5    # partial (non-fired) rule evidence counts at most half
MAX_FAMILIES = 3              # a group spanning more chemical families is too broad to report
MIN_OBSERVED_DEPTH = 0.02     # the engine's own default min_band_depth
QUALITY_PENALTIES = {"low_albedo": 0.8, "out_of_distribution": 0.7, "interpolated_gaps": 0.9}

# The rule engine also covers vegetation, water, plastics, blood, urban
# materials and ice. For laboratory rock spectra those are not plausible
# interpretations; they are still reported, but never become the prediction.
PLAUSIBLE_CATEGORIES = {"mineral", "geological"}
CONTEXT_EXCLUDED = {"ice_snow": "ice is not plausible for a laboratory rock spectrum"}
HAZARD_CLASSES = {"crocidolite_asbestos", "chrysotile_asbestos"}

# Chemical family of each plausible engine rule, from the absorbing species the
# rule requires (see COMPOSITE_RULES / SPECTRAL_FEATURES_DB). Used to name groups.
RULE_FAMILY = {
    "calcite": "Carbonate", "dolomite": "Carbonate", "ankerite": "Carbonate", "siderite": "Carbonate",
    "talc": "Mg-OH silicate", "serpentinite": "Mg-OH silicate", "chrysotile_asbestos": "Mg-OH silicate",
    "crocidolite_asbestos": "Fe-OH amphibole",
    "kaolinite": "Al-OH clay/mica", "smectite_montmorillonite": "Al-OH clay/mica",
    "muscovite_illite": "Al-OH clay/mica", "halloysite": "Al-OH clay/mica", "pyrophyllite": "Al-OH clay/mica",
    "advanced_argillic_alteration": "Al-OH clay/mica",
    "gibbsite_laterite": "Al hydroxide", "boehmite_bauxite": "Al hydroxide",
    "hematite_iron_oxide": "Fe oxide/oxyhydroxide", "goethite": "Fe oxide/oxyhydroxide",
    "ferrihydrite": "Fe oxide/oxyhydroxide", "lepidocrocite_soil": "Fe oxide/oxyhydroxide",
    "acid_mine_drainage": "Fe oxide/oxyhydroxide",
    "olivine": "Fe2+ silicate", "pyroxene_orthopyroxene": "Fe2+ silicate",
    "gypsum_evaporite": "Sulphate", "epsomite": "Sulphate", "kieserite": "Sulphate", "szomolnokite": "Sulphate",
    "neodymium_REE": "REE", "REE_erbium": "REE", "REE_dysprosium": "REE", "REE_ytterbium": "REE",
    "REE_holmium": "REE",
    "propylitic_alteration": "Epidote/chlorite", "prehnite": "Ca-Al silicate",
    "schorl_tourmaline": "Borosilicate", "coal": "Organic (coal)",
}


def members_of(label) -> set[str]:
    """Rule names in a hypothesis label ('a / b'). Missing labels (None/NaN) -> empty set."""
    return set(label.split(" / ")) if isinstance(label, str) and label else set()


def jaccard(a, b) -> float:
    """Overlap of two hypothesis labels (0 = disjoint, 1 = identical rule sets)."""
    ma, mb = members_of(a), members_of(b)
    return len(ma & mb) / len(ma | mb) if ma and mb else 0.0


def family_of(rule: str) -> str:
    return RULE_FAMILY.get(rule, "Other")


def supporting_features(rule_name: str, features: list[Feature]) -> list[dict]:
    """Features whose centre falls in a database range of the rule's required species."""
    eng = load_engine()
    rule = next(r for r in eng.COMPOSITE_RULES if r["name"] == rule_name)
    out = []
    for sp in sorted(set(rule["required_species"])):
        ranges = [e["range"] for e in eng.SPECTRAL_FEATURES_DB if e["species"] == sp]
        for f in features:
            if f.depth >= MIN_OBSERVED_DEPTH and any(lo <= f.center_nm <= hi for lo, hi in ranges):
                out.append({"species": sp, "center_nm": f.center_nm, "depth": round(f.depth, 4),
                            "fwhm_nm": round(f.fwhm_nm, 1)})
    return out


def _plausibility(name: str, category: str) -> tuple[bool, str]:
    if category not in PLAUSIBLE_CATEGORIES:
        return False, f"category '{category}' is not a rock/mineral interpretation"
    if name in CONTEXT_EXCLUDED:
        return False, CONTEXT_EXCLUDED[name]
    return True, ""


def rule_candidates(analysis: Analysis) -> list[dict]:
    """Composite-rule hypotheses with plausibility, feature strength, R and competitors; best first."""
    cands = []
    for h in analysis.rules.hypotheses:
        if h["kind"] != "composite_rule":
            continue
        plausible, reason = _plausibility(h["name"], h["category"])
        support = supporting_features(h["name"], analysis.features)
        depth = sum(s["depth"] for s in support) / len(support) if support else 0.0
        cands.append({"name": h["name"], "category": h["category"], "rule_score": h["rule_score"],
                      "plausible": plausible, "excluded_reason": reason, "supporting_features": support,
                      "deepest_feature_nm": max(support, key=lambda s: s["depth"])["center_nm"] if support else None,
                      "feature_strength": round(min(1.0, depth / FEATURE_DEPTH_REF), 3)})
    for c in cands:
        c["R"] = round(c["rule_score"] * c["feature_strength"], 3) if c["plausible"] else 0.0
        c["competing"] = [o["name"] for o in cands
                          if o is not c and o["plausible"] and c["plausible"]
                          and o["deepest_feature_nm"] is not None
                          and o["deepest_feature_nm"] == c["deepest_feature_nm"]
                          and abs(o["rule_score"] - c["rule_score"]) < AMBIGUITY_MARGIN]
    return sorted(cands, key=lambda c: (c["plausible"], c["R"], c["rule_score"]), reverse=True)


def hypothesis_groups(cands: list[dict]) -> list[dict]:
    """Greedy grouping of plausible rules the evidence cannot separate. Best first."""
    groups, used = [], set()
    for c in cands:
        if not c["plausible"] or c["R"] <= 0 or c["name"] in used:
            continue
        members = [c["name"]] + [n for n in c["competing"] if n not in used]
        used.update(members)
        groups.append({"label": " / ".join(members), "members": members, "best_rule": c["name"],
                       "rule_score": c["rule_score"], "R": c["R"], "shared_feature_nm": c["deepest_feature_nm"]})
    return groups


def rule_hypothesis(cands: list[dict]) -> tuple[str | None, float]:
    """Strong rule-based hypothesis group (used as a pseudo-label), or (None, best R)."""
    groups = hypothesis_groups(cands)
    if groups and groups[0]["R"] >= STRONG_RULE:
        return groups[0]["label"], groups[0]["R"]
    return None, (groups[0]["R"] if groups else 0.0)


def partial_feature_candidates(analysis: Analysis, fired: set[str]) -> list[dict]:
    """Plausible rules that did not fire but whose required species are partly
    matched by measured absorptions. Evidence is discounted (see module doc)."""
    out = []
    for rule in load_engine().COMPOSITE_RULES:
        name = rule["name"]
        if name in fired or not _plausibility(name, rule["category"])[0]:
            continue
        support = supporting_features(name, analysis.features)
        if not support:
            continue
        # Share of required feature occurrences that are matched (a rule may require
        # the same species twice, e.g. a doublet).
        required = rule["required_species"]
        matched = sum(min(sum(s["species"] == sp for s in support), required.count(sp)) for sp in set(required))
        share = matched / len(required)
        if share >= 1.0:
            # Fully matched but not fired: the engine rejected it (required-absent species
            # or vegetation gate). Respect that decision rather than re-admitting it.
            continue
        depth = sum(s["depth"] for s in support) / len(support)
        strength = min(1.0, depth / FEATURE_DEPTH_REF)
        out.append({"name": name, "category": rule["category"], "rule_score": rule["base_score"],
                    "matched_share": round(share, 3), "feature_strength": round(strength, 3),
                    "supporting_features": support,
                    "E": round(PARTIAL_MATCH_FACTOR * rule["base_score"] * strength * share, 3)})
    return sorted(out, key=lambda c: c["E"], reverse=True)


def _share(items: list[tuple[str | None, float, float]], label: str) -> float:
    total = sum(w for _, w, _ in items)
    return sum(w * jaccard(lab, label) * fm for lab, w, fm in items) / total if total > 0 else 0.0


def group_name(members: list[str]) -> str:
    fams = list(dict.fromkeys(family_of(m) for m in members))
    return f"{' / '.join(fams)} mineral group"


def rank_candidates(analysis: Analysis, cands: list[dict], neighbours: list[dict], cluster_labels: list,
                    quality_factors: dict[str, float]) -> dict:
    """Build, score and rank all candidate units, then decide. Returns the decision fields."""
    q = 1.0
    for v in quality_factors.values():
        q *= v
    neigh_items = [(n["rule_hypothesis"], max(n["similarity"], 0.0), n["feature_match"]) for n in neighbours]
    labelled_cluster = [lab for lab in cluster_labels if members_of(lab)]
    represented = sum(n["feature_match"] for n in neighbours) / len(neighbours) if neighbours else 0.0

    def score(label: str, e: float) -> dict:
        n = _share(neigh_items, label)
        c = (represented * sum(jaccard(lab, label) for lab in labelled_cluster) / len(labelled_cluster)
             if len(labelled_cluster) >= 3 else 0.0)
        ec = q * (W_RULE * e + W_NEIGHBOUR * n + W_CLUSTER * c)
        agree = {"spectral": e >= STRONG_RULE, "neighbours": n >= AGREE_NEIGHBOUR, "cluster": c >= AGREE_CLUSTER}
        return {"E": round(e, 3), "N": round(n, 3), "C": round(c, 3), "Q": round(q, 3),
                "evidence_confidence": round(ec, 3), "supporting_sources": [k for k, v in agree.items() if v]}

    by_name = {c["name"]: c for c in cands}
    units = []
    # 1. rule-engine groups
    for g in hypothesis_groups(cands):
        units.append({"label": g["label"], "members": g["members"], "origin": "rule engine",
                      "shared_feature_nm": g["shared_feature_nm"], **score(g["label"], g["R"])})
    fired = {c["name"] for c in cands}
    covered = set().union(*(set(u["members"]) for u in units)) if units else set()
    # 2. partially matched rules (absorption features only)
    partial = partial_feature_candidates(analysis, fired)
    for p in partial[:5]:
        units.append({"label": p["name"], "members": [p["name"]], "origin": "absorption features (partial match)",
                      "shared_feature_nm": None, **score(p["name"], p["E"])})
    covered |= {p["name"] for p in partial[:5]}
    # 3. neighbour pseudo-labels not covered by the spectrum's own evidence (E = 0)
    for lab in sorted({lab for lab, _, _ in neigh_items if members_of(lab)}):
        if not members_of(lab) & covered:
            units.append({"label": lab, "members": lab.split(" / "), "origin": "similar reference spectra",
                          "shared_feature_nm": None, **score(lab, 0.0)})
    for u in units:
        u["families"] = list(dict.fromkeys(family_of(m) for m in u["members"]))
        u["kind"] = "specific" if len(u["members"]) == 1 else "group"
        u["name"] = u["members"][0] if u["kind"] == "specific" else group_name(u["members"])
        u["eligible"] = len(u["families"]) <= MAX_FAMILIES
        # Rank members inside a group by their own (member-level) support. Ranking only.
        u["member_ranking"] = sorted(
            ({"rule": m, "family": family_of(m), "rule_score": by_name[m]["rule_score"] if m in by_name else None,
              **{k: v for k, v in score(m, by_name[m]["R"] if m in by_name else 0.0).items()
                 if k in ("E", "N", "C", "evidence_confidence")}} for m in u["members"]),
            key=lambda r: r["evidence_confidence"], reverse=True)
    units.sort(key=lambda u: (u["evidence_confidence"], -len(u["members"])), reverse=True)

    observed = [f for f in analysis.features if f.depth >= MIN_OBSERVED_DEPTH]
    eligible = [u for u in units if u["eligible"]]
    decision = {"prediction_type": "UNKNOWN", "support_level": None, "prediction_kind": None,
                "prediction": "UNKNOWN", "unit": eligible[0] if eligible else None,
                "alternatives": [u for u in units if u is not (eligible[0] if eligible else None)][:4],
                "candidates": units, "reason": ""}
    if not observed and not eligible:
        decision["reason"] = "no absorption feature deeper than 2 % of the continuum"
        return decision

    if eligible:
        top = eligible[0]
        rival = next((o for o in eligible[1:] if o["N"] >= CONFLICT_SHARE and o["N"] > top["N"] + 0.3
                      and jaccard(o["label"], top["label"]) < 0.5), None)
        if rival:
            decision["reason"] = (f"conflicting evidence: the spectrum's own evidence favours {top['label']} but "
                                  f"the most similar reference spectra mostly carry {rival['label']}")
            return decision
        n_src = len(top["supporting_sources"])
        own = top["E"] > 0
        level = None
        if own and n_src >= 2 and top["evidence_confidence"] >= INFER_THRESHOLD:
            level = "HIGH"
            reason = f"{' + '.join(top['supporting_sources'])} support it (evidence confidence ≥ {INFER_THRESHOLD})"
        elif own and ("spectral" in top["supporting_sources"] or n_src >= 2):
            level = "MODERATE"
            reason = (f"supported by {' + '.join(top['supporting_sources'])}"
                      + ("" if n_src >= 2 else " only; similar reference spectra / cluster do not confirm it")
                      + "; alternatives shown")
        if level:
            kind, name = top["kind"], top["name"]
            if kind == "specific" and n_src < 2:
                # A specific mineral needs independent support; with one source only the
                # chemical family of the rule is claimed (the rule stays the ranked member).
                kind, name = "group", group_name(top["members"])
                reason += "; a specific mineral needs ≥ 2 independent sources, so only its family is claimed"
            decision.update(prediction_type="INFERRED", support_level=level, prediction_kind=kind,
                            prediction=name, reason=reason)
            return decision

    if not observed:
        decision["reason"] = "no own-spectrum absorption ≥ 2 %; similar spectra alone are not evidence"
        return decision
    broad = [u for u in units if not u["eligible"]]
    decision.update(prediction_type="OBSERVED",
                    prediction="No mineral inferred; absorptions observed at " +
                               ", ".join(f"{f.center_nm:.0f} nm" for f in observed[:4]),
                    reason=("the candidates span more than 3 chemical families" if broad and not eligible else
                            "no candidate has own-spectrum rule evidence (E ≥ 0.40) or two agreeing sources"))
    return decision
