"""Hand-checkable cases for the density-altitude helpers."""

import pytest

from app.core import physics as ph


def test_sea_level_isa_has_zero_density_altitude_and_full_factors() -> None:
    assert ph.density_altitude_ft(0, 15.0) == pytest.approx(0.0)
    assert ph.density_ratio(0.0) == pytest.approx(1.0)
    assert ph.payload_factor("TPT-B", 0.0) == 1.0


def test_isa_density_ratio_at_10000_ft_matches_standard_table() -> None:
    # Standard atmosphere table: sigma(10,000 ft) = 0.7385
    assert ph.density_ratio(10000.0) == pytest.approx(0.7385, abs=0.002)


def test_density_altitude_hot_day_at_sea_level() -> None:
    # OAT 45 C, ISA 15 C -> +30 C * 120 ft/C = 3600 ft
    assert ph.density_altitude_ft(0, 45.0) == pytest.approx(3600.0)


def test_density_altitude_at_isa_temperature_equals_pressure_altitude() -> None:
    elev_m = 3048.0  # 10,000 ft
    isa_c = ph.isa_temperature_c(elev_m * ph.M_TO_FT)
    assert isa_c == pytest.approx(-4.812, abs=0.01)
    assert ph.density_altitude_ft(elev_m, isa_c) == pytest.approx(elev_m * ph.M_TO_FT)


def test_helicopter_loses_more_payload_than_transport_at_altitude() -> None:
    da = 12000.0
    assert ph.payload_factor("HEL-C", da) < ph.payload_factor("TPT-B", da) < 1.0


def test_factors_are_clamped_and_range_degrades_less_than_payload() -> None:
    assert ph.payload_factor("HEL-C", 30000.0) == ph.MIN_FACTOR
    da = 8000.0
    assert ph.range_factor("FTR-A", da) > ph.payload_factor("FTR-A", da)


def test_available_payload_drops_at_a_high_hot_site() -> None:
    sea = ph.available_payload_kg("HEL-C", 0, 15.0)
    high = ph.available_payload_kg("HEL-C", 3500, 20.0)
    assert sea == pytest.approx(2000.0)
    assert high < 0.7 * sea
