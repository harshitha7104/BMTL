"""Inference: one spectrum in, one structured, evidence-labelled result out.

    from src.predict import predict_spectrum
    result = predict_spectrum(wavelengths, reflectance)   # µm or nm, auto-detected
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .analysis import Analysis, analyse_spectrum
from .data_loader import convert_wavelength_units, infer_wavelength_unit, load_spectra, parse_sample_name
from .engine import rule_info
from .fusion import (HAZARD_CLASSES, MIN_OBSERVED_DEPTH, QUALITY_PENALTIES, jaccard, members_of,
                     rank_candidates, rule_candidates)
from .model import load_model, normalise_rows, preprocess_config_from, reconstruction_error

log = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "spectral_model.joblib"
N_NEIGHBOURS = 5
FEATURE_MATCH_NM = 15.0
FEATURE_MATCH_MIN_DEPTH = 0.03
NOVEL_FEATURE_MATCH = 0.5

CONFIDENCE_DEFINITION = (
    "Evidence confidence (0–1) = Q × (0.5·E + 0.3·N + 0.2·C): E = own-spectrum rule evidence (rule score × feature "
    "strength; partial matches count at most half), "
    "N = agreement of the most similar reference spectra, C = agreement within the cluster, Q = quality penalties. "
    "It summarises how consistently the implemented evidence sources point to one hypothesis. "
    "It is NOT a probability and NOT a measured accuracy — there is no ground truth to calibrate it.")


class Predictor:
    def __init__(self, model: dict | None = None, model_path: Path = DEFAULT_MODEL_PATH):
        self.model = model or load_model(model_path)
        self.cfg = preprocess_config_from(self.model)
        self.ref = self.model["reference"]
        self.ref_unit = normalise_rows(self.model["reference_embeddings"])
        self.ref_rock = self.ref["rock_id"].fillna(self.ref["sample"]).to_numpy()

    # -- model lookups -------------------------------------------------------------
    def embed(self, analysis: Analysis) -> np.ndarray:
        return self.model["pca"].transform(analysis.vector[None, :])[0]

    @staticmethod
    def feature_match(query: Analysis, ref_features: list) -> float:
        """Depth-weighted share of the query's absorptions (>=3 %) present within ±15 nm in a reference spectrum."""
        q = [(f.center_nm, f.depth) for f in query.features if f.depth >= FEATURE_MATCH_MIN_DEPTH]
        if not q:
            return 1.0
        centres = np.array([c for c, _ in ref_features]) if ref_features else np.array([])
        hit = sum(d for c, d in q if centres.size and np.min(np.abs(centres - c)) <= FEATURE_MATCH_NM)
        return round(hit / sum(d for _, d in q), 3)

    def neighbours(self, z: np.ndarray, exclude_rock: str | None, k: int = N_NEIGHBOURS,
                   query: Analysis | None = None) -> list[dict]:
        """Most similar reference spectra, best one per rock (replicates are not independent)."""
        sims = self.ref_unit @ normalise_rows(z)
        out, seen = [], set()
        for i in np.argsort(-sims):
            rock = self.ref_rock[i]
            if rock == exclude_rock or rock in seen:
                continue
            seen.add(rock)
            row = self.ref.iloc[i]
            lab = row["rule_hypothesis"]
            out.append({"sample": row["sample"], "rock_id": rock, "similarity": round(float(sims[i]), 4),
                        "feature_match": self.feature_match(query, row["features"]) if query else 1.0,
                        "cluster": int(row["cluster"]), "rule_hypothesis": lab if isinstance(lab, str) else None})
            if len(out) == k:
                break
        return out

    def cluster_context(self, cluster: int, exclude_rock: str | None) -> dict:
        members = self.ref[(self.ref["cluster"] == cluster) & (self.ref_rock != exclude_rock)]
        counts = members["rule_hypothesis"].value_counts().to_dict()
        return {"cluster": int(cluster), "n_members": int(len(members)),
                "n_rocks": int(members["rock_id"].nunique()),
                "rule_hypothesis_counts": {k: int(v) for k, v in counts.items()},
                "labels": members["rule_hypothesis"].tolist()}

    # -- main entry point ---------------------------------------------------------------
    def predict(self, wavelengths, reflectance, wavelength_unit: str = "auto",
                sample_name: str | None = None, exclude_rock: str | None = None) -> dict:
        wl = np.asarray(wavelengths, dtype=float)
        if wavelength_unit == "auto":
            wavelength_unit, _ = infer_wavelength_unit(wl[np.isfinite(wl)])
        wl_nm = convert_wavelength_units(wl, wavelength_unit)

        analysis = analyse_spectrum(wl_nm, np.asarray(reflectance, dtype=float), self.cfg)
        warnings = [f"[{sev}] {check}: {detail}" for check, sev, _, _, detail in analysis.quality_flags]
        warnings += analysis.notes + analysis.rules.flags
        if any(f[1] == "ERROR" for f in analysis.quality_flags if f[0] != "non_finite_values"):
            return self._unusable(sample_name, analysis, warnings)

        z = self.embed(analysis)
        cluster = int(self.model["kmeans"].predict(z[None, :])[0])
        neigh = self.neighbours(z, exclude_rock, query=analysis)
        ctx = self.cluster_context(cluster, exclude_rock)

        qf = {}
        if analysis.has_flag("low_albedo"):
            qf["low_albedo"] = QUALITY_PENALTIES["low_albedo"]
        top_sim = neigh[0]["similarity"] if neigh else -1.0
        if top_sim < self.model["ood_similarity_threshold"]:
            qf["out_of_distribution"] = QUALITY_PENALTIES["out_of_distribution"]
            warnings.append(f"Spectrum is less similar to any reference rock ({top_sim:.3f}) than "
                            f"95 % of reference spectra are to theirs ({self.model['ood_similarity_threshold']:.3f}).")
        recon = float(reconstruction_error(self.model["pca"], analysis.vector)[0])
        match = float(np.mean([n["feature_match"] for n in neigh])) if neigh else 0.0
        if match < NOVEL_FEATURE_MATCH or recon > self.model["reconstruction_error_threshold"]:
            qf["out_of_distribution"] = QUALITY_PENALTIES["out_of_distribution"]
            warnings.append(f"Novel spectrum: only {100 * match:.0f} % of its absorption depth is found in the most "
                            f"similar reference spectra (PCA reconstruction error {recon:.4f}, reference 99th "
                            f"percentile {self.model['reconstruction_error_threshold']:.4f}). Similarity and cluster "
                            "evidence are down-weighted accordingly.")
        if any("bridged" in n for n in analysis.notes):
            qf["interpolated_gaps"] = QUALITY_PENALTIES["interpolated_gaps"]

        cands = rule_candidates(analysis)
        dec = rank_candidates(analysis, cands, neigh, ctx["labels"], qf)
        unit = dec["unit"] or {}
        members = set(unit.get("members", [])) if dec["prediction_type"] == "INFERRED" else set()
        hazards = members & HAZARD_CLASSES
        if hazards:
            warnings.append(f"{', '.join(sorted(hazards))}: hazard class proposed by spectral rules only; it must be "
                            "confirmed by mineralogical analysis (e.g. XRD, microscopy) before any safety decision.")
        if dec["support_level"] == "MODERATE":
            warnings.append("Moderate support: treat as a candidate interpretation and check the alternatives.")
        if dec["prediction_type"] == "INFERRED" and dec["alternatives"]:
            alt = dec["alternatives"][0]
            if unit["evidence_confidence"] - alt["evidence_confidence"] < 0.03:
                warnings.append(f"Near-tie: alternative '{alt['name']}' ({alt['label']}) has almost the same "
                                f"evidence confidence ({alt['evidence_confidence']:.2f}).")
        best_rule = next((c for c in cands if unit and c["name"] in unit.get("members", [])), None)
        support = best_rule["supporting_features"] if best_rule else []

        result = {
            "sample": sample_name,
            "prediction": dec["prediction"],
            "prediction_type": dec["prediction_type"],
            "support_level": dec["support_level"],
            "prediction_kind": dec["prediction_kind"],
            "group_members": unit.get("member_ranking", []) if dec["prediction_kind"] == "group" else [],
            # For OBSERVED/UNKNOWN this is the (non-qualifying) confidence of the best candidate.
            "confidence": unit.get("evidence_confidence", 0.0),
            "confidence_label": "Evidence confidence (not a probability)",
            "confidence_definition": CONFIDENCE_DEFINITION,
            "rule_score": best_rule["rule_score"] if best_rule else None,
            "evidence_sources": unit.get("supporting_sources", []),
            "evidence_components": ({k: unit.get(k) for k in ("label", "E", "N", "C", "Q", "evidence_confidence")}
                                    if unit else {}),
            "alternatives": [{k: a[k] for k in ("name", "label", "kind", "origin", "evidence_confidence",
                                                 "supporting_sources", "E", "N", "C")} for a in dec["alternatives"]],
            "key_features": [f.to_dict() for f in analysis.features if f.depth >= MIN_OBSERVED_DEPTH][:6],
            "prediction_features_nm": sorted({s["center_nm"] for s in support}),
            "cluster": {k: v for k, v in ctx.items() if k != "labels"},
            "similar_samples": neigh,
            "spectral_features": [f.to_dict() for f in analysis.features],
            "rule_evidence": cands,
            "rule_engine_dominant_class": analysis.rules.dominant_class,
            "chromophores": analysis.rules.chromophores[:12],
            "warnings": warnings,
            "decision_reason": dec["reason"],
        }
        result["why"] = self._why(result, unit, best_rule, neigh, ctx, qf)
        result["evidence"] = self._evidence_tree(analysis, result, cands)
        result["explanation"] = self._explain(result, unit)
        result["_analysis"] = analysis  # for plotting; dropped by to_serialisable()
        return result

    # -- helpers ----------------------------------------------------------------------------
    def _unusable(self, sample_name, analysis, warnings) -> dict:
        return {"sample": sample_name, "prediction": "UNKNOWN", "prediction_type": "UNKNOWN",
                "support_level": None, "prediction_kind": None, "group_members": [], "confidence": 0.0,
                "confidence_label": "Evidence confidence (not a probability)",
                "confidence_definition": CONFIDENCE_DEFINITION, "rule_score": None, "evidence_sources": [],
                "evidence_components": {}, "alternatives": [], "key_features": [], "prediction_features_nm": [],
                "cluster": None, "similar_samples": [], "spectral_features": [], "rule_evidence": [],
                "rule_engine_dominant_class": None, "chromophores": [], "warnings": warnings,
                "decision_reason": "spectrum failed quality checks",
                "why": [{"source": "Quality checks", "value": None, "contributed": False,
                         "detail": "The spectrum failed basic quality checks; no evidence was evaluated."}],
                "evidence": {"observed": [], "inferred": [], "unknown": ["Spectrum is unusable (see warnings)."]},
                "explanation": "The spectrum failed basic quality checks, so no interpretation was attempted.",
                "_analysis": analysis}

    @staticmethod
    def _why(r: dict, unit: dict, best_rule: dict | None, neigh: list[dict], ctx: dict, qf: dict) -> list[dict]:
        """Exactly which evidence sources contributed to the reported candidate."""
        if not unit:
            return [{"source": "Candidates", "value": None, "contributed": False,
                     "detail": "No candidate could be formed."}]
        label = unit["label"]
        out = []
        if unit["origin"] == "rule engine" and best_rule:
            rule = rule_info(best_rule["name"]) or {}
            wls = ", ".join(f"{s['species']} at {s['center_nm']:.0f} nm ({100 * s['depth']:.1f} %)"
                            for s in best_rule["supporting_features"]) or "none deeper than 2 %"
            out.append({"source": "Rule engine on own spectrum (E)", "value": unit["E"],
                        "contributed": "spectral" in unit["supporting_sources"],
                        "detail": f"'{best_rule['name']}' fired, rule score {best_rule['rule_score']:.2f} "
                                  f"(rule: {rule.get('notes', 'n/a')}); matched absorptions: {wls}; feature "
                                  f"strength {best_rule['feature_strength']:.2f}."})
        elif unit["origin"].startswith("absorption"):
            out.append({"source": "Absorption features, partial rule match (E)", "value": unit["E"],
                        "contributed": False,
                        "detail": "Some required absorptions of this rule are present but the rule did not fire; "
                                  "counted at most half."})
        else:
            out.append({"source": "Own spectrum (E)", "value": 0.0, "contributed": False,
                        "detail": "No own-spectrum rule evidence for this candidate."})
        if len(unit["members"]) > 1:
            out.append({"source": "Engine distinguishability", "value": None, "contributed": False,
                        "detail": f"{len(unit['members'])} rules rest on the same deepest absorption "
                                  f"({unit['shared_feature_nm']:.0f} nm) with rule scores within 0.10; the engine "
                                  "cannot separate them, so a group is reported. Member order uses member-level "
                                  "support and is not an identification."})
        backers = [f"{n['sample']} (sim {n['similarity']:.3f}, feature match {n['feature_match']:.2f}, "
                   f"pseudo-label {n['rule_hypothesis']})" for n in neigh if jaccard(n["rule_hypothesis"], label) > 0]
        out.append({"source": "Similar reference spectra (N)", "value": unit["N"],
                    "contributed": "neighbours" in unit["supporting_sources"],
                    "detail": ("Supporting: " + "; ".join(backers)) if backers else
                              "None of the most similar reference spectra carries this hypothesis."})
        out.append({"source": "Cluster context (C)", "value": unit["C"],
                    "contributed": "cluster" in unit["supporting_sources"],
                    "detail": f"Cluster {ctx['cluster']}: {ctx['n_members']} reference spectra from {ctx['n_rocks']} "
                              "rocks (own rock excluded); agreement = Jaccard overlap of pseudo-labels."})
        out.append({"source": "Quality factor (Q)", "value": unit["Q"], "contributed": None,
                    "detail": ", ".join(f"{k} ×{v}" for k, v in qf.items()) or "no penalties"})
        level = f" / {r['support_level']}" if r["support_level"] else ""
        out.append({"source": "Decision rule", "value": r["confidence"], "contributed": None,
                    "detail": f"{r['prediction_type']}{level}: {r['decision_reason']}. Pseudo-labels of reference "
                              "spectra are rule-based hypotheses, not ground truth."})
        return out

    @staticmethod
    def _evidence_tree(analysis: Analysis, r: dict, cands: list[dict]) -> dict:
        observed = [f"Absorption at {f.center_nm:.0f} nm: depth {100 * f.depth:.1f} % below continuum, "
                    f"FWHM {f.fwhm_nm:.0f} nm ({f.region})" + (" — truncated at range edge" if f.edge_truncated else "")
                    for f in analysis.features if f.depth >= MIN_OBSERVED_DEPTH]
        refl = analysis.processed.reflectance
        observed.insert(0, f"Reflectance {refl.min():.3f}–{refl.max():.3f} over 400–2500 nm")
        inferred, unknown = [], []
        claimed = {m["rule"] for m in r["group_members"]} or members_of(r["prediction"])
        if r["prediction_type"] == "INFERRED":
            inferred.append(f"{r['prediction']} — {r['support_level']} support, evidence confidence "
                            f"{r['confidence']:.2f}; sources: {', '.join(r['evidence_sources']) or 'none'}")
            if r["group_members"]:
                inferred.append("Ranked members (not individually identified): " +
                                ", ".join(m["rule"] for m in r["group_members"]))
        for c in cands:
            if not c["plausible"]:
                unknown.append(f"{c['name']} (rule score {c['rule_score']:.2f}) not considered: {c['excluded_reason']}")
            elif r["prediction_type"] != "INFERRED" or c["name"] not in claimed:
                unknown.append(f"{c['name']}: rule fired (rule score {c['rule_score']:.2f}) but is not the "
                               "best-supported candidate")
        if r["prediction_type"] != "INFERRED":
            unknown.insert(0, "Mineral identity: insufficient or conflicting evidence")
        elif r["prediction_kind"] == "group":
            unknown.insert(0, "Which member of the group is present: the rule evidence cannot separate them")
        unknown.append("Ground truth: not available — no prediction here has been validated against labels")
        return {"observed": observed, "inferred": inferred, "unknown": unknown}

    @staticmethod
    def _explain(r: dict, unit: dict) -> str:
        if r["prediction_type"] == "INFERRED":
            what = "mineral group" if r["prediction_kind"] == "group" else "mineral/material"
            text = (f"The best-supported {what} is **{r['prediction']}** ({r['support_level']} support, evidence "
                    f"confidence {r['confidence']:.2f}).")
            if r["group_members"]:
                text += " Ranked members: " + ", ".join(
                    f"{i + 1}. {m['rule']}" for i, m in enumerate(r["group_members"][:3])) + "."
        elif r["prediction_type"] == "OBSERVED":
            text = "Absorption features were measured, but no mineral candidate is defensible."
            if unit:
                text += (f" Best candidate (not claimed): {unit['name']} ({unit['label']}), evidence confidence "
                         f"{unit['evidence_confidence']:.2f}.")
        else:
            text = "No interpretation could be supported."
        return text + f" Decision: {r['decision_reason']}."


