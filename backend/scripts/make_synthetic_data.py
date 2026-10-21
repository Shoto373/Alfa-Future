"""Генератор синтетического набора данных в схеме кейса (Приложение 1).

Реальные CSV кейса в репозиторий не входят. Этот набор воспроизводит схему,
типичные распределения и шум (пропуски, выручка-заглушка, «большие» группы),
чтобы тесты, CI и сквозной сценарий работали без исходных данных.

    python scripts/make_synthetic_data.py --out ../data/synthetic
"""

import argparse
import csv
import random
from pathlib import Path

SEED = 2026

OKVED = [
    ("46.71", "Торговля оптовая твердым, жидким и газообразным топливом и подобными продуктами"),
    ("46.90", "Торговля оптовая неспециализированная"),
    ("46.34", "Торговля оптовая напитками"),
    ("46.21", "Торговля оптовая зерном, необработанным табаком, семенами и кормами для сельскохозяйственных животных"),
    ("46.46", "Торговля оптовая фармацевтической продукцией"),
    ("46.51", "Торговля оптовая компьютерами, периферийными устройствами к компьютерам и программным обеспечением"),
    ("45.11", "Торговля легковыми автомобилями и грузовыми автомобилями малой грузоподъемности"),
    ("41.20", "Строительство жилых и нежилых зданий"),
    ("42.11", "Строительство автомобильных дорог и автомагистралей"),
    ("47.11", "Торговля розничная преимущественно пищевыми продуктами в неспециализированных магазинах"),
    ("49.41", "Деятельность автомобильного грузового транспорта"),
    ("52.10", "Деятельность по складированию и хранению"),
    ("10.11", "Переработка и консервирование мяса"),
    ("01.11", "Выращивание зерновых культур"),
    ("24.10", "Производство чугуна, стали и ферросплавов"),
    ("07.29", "Добыча руд прочих цветных металлов"),
    ("35.11", "Производство электроэнергии"),
    ("62.01", "Разработка компьютерного программного обеспечения"),
    ("68.20", "Аренда и управление собственным или арендованным недвижимым имуществом"),
    ("56.10", "Деятельность ресторанов и услуги по доставке продуктов питания"),
    ("28.92", "Производство машин и оборудования для добычи полезных ископаемых и строительства"),
    ("20.15", "Производство удобрений и азотных соединений"),
]
REGIONS = [
    ("г. Москва", "Москва"), ("г. Санкт-Петербург", "Санкт-Петербург"), ("г. Новосибирск", "Новосибирская область"),
    ("г. Екатеринбург", "Свердловская область"), ("г. Казань", "Республика Татарстан"),
    ("г. Краснодар", "Краснодарский край"), ("г. Челябинск", "Челябинская область"),
    ("г. Владивосток", "Приморский край"), ("г. Ростов-на-Дону", "Ростовская область"),
]
OKFS = ["ЧАСТНАЯ СОБСТВЕННОСТЬ"] * 12 + ["СОБСТВЕННОСТЬ ИНОСТРАННЫХ ЮРИДИЧЕСКИХ ЛИЦ", "ФЕДЕРАЛЬНАЯ СОБСТВЕННОСТЬ"]
AGES = ["0-3", "4-7", "8-15", "16-25"]
STAGES = ["Оптимизация", "Бизнес в новой реальности", "Рождение", "Стремительный рост", ""]
WORKERS = ["Менее 15", "16-100", "101-250", "Более 251"]
COUNTRIES = ["КИТАЙ", "ТУРЦИЯ", "КИТАЙ, ТУРЦИЯ", "ОАЭ, ИНДИЯ, КИТАЙ", "КАЗАХСТАН", "УЗБЕКИСТАН", "КИТАЙ, ГОНКОНГ"]
HEADER = ("SYNTHETIC_U;ORG_TYPE;OKFS_NAME;COMPANY_AGE_YEARS_GRADATION;ECO_MARK_LABEL;MAINOKVED_CODE;MAINOKVED_NAME;"
          "NEGATIVEMARK;AMOUNT_WORKERS_FNS_GRADATION;AMOUNT_WORKERS_SPARK_GRADATION;CL_TYPE;CL_PRODUCT_RKO_MARK;"
          "CL_PRODUCT_GAR_MARK;CL_PRODUCT_LOA_MARK;CL_PRODUCT_LEA_MARK;CL_PRODUCT_DEP_MARK;CL_PRODUCT_ZPP_MARK;"
          "FTS_FLAG;FTS_COUNTRY_NAME;FACTORING_MARK;REVENUE_COMPANY;GROUP_ID;CITY;REGION").split(";")


