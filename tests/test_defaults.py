from __future__ import annotations

from imoveis_radar.model import DEFAULT_SETTINGS, fixed_cost_for


def test_default_debts_are_30_percent_of_appraisal():
    assert DEFAULT_SETTINGS["custo_fixo_modo"] == "percentual"
    assert DEFAULT_SETTINGS["custo_fixo"] == 30.0
    assert fixed_cost_for(DEFAULT_SETTINGS, 200_000.0) == 60_000.0
