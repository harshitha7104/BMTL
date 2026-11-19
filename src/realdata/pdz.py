"""Reader for Bruker S1 TITAN `.pdz` files (pdz25 record format).

PROVENANCE: real instrument files from the ACE Bruker XRF trial (S1 TITAN 800,
26 Oct 2026, `data/raw/ace_company/bruker_s1titan/pdz_90s/`).

The format was reverse-read from the files themselves and checked against the
printed report (`Instrument Results.pdf`):
  record = uint16 type, uint32 length, payload
  type 1   instrument (UTF-16 serial number etc.)
  type 3   one excitation phase: uint32 phase index, header floats (incl. kV, uA),
           then 2048 uint32 channel counts
  type 6   one element/compound result: name, Z, then three float32:
           [0] factory-calibration value (%), [1] type-standardised value (%),
           [2] 1-sigma uncertainty (%). [1] equals the value on the printed report and
           in Results.csv; the report's "+-2s" column is 2 x [2].
Values reported as 0 with a non-zero uncertainty are "< LOD" on the report.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

N_CHANNELS = 2048


@dataclass
class PdzPhase:
    index: int
    kv: float
    ua: float
    header_floats: list[float]
    counts: np.ndarray


@dataclass
class PdzElement:
    name: str
    z: int
    factory_pct: float
    standardised_pct: float
    sigma_pct: float

    @property
    def below_lod(self) -> bool:
        return self.standardised_pct == 0.0


@dataclass
class PdzFile:
    path: Path
    serial: str | None
    phases: list[PdzPhase] = field(default_factory=list)
    elements: dict[str, PdzElement] = field(default_factory=dict)
    strings: list[str] = field(default_factory=list)


def _utf16(payload: bytes, offset: int) -> tuple[str, int]:
    n = struct.unpack_from("<I", payload, offset)[0]
    start = offset + 4
    return payload[start:start + 2 * n].decode("utf-16-le", errors="replace"), start + 2 * n


def read_pdz(path: str | Path) -> PdzFile:
    path = Path(path)
    data = path.read_bytes()
    if data[6:16].decode("utf-16-le", errors="replace") != "pdz25":
        raise ValueError(f"{path.name}: not a pdz25 file")
    result = PdzFile(path=path, serial=None)
    offset = 0
    while offset + 6 <= len(data):
        rtype, length = struct.unpack_from("<HI", data, offset)
        payload = data[offset + 6: offset + 6 + length]
        if len(payload) != length:
            break
        if rtype == 1:
            result.serial, _ = _utf16(payload, 0)
        elif rtype == 3 and length == 144 + 4 * N_CHANNELS:
            header = payload[:144]
            floats = list(struct.unpack_from("<34f", header, 8))
            counts = np.frombuffer(payload[144:], dtype="<u4").astype(np.int64)
            index = struct.unpack_from("<I", header, 0)[0]
            # kV / uA sit at header bytes 40 and 44 (verified against the printed excitation table)
            kv, ua = struct.unpack_from("<2f", header, 40)
            result.phases.append(PdzPhase(index=index, kv=round(kv, 3), ua=round(ua, 3), header_floats=floats, counts=counts))
        elif rtype == 6:
            name, pos = _utf16(payload, 0)
            z = struct.unpack_from("<I", payload, pos)[0]   # uint32 Z, then one flag byte
            factory, standardised, sigma = struct.unpack_from("<3f", payload, pos + 5)
            result.elements[name] = PdzElement(name=name, z=z, factory_pct=float(factory), standardised_pct=float(standardised), sigma_pct=float(sigma))
        elif rtype == 9:
            pos, n = 2, struct.unpack_from("<H", payload, 0)[0]
            for _ in range(2 * n):
                try:
                    text, pos = _utf16(payload, pos)
                except (struct.error, UnicodeDecodeError):
                    break
                result.strings.append(text)
        offset += 6 + length
    return result
