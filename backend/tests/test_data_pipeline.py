import csv

from app.companies import etl, profiles
from app.companies.sectors import sector_for_okved
from tests.conftest import REPO


def test_sector_mapping_uses_longest_prefix():
    assert sector_for_okved("46.71.1") == "fuel_trade"
    assert sector_for_okved("46.90") == "trade_wholesale"
    assert sector_for_okved("41.20") == "construction"
    assert sector_for_okved("45.11") == "auto"
    assert sector_for_okved(None) == "other"
    assert sector_for_okved("99.99") == "other"


def test_build_profiles_selects_large_business():
    result = etl.build_profiles(REPO / "data" / "synthetic")
    assert result["total_companies"] == 600
    assert result["companies"], "должны быть крупные компании"
    for c in result["companies"]:
        group = c["group"]
        assert c["revenue"] > etl.LARGE_REVENUE or (group["reliable"] and group["revenue"] > etl.LARGE_REVENUE)
        assert c["market"]["note"]
        assert set(c["suppliers"]) >= {"total_amount", "top", "by_sector", "top1_share"}


def test_noisy_values_are_handled(tmp_path):
    src = REPO / "data" / "synthetic"
    for name in ("df_Uid_payment_hack.csv", "df_Fid_Uid_link_hack.csv"):
        (tmp_path / name).write_bytes((src / name).read_bytes())
    rows = list(csv.DictReader((src / "df_Uid_data_hack.csv").open(encoding="utf-8"), delimiter=";"))
    rows[0].update(REVENUE_COMPANY="", MAINOKVED_CODE="", CL_PRODUCT_LOA_MARK="", REGION="")
    rows[1].update(REVENUE_COMPANY="20000000000", FTS_FLAG="1.0", FTS_COUNTRY_NAME="")
    with (tmp_path / "df_Uid_data_hack.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter=";")
        w.writeheader()
        w.writerows(rows)
    result = etl.build_profiles(tmp_path)
    by_id = {c["company_id"]: c for c in result["companies"]}
    noisy = by_id[rows[1]["SYNTHETIC_U"]]
    assert "Есть признак ВЭД, но страны не указаны" in noisy["data_quality"]
    companies = etl.read_companies(tmp_path / "df_Uid_data_hack.csv")
    assert companies[rows[0]["SYNTHETIC_U"]]["products"]["loans"] is None  # пропуск = неизвестно, не False
    assert companies[rows[0]["SYNTHETIC_U"]]["sector"] == "other"


def test_profiles_built_lazily_into_postgres(isolated_runtime):
    meta = profiles.meta()
    assert meta["profiles"] > 0
    from app import database
    with database.session() as conn:
        from sqlalchemy import select, func
        from app.models import Company
        assert conn.scalar(select(func.count()).select_from(Company)) == meta["profiles"]
    assert not (isolated_runtime / "companies.json").exists()


def test_exposures_reference_client_features(client, company):
    exps = profiles.exposures(company["company_id"])
    assert exps
    assert all(e["feature"] and e["why"] and e["topic"] for e in exps)
    if company["products"]["loans"]:
        assert any(e["feature"] == "products.loans" and e["topic"] == "key_rate" for e in exps)


def test_directory_named_synthetic_is_not_a_dataset_marker(tmp_path, monkeypatch):
    import shutil
    for path in (REPO / "data" / "synthetic").glob("*.csv"):
        shutil.copy(path, tmp_path / path.name)
    (tmp_path / "SYNTHETIC").mkdir()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    profiles.reset_cache()
    assert profiles.meta()["synthetic"] is False
