"""Density-altitude effects on payload and range (INDIA_CONTEXT §3.2).

APPROXIMATE and ILLUSTRATIVE. The atmosphere maths is the standard ISA approximation; the
per-type numbers in `TYPE_PERFORMANCE` are placeholders, not real aircraft data (HONESTY.md).

Model
- Pressure altitude is taken as field elevation (standard pressure assumed).
- Density altitude: DA = PA + 120 ft * (OAT - T_ISA(PA)), T_ISA = 15 C - 1.9812 C per 1000 ft.
- Density ratio: sigma = (1 - 6.8756e-6 * DA_ft) ** 4.2559 (troposphere ISA relation).
- payload_factor = clamp(sigma ** sensitivity, 0.3, 1.0): thin air cuts lift-limited payload;
  helicopters are more sensitive than fixed-wing. No bonus below sea-level density.
- range_factor = sqrt(payload_factor): range/endurance degrade less than payload.
"""

from __future__ import annotations

from dataclasses import dataclass

M_TO_FT = 3.28084
ISA_SEA_LEVEL_C = 15.0
ISA_LAPSE_C_PER_FT = 0.0019812
DA_FT_PER_C = 120.0
MIN_FACTOR = 0.3


@dataclass(frozen=True)
class TypePerformance:
    max_payload_kg: float  # at sea-level ISA (placeholder)
    altitude_sensitivity: float  # exponent applied to the density ratio (placeholder)


TYPE_PERFORMANCE: dict[str, TypePerformance] = {
    "FTR-A": TypePerformance(max_payload_kg=6000, altitude_sensitivity=0.6),
    "TPT-B": TypePerformance(max_payload_kg=15000, altitude_sensitivity=0.7),
    "HEL-C": TypePerformance(max_payload_kg=2000, altitude_sensitivity=1.5),
    "ISR-D": TypePerformance(max_payload_kg=2500, altitude_sensitivity=0.5),
    "TKR-E": TypePerformance(max_payload_kg=12000, altitude_sensitivity=0.7),
}


def isa_temperature_c(altitude_ft: float) -> float:
    return ISA_SEA_LEVEL_C - ISA_LAPSE_C_PER_FT * altitude_ft


def density_altitude_ft(elevation_m: float, oat_c: float) -> float:
    pressure_alt_ft = elevation_m * M_TO_FT
    return pressure_alt_ft + DA_FT_PER_C * (oat_c - isa_temperature_c(pressure_alt_ft))


def density_ratio(da_ft: float) -> float:
    base = 1.0 - 6.8756e-6 * da_ft
    return max(base, 0.0) ** 4.2559


def payload_factor(type_id: str, da_ft: float) -> float:
    sigma = density_ratio(da_ft)
    value = sigma ** TYPE_PERFORMANCE[type_id].altitude_sensitivity
    return min(1.0, max(MIN_FACTOR, value))


def range_factor(type_id: str, da_ft: float) -> float:
    return payload_factor(type_id, da_ft) ** 0.5


def available_payload_kg(type_id: str, elevation_m: float, oat_c: float) -> float:
    da = density_altitude_ft(elevation_m, oat_c)
    return TYPE_PERFORMANCE[type_id].max_payload_kg * payload_factor(type_id, da)
