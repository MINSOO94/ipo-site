"""네이버 금융 일별 시세 수집 (상장 후 주가 + 코스피/코스닥 지수).

결과: data/prices/{종목코드}.json = [[YYYYMMDD, 시가, 고가, 저가, 종가], ...]
      data/prices/KOSPI.json, KOSDAQ.json
- 상장 후 400일 이내 종목은 매일 새로 받고, 그보다 오래된 종목은 한 번 받은 뒤 재사용한다.
"""
import ast
import time
from datetime import date, timedelta

from common import PRICES, RAW, START, TODAY, http, norm_name, read_json, valid_code, write_json

URL = "https://api.finance.naver.com/siseJson.naver"
RECENT_DAYS = 400   # 이 기간 안의 신규상장주는 매일 갱신
KEEP_DAYS = 250     # 오래된 종목은 상장 후 이 기간까지만 보관


def fetch(symbol, start, end):
    r = http("GET", URL, params={"symbol": symbol, "requestType": 1, "timeframe": "day",
                                 "startTime": f"{start:%Y%m%d}", "endTime": f"{end:%Y%m%d}"})
    rows = ast.literal_eval(r.text.strip())[1:]  # 첫 줄은 헤더
    return [[d, o, h, l, c] for d, o, h, l, c, *_ in rows if c]


def main():
    for idx in ("KOSPI", "KOSDAQ"):
        write_json(PRICES / f"{idx}.json", fetch(idx, date(START.year - 1, 1, 1), TODAY))

    # 외국기업은 KIND 에 종목코드가 없어서 DART 의 종목코드로 보완
    dart_code = {norm_name(d["corp_name"]): d.get("stock_code")
                 for d in read_json(RAW / "dart_ipo.json", {}).values()}
    listing = []
    for x in read_json(RAW / "kind_listing.json", []):
        if x["market"] not in ("KOSPI", "KOSDAQ"):
            continue
        if not valid_code(x.get("code")):
            x["code"] = dart_code.get(norm_name(x["name"]))
        if valid_code(x.get("code")):
            listing.append(x)
    n = 0
    for x in listing:
        ld = date.fromisoformat(x["listing_date"])
        path = PRICES / f"{x['code']}.json"
        recent = ld >= TODAY - timedelta(days=RECENT_DAYS)
        if path.exists() and not recent:
            continue
        end = TODAY if recent else min(TODAY, ld + timedelta(days=KEEP_DAYS))
        try:
            rows = fetch(x["code"], ld, end)
        except Exception as e:  # 상장폐지 등으로 데이터가 없을 수 있음
            print("  !", x["name"], x["code"], e)
            rows = []
        write_json(path, rows)
        n += 1
        time.sleep(0.25)
    print(f"네이버 시세: 지수 2개, 종목 {n}개 갱신 (전체 대상 {len(listing)}개)")


if __name__ == "__main__":
    main()
