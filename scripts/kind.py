"""KIND(한국거래소 기업공시채널) 수집: 상장예비심사 / 공모진행 / 신규상장.

결과: data/raw/kind_invstg.json, kind_pubofr.json, kind_listing.json
"""
import re
import time
from datetime import date

from bs4 import BeautifulSoup

from common import RAW, START, TODAY, http, to_int, write_json

BASE = "https://kind.krx.co.kr"
XHR = {"X-Requested-With": "XMLHttpRequest"}
MARKET = {"코스닥": "KOSDAQ", "유가증권": "KOSPI", "코넥스": "KONEX"}


def post(path, data):
    form = {"currentPageSize": "3000", "pageIndex": "1", "orderMode": "", "orderStat": "", "marketType": "", **data}
    html = http("POST", BASE + path, data=form, headers=XHR).text
    if "잠시 후 다시 이용해 주세요" in html:
        raise RuntimeError(f"KIND 오류 응답: {path}")
    return BeautifulSoup(html, "html.parser")


def market_of(td):
    img = td.find("img", class_=re.compile("vmiddle"))
    return MARKET.get(img.get("alt") if img else "", "")


def cells(tr):
    return [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip() for td in tr.find_all("td")]


def year_ranges():
    for y in range(START.year, TODAY.year + 1):
        yield date(y, 1, 1).isoformat(), min(date(y, 12, 31), TODAY).isoformat()


def fetch_invstg():
    """상장예비심사 청구 기업 (청구일 기준)."""
    out = []
    for f, t in year_ranges():
        soup = post("/listinvstg/listinvstgcom.do", {
            "method": "searchListInvstgCorpSub", "forward": "listinvstgcom_sub", "fromDate": f, "toDate": t})
        for tr in soup.select("tbody tr"):
            c = cells(tr)
            if len(c) < 6:
                continue
            m = re.search(r"fnDetailView\('(\d+)'", tr.get("onclick", ""))
            out.append({
                "name": c[0], "market": market_of(tr.td), "list_type": c[1],
                "apply_date": c[2] or None, "result_date": c[3] or None,
                "result": c[4].replace(" ", ""), "underwriter": c[5],
                "kind_id": m.group(1) if m else None,
            })
        time.sleep(1)
    return out


def fetch_pubofr():
    """공모 진행 기업 (신고서 제출 ~ 상장예정)."""
    out = []
    f = date(TODAY.year - 1, 1, 1).isoformat()
    t = date(TODAY.year + 1, 12, 31).isoformat()
    soup = post("/listinvstg/pubofrprogcom.do", {
        "method": "searchPubofrProgComSub", "forward": "pubofrprogcom_sub", "fromDate": f, "toDate": t})
    for tr in soup.select("tbody tr"):
        c = cells(tr)
        if len(c) < 9:
            continue
        m = re.search(r"fnDetailView\('(\d+)'", tr.get("onclick", ""))

        def rng(s):
            d = re.findall(r"\d{4}-\d{2}-\d{2}", s)
            return (d[0], d[-1]) if d else (None, None)

        out.append({
            "name": c[0], "market": market_of(tr.td), "filing_date": c[1] or None,
            "forecast": rng(c[2]), "subscription": rng(c[3]), "payment_date": c[4] or None,
            "offer_price": to_int(c[5]), "offer_amount_mil": to_int(c[6]),
            "listing_date": c[7] or None, "underwriter": c[8], "kind_id": m.group(1) if m else None,
        })
    return out


def fetch_listing():
    """신규상장 기업 (상장일 기준). 종목코드·공모가·업종·주요제품 포함."""
    out = []
    for f, t in year_ranges():
        soup = post("/listinvstg/listingcompany.do", {
            "method": "searchListingTypeSub", "forward": "listingtype_sub", "orderMode": "1", "orderStat": "D",
            "country": "", "industry": "", "listTypeArrStr": "01|02|",  # 신규상장 + 이전상장
            "choicTypeArrStr": "01|02|03|04|05|06|", "secuGrpArrStr": "0|ST|FS|MF|SC|RT|IF|DR|",
            "repMajAgntDesignAdvserComp": "", "designAdvserComp": "", "repMajAgntComp": "",
            "fromDate": f, "toDate": t})
        for tr in soup.select("tbody tr"):
            c = cells(tr)
            if len(c) < 12:
                continue
            m = re.search(r"fnDetailView\('([0-9A-Z]+)'", tr.get("onclick", ""))
            code = (m.group(1) + "0") if m and len(m.group(1)) == 5 else (m.group(1) if m else None)
            out.append({
                "name": c[0], "market": market_of(tr.td), "listing_date": c[1], "list_type": c[2],
                "security": c[3], "industry": c[4], "country": c[5], "underwriter": c[6],
                "par": to_int(c[7]), "offer_price": to_int(c[8]), "offer_amount": to_int(c[9]),
                "product": c[10], "listed_shares": to_int(c[11]), "code": code,
            })
        time.sleep(1)
    return out


def main():
    inv = fetch_invstg()
    write_json(RAW / "kind_invstg.json", inv, indent=1)
    print(f"KIND 예비심사 {len(inv)}건")
    pub = fetch_pubofr()
    write_json(RAW / "kind_pubofr.json", pub, indent=1)
    print(f"KIND 공모진행 {len(pub)}건")
    lst = fetch_listing()
    write_json(RAW / "kind_listing.json", lst, indent=1)
    print(f"KIND 신규상장 {len(lst)}건")


if __name__ == "__main__":
    main()
