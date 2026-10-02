"""38커뮤니케이션 수집: 청약일정 / 수요예측결과 / 신규상장.

38.co.kr 은 오래된 TLS 라 http 로 접속하고, 인코딩은 EUC-KR 이다.
결과: data/raw/38_sched.json, 38_forecast.json, 38_listed.json
"""
import re
import time

from bs4 import BeautifulSoup

from common import RAW, START, http, num, to_int, write_json

BASE = "http://www.38.co.kr/html/fund/index.htm"
TABLES = {"k": "공모주 청약일정", "r1": "수요예측결과", "nw": "신규상장종목"}


def page_rows(o, page):
    r = http("GET", BASE, params={"o": o, "page": page})
    r.encoding = "euc-kr"
    soup = BeautifulSoup(r.text, "html.parser")
    tb = soup.find("table", summary=TABLES[o])
    if not tb:
        return []
    rows = []
    for tr in tb.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        a = tds[0].find("a")
        no = re.search(r"no=(\d+)", a.get("href", "")) if a else None
        rows.append(([re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tds], no.group(1) if no else None))
    return rows


def crawl(o, date_of, max_pages=80):
    """START 이전 날짜가 나올 때까지 페이지를 넘기며 수집."""
    out = []
    for p in range(1, max_pages + 1):
        rows = page_rows(o, p)
        if not rows:
            break
        out += rows
        d = date_of(rows[-1][0])
        if d and d < START.isoformat():
            break
        time.sleep(0.7)
    return out


def band(s):
    v = [to_int(x) for x in re.findall(r"[\d,]+", s or "")]
    return v[:2] if len(v) >= 2 else None


def sched_dates(s):
    """'2025.12.30~01.02' → ('2025-12-30', '2026-01-02')"""
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})\s*~\s*(\d{2})\.(\d{2})", s or "")
    if not m:
        return None, None
    y, m1, d1, m2, d2 = map(int, m.groups())
    y2 = y + 1 if m2 < m1 else y
    return f"{y:04d}-{m1:02d}-{d1:02d}", f"{y2:04d}-{m2:02d}-{d2:02d}"


def main():
    sched = []
    for c, no in crawl("k", lambda c: sched_dates(c[1])[0]):
        s, e = sched_dates(c[1])
        sched.append({"name": c[0], "no": no, "sub_start": s, "sub_end": e, "offer_price": to_int(c[2]),
                      "band": band(c[3]), "sub_competition": num(c[4]), "underwriter": c[5]})
    write_json(RAW / "38_sched.json", sched, indent=1)
    print(f"38 청약일정 {len(sched)}건")

    fc = []
    for c, no in crawl("r1", lambda c: c[1].replace(".", "-")):
        fc.append({"name": c[0], "no": no, "forecast_date": c[1].replace(".", "-"), "band": band(c[2]),
                   "offer_price": to_int(c[3]), "offer_amount_mil": to_int(c[4]),
                   "inst_competition": num(c[5]), "lockup_pct": num(c[6]), "underwriter": c[7]})
    write_json(RAW / "38_forecast.json", fc, indent=1)
    print(f"38 수요예측 {len(fc)}건")

    ls = []
    for c, no in crawl("nw", lambda c: c[1].replace("/", "-")):
        ls.append({"name": c[0], "no": no, "listing_date": c[1].replace("/", "-"), "offer_price": to_int(c[4]),
                   "open_price": to_int(c[6]), "first_close": to_int(c[8])})
    write_json(RAW / "38_listed.json", ls, indent=1)
    print(f"38 신규상장 {len(ls)}건")


if __name__ == "__main__":
    main()
