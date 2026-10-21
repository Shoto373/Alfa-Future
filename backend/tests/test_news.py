import pytest

from app.knowledge import kb
from app.news import parser, store
from app.news.classifier import classify

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>ЦБ повысил ключевую ставку до 16%</title><link>https://example.org/a</link>
<pubDate>Mon, 19 Oct 2026 10:00:00 +0300</pubDate>
<description><![CDATA[<p>Совет директоров Банка России повысил ключевую ставку до 16% годовых из-за ускорения инфляции.</p>]]></description></item>
<item><title>Короткая</title><description>мало</description></item>
</channel></rss>"""


def test_classifier_detects_topics_direction_and_facts():
    cls = classify("Банк России сохранил ключевую ставку на уровне 14% годовых",
                   "11 сентября 2026 года совет директоров Банка России сохранил ключевую ставку на уровне 14%. "
                   "Регулятор отметил ускорение инфляции.")
    assert cls.topic_keys()[0] == "key_rate"
    assert cls.direction == "hold"
    assert "Банк России" in cls.actors
    assert any("14%" in n for n in cls.numbers)
    assert any("11 сентября 2026" in d for d in cls.dates)


def test_credit_tightening_is_down_for_credit_market():
    cls = classify("С 1 октября ужесточаются лимиты по автокредитам",
                   "Банк России ужесточает макропруденциальные лимиты по автокредитам, выдачи автокредитов снижаются.")
    assert cls.topic_directions.get("credit_market") == "down"


def test_countries_and_sectors():
    cls = classify("Расчеты в юанях с Китаем", "Импортеры оптовой торговли переходят на расчеты в юанях с поставщиками из КНР.")
    assert "Китай" in cls.countries
    assert "trade_wholesale" in cls.sectors
    assert "imports_exports" in cls.topic_keys() or "fx" in cls.topic_keys()


def test_seed_feed_loaded_and_classified():
    items = store.all_items()
    assert len(items) >= 10
    assert all(i["classification"]["topics"] for i in items)


def test_duplicates_are_merged():
    a = store.make_item("Минфин разместил ОФЗ на 51,5 млрд рублей",
                        "Минфин 9 сентября разместил выпуск ОФЗ 26218 на 51,5 млрд рублей по средневзвешенной доходности 15,45%.",
                        "Источник А", "https://a.example")
    b = store.make_item("Минфин разместил ОФЗ на 51,5 млрд руб.",
                        "Минфин 9 сентября разместил выпуск ОФЗ 26218 на 51,5 млрд рублей по средневзвешенной доходности 15,45%.",
                        "Источник Б", "https://b.example")
    saved_a, created_a = store.add(a)
    saved_b, created_b = store.add(b)
    assert created_a and not created_b
    assert saved_b["news_id"] == saved_a["news_id"]
    assert saved_b["duplicates"][0]["source"] == "Источник Б"


def test_rss_parsing_skips_short_items():
    items = parser.parse_rss(RSS, "Тест")
    assert len(items) == 1
    assert items[0]["classification"]["topics"][0]["topic"] == "key_rate"
    assert items[0]["url"] == "https://example.org/a"
    assert items[0]["kind"] == "rss"


@pytest.mark.parametrize("url", ["ftp://x.org/a", "http://127.0.0.1/admin", "http://localhost:8000/healthz", "http://10.0.0.1/"])
def test_ssrf_guard(url):
    with pytest.raises(parser.FetchError):
        parser.check_url(url)


def test_kb_search_prefers_fresh_and_hides_stale():
    found = kb.search("ключевая ставка", ["key_rate"], [])
    assert found and found[0]["doc_id"] == "rate_2026_09_11"
    assert all(not t["stale"] for t in found)
    steel = kb.search("сталь прокат", ["metals_steel"], ["metallurgy"], include_stale=True)
    assert steel and steel[0]["stale"]


def test_kb_has_conflicting_rate_forecasts():
    forecasts = kb.latest_forecasts("key_rate")
    assert len({f["doc_id"] for f in forecasts}) > 1
