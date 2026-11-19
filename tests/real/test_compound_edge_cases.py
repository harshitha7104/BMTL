"""Compound naming must never crash on unusual but real inputs (found by the 2026-11-18 bug sweep: one row of an
ICP workbook had Fe but zero Ni, Mn, Co and P -> ZeroDivisionError, and the whole sheet failed)."""
from __future__ import annotations

from src.realmodels.compound import name_compound


def test_iron_only_with_zero_phosphorus_does_not_crash():
    out = name_compound({"Fe": 5.0, "P": 0.0, "Ni": 0.0, "Mn": 0.0, "Co": 0.0}, "NMC")
    assert out["state"] in ("UNKNOWN", "INFERRED") and "basis" in out


def test_all_zero_is_unknown():
    assert name_compound({"Ni": 0.0, "Co": 0.0, "Mn": 0.0, "Fe": 0.0}, "NMC")["state"] == "UNKNOWN"


def test_uncertainty_line_read_twice_is_never_a_value():
    """2026-11-18 photo sweep: one OCR pass read '± 0.04', the other read the same line as '0.04'; the Cu tile was
    then paired with 0.04 instead of its real value (3.84 on the photo)."""
    from src.realdata.extract import pair_ocr_boxes

    h = 1000.0
    boxes = [(100, 520, "Cu", 0.9), (200, 545, "± 0.04", 0.9), (201, 546, "0.04", 0.8)]
    assert "Cu" not in pair_ocr_boxes(boxes, h)["values"]            # nothing real to pair with: stays unread
    boxes.append((200, 505, "3.84 %", 0.95))
    assert pair_ocr_boxes(boxes, h)["values"]["Cu"] == 3.84