def flag(rng: random.Random, p: float) -> str:
    return "1.0" if rng.random() < p else "0.0"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--companies", type=int, default=600)
    args = parser.parse_args()
    rng = random.Random(SEED)
    args.out.mkdir(parents=True, exist_ok=True)

    rows = []
    for i in range(1, args.companies + 1):
        code, name = rng.choice(OKVED)
        city, region = rng.choice(REGIONS)
        large = i <= 45
        revenue = rng.uniform(16e9, 120e9) if large else 10 ** rng.uniform(6, 10.3)
        if i % 97 == 0:
            revenue = 1000.0  # заглушка, как в исходных данных
        fts = rng.random() < (0.45 if large else 0.1)
        group = f"group_{900000 + (i % 40 if i % 3 else 99)}_sb" if i > 45 else f"group_{800000 + i // 3}_sb"
        rows.append({
            "SYNTHETIC_U": f"U_{i}", "ORG_TYPE": "КОММ_ОРГ", "OKFS_NAME": rng.choice(OKFS),
            "COMPANY_AGE_YEARS_GRADATION": rng.choice(AGES), "ECO_MARK_LABEL": rng.choice(STAGES),
            "MAINOKVED_CODE": code, "MAINOKVED_NAME": name, "NEGATIVEMARK": flag(rng, 0.13),
            "AMOUNT_WORKERS_FNS_GRADATION": rng.choice(WORKERS[2:] if large else WORKERS),
            "AMOUNT_WORKERS_SPARK_GRADATION": rng.choice(WORKERS) if rng.random() < 0.05 else "",
            "CL_TYPE": rng.choice(["CLIENT", "CLIENT", "PROSPECT", "CLOSE_CLIENT"]),
            "CL_PRODUCT_RKO_MARK": flag(rng, 0.6), "CL_PRODUCT_GAR_MARK": flag(rng, 0.2 if large else 0.03),
            "CL_PRODUCT_LOA_MARK": flag(rng, 0.45 if large else 0.06), "CL_PRODUCT_LEA_MARK": flag(rng, 0.3),
            "CL_PRODUCT_DEP_MARK": flag(rng, 0.3 if large else 0.05), "CL_PRODUCT_ZPP_MARK": flag(rng, 0.4),
            "FTS_FLAG": "1.0" if fts else "0.0", "FTS_COUNTRY_NAME": rng.choice(COUNTRIES) if fts and rng.random() < 0.9 else "",
            "FACTORING_MARK": flag(rng, 0.05), "REVENUE_COMPANY": f"{revenue:.1f}", "GROUP_ID": group,
            "CITY": city, "REGION": region,
        })
    with (args.out / "df_Uid_data_hack.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADER, delimiter=";")
        w.writeheader()
        w.writerows(rows)

    ids = [r["SYNTHETIC_U"] for r in rows]
    with (args.out / "df_Uid_payment_hack.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["BENEFICIARY", "PAYER", "PAY_AMT", "PAY_CNT"])
        for payer in ids:
            for _ in range(rng.randint(2, 12)):
                benef = rng.choice(ids) if rng.random() < 0.7 else f"U_{rng.randint(10_000, 20_000)}"
                w.writerow([benef, payer, f"{10 ** rng.uniform(4, 9.5):.1f}", rng.randint(1, 300)])
            if rng.random() < 0.02:
                w.writerow([payer, payer, f"{10 ** rng.uniform(8, 10):.1f}", rng.randint(10, 500)])

    with (args.out / "df_Fid_Uid_link_hack.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["SYNTHETIC_F", "CITY_NAME", "RC_NAME", "SYNTHETIC_U"])
        for n in range(1, 220):
            city, region = rng.choice(REGIONS)
            for cid in rng.sample(ids, rng.choice([1, 1, 1, 2, 3])):
                w.writerow([f"F_{n}", city.replace("г. ", ""), region.upper(), cid])
    print(f"synthetic data -> {args.out}")


if __name__ == "__main__":
    main()
