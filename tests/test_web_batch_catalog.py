from app.web import WebHandler


def test_web_batch_catalog_covers_all_42_upload_numbers():
    assert sorted(WebHandler.BATCH_INDICATORS) == list(range(1, 43))
    assert WebHandler.BATCH_INDICATORS[20][0] == "capacity_utilization_rate"
    assert WebHandler.BATCH_INDICATORS[29][0] == "international_balance_current_account"
    assert WebHandler.BATCH_INDICATORS[42][0] == "government_bond_net_financing_monthly"
