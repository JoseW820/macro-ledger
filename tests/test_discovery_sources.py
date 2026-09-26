from app.providers.discovery import discover_customs_statistical_links, discover_mof_statistical_links


def test_mof_statistics_discovery_finds_articles_and_pdf():
    html = '<a href="202609/a.htm">2026年1-8月财政收支情况</a><a href="202608/a.pdf">政府收支及融资数据</a><a href="x.htm">其他</a>'
    links = discover_mof_statistical_links(html)
    assert [link.url for link in links] == ["https://gks.mof.gov.cn/tongjishuju/202609/a.htm", "https://gks.mof.gov.cn/tongjishuju/202608/a.pdf"]


def test_customs_discovery_filters_trade_entries():
    html = '<a href="/trade.htm">进出口总值</a><a href="/other.htm">政策</a>'
    links = discover_customs_statistical_links(html)
    assert links[0].url == "https://www.customs.gov.cn/trade.htm"
