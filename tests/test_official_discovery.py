from app.providers.pboc import discover_pboc_attachment, discover_pboc_workbook_urls, discover_pboc_topic
from app.providers.safe import discover_safe_monthly_articles


def test_pboc_discovers_year_sections_without_numeric_ids():
    html = '<a href="/stats/section/9876/index.html">2026年统计数据</a><a href="/stats/section/1234/">2025年统计数据</a>'
    assert discover_pboc_workbook_urls(html) == {
        2026: "https://www.pbc.gov.cn/stats/section/9876/index.html",
        2025: "https://www.pbc.gov.cn/stats/section/1234/",
    }


def test_pboc_finds_workbook_near_table_label():
    html = '<h2>社会融资规模增量统计表</h2><a href="/files/sf.xlsx">下载</a><h2>其他</h2><a href="/files/other.xlsx">下载</a>'
    assert discover_pboc_attachment(html, "https://www.pbc.gov.cn/topic/", "社会融资规模增量统计表") == "https://www.pbc.gov.cn/files/sf.xlsx"


def test_pboc_finds_topic_link():
    assert discover_pboc_topic('<a href="/topic.html">货币统计概览</a>', "https://www.pbc.gov.cn/year/", "货币统计概览") == "https://www.pbc.gov.cn/topic.html"


def test_safe_discovers_only_relevant_articles():
    html = '<a href="/safe/2026/0915/1.html">2026年8月银行结售汇和银行代客涉外收付款数据</a><a href="/safe/2026/0901/2.html">政策通知</a>'
    links = discover_safe_monthly_articles(html)
    assert len(links) == 1
    assert links[0].url.endswith("/safe/2026/0915/1.html")
