from sim.card_catalog_audit import canonical, report


def test_canonical_handles_client_separator_and_case_formats():
    assert canonical("the-log") == canonical("The Log")
    assert canonical("Elixir Collector") == canonical("elixir _collector")
    assert canonical("dart-goblin") != canonical("BlowdartGoblin")


def test_every_synced_public_card_has_one_client_data_mapping():
    result = report()
    assert result["public_cards"] == 120
    assert len(result["mapped"]) == 120
    assert result["unresolved"] == []
    assert result["ambiguous"] == {}