_default: Predictor | None = None


def get_predictor(model_path: Path = DEFAULT_MODEL_PATH) -> Predictor:
    global _default
    if _default is None:
        _default = Predictor(model_path=model_path)
    return _default


def predict_spectrum(wavelengths, reflectance, wavelength_unit: str = "auto", sample_name: str | None = None,
                     exclude_rock: str | None = None) -> dict:
    """Predict one spectrum with the saved model (see Predictor.predict)."""
    return get_predictor().predict(wavelengths, reflectance, wavelength_unit, sample_name, exclude_rock)


def predict_file(path, predictor: Predictor | None = None, leave_rock_out: bool = False) -> list[dict]:
    """Predict every spectrum column in a CSV/XLSX file (first column = wavelength).

    leave_rock_out=True excludes each sample's own rock from the similarity
    evidence — use it when the file is the reference dataset itself."""
    predictor = predictor or get_predictor()
    ds = load_spectra(path)
    results = []
    for i, name in enumerate(ds.sample_names):
        rock = parse_sample_name(name)["rock_id"] if leave_rock_out else None
        results.append(predictor.predict(ds.wavelength_nm, ds.reflectance[i], "nm", name, rock or (name if leave_rock_out else None)))
    return results


def to_serialisable(result: dict) -> dict:
    return {k: v for k, v in result.items() if not k.startswith("_")}
