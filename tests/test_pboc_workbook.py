import io

from openpyxl import Workbook

from app.providers.pboc_workbook import parse_monthly_workbook


def test_parse_pboc_workbook_uses_unit_section_and_month_rows():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["社会融资规模增量统计表"])
    sheet.append(["单位：亿元人民币"])
    sheet.append(["月份", "增量"])
    sheet.append(["2025.08", 3245])
    sheet.append(["注：", "忽略"])
    sheet.append(["单位：百分比"])
    sheet.append(["2025.08", 99])
    stream = io.BytesIO()
    workbook.save(stream)
    assert parse_monthly_workbook(stream.getvalue()) == [{"period": "2025-08", "value": 3245, "unit": "亿元"}]
