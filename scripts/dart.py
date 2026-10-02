"""DART(전자공시) Open API 수집.

1) 지분증권 증권신고서(C001) 공시 목록 → IPO 기업의 corp_code·신고서 접수번호
2) estkRs: 증권신고서 주요정보 (공모주식수, 모집가액, 인수인, 자금의 사용목적, 매출인)
3) fnlttSinglAcnt: 주요 재무 (매출액·영업이익·당기순이익 등, 최근 3개년)

결과: data/raw/dart_list/*.json, data/raw/dart_ipo.json
"""
import os
import time
from datetime import date, datetime, timedelta

from common import RAW, SPAC_RE, START, TODAY, http, load_env, norm_name, read_json, write_json

API = "https://opendart.fss.or.kr/api/"
LIST_DIR = RAW / "dart_list"
CACHE = RAW / "dart_ipo.json"


def api(name, **params):
    r = http("GET", API + name, params={"crtfc_key": os.environ["DART_API_KEY"], **params}).json()
    if r.get("status") == "020":
        raise SystemExit("DART 일일 요청 한도 초과")
    time.sleep(0.15)
    return r


def fetch_list():
    """90일 단위로 C001 공시 목록을 받는다. 지난 구간은 캐시를 재사용."""
    rows = []
    s = START
    while s <= TODAY:
        e = min(s + timedelta(days=89), TODAY)
        path = LIST_DIR / f"{s:%Y%m%d}.json"
        cached = read_json(path)
        if cached is None or e >= TODAY - timedelta(days=150):
            cached, page = [], 1
            while True:
                r = api("list.json", bgn_de=f"{s:%Y%m%d}", end_de=f"{e:%Y%m%d}",
                        pblntf_detail_ty="C001", page_no=page, page_count=100)
                if r["status"] != "000":
                    break
                cached += [{k: x[k] for k in ("corp_code", "corp_name", "stock_code", "corp_cls",
                                              "report_nm", "rcept_no", "rcept_dt")} for x in r["list"]]
                if page >= r["total_page"]:
                    break
                page += 1
            write_json(path, cached)
        rows += cached
        s = e + timedelta(days=1)
    return rows


def ipo_targets():
    """KIND·38 에 등장한 IPO 기업명(정규화)과 종목코드 집합.
    상장 전후로 사명이 바뀌는 경우가 있어 종목코드로도 찾는다."""
    names, codes = set(), set()
    for f in ("kind_invstg", "kind_pubofr", "kind_listing", "38_sched", "38_forecast", "38_listed"):
        for x in read_json(RAW / f"{f}.json", []):
            names.add(norm_name(x["name"]))
            if x.get("code"):
                codes.add(x["code"])
    return names, codes


def financials(corp_code):
    """가장 최근 사업보고서 기준 주요계정(연결 우선). 없으면 None."""
    for y in (TODAY.year - 1, TODAY.year - 2):
        r = api("fnlttSinglAcnt.json", corp_code=corp_code, bsns_year=str(y), reprt_code="11011")
        if r.get("status") != "000":
            continue
        lst = r["list"]
        cfs = [x for x in lst if x.get("fs_div") == "CFS"] or [x for x in lst if x.get("fs_div") == "OFS"]
        keep = {}
        for x in cfs:
            if x["account_nm"] in ("매출액", "수익(매출액)", "영업수익", "영업이익", "영업이익(손실)",
                                   "당기순이익", "당기순이익(손실)", "자산총계", "부채총계", "자본총계"):
                key = x["account_nm"].replace("(손실)", "").replace("수익(매출액)", "매출액").replace("영업수익", "매출액")
                keep.setdefault(key, [x.get("bfefrmtrm_amount"), x.get("frmtrm_amount"), x.get("thstrm_amount")])
        return {"year": y, "fs": cfs[0]["fs_div"] if cfs else None, "accounts": keep}
    return None


def main():
    load_env()
    if not os.environ.get("DART_API_KEY"):
        raise SystemExit("DART_API_KEY 가 없습니다 (.env 또는 GitHub Secrets 확인)")
    rows = fetch_list()
    print(f"DART C001 공시 {len(rows)}건")

    names, codes = ipo_targets()
    by_corp = {}
    for x in rows:
        if norm_name(x["corp_name"]) in names or (x["stock_code"] and x["stock_code"] in codes):
            by_corp.setdefault(x["corp_code"], []).append(x)

    cache = read_json(CACHE, {})
    now = datetime.now().isoformat(timespec="seconds")
    n_new = 0
    for cc, fl in by_corp.items():
        fl.sort(key=lambda x: x["rcept_no"])
        # IPO 공모가 끝나면 '증권발행실적보고서'가 나온다. 그 뒤의 유상증자 등은 제외
        done = next((i for i, x in enumerate(fl) if "증권발행실적보고서" in x["report_nm"]), None)
        if done is not None:
            fl = fl[:done + 1]
        filings = [x for x in fl if "증권신고서" in x["report_nm"] and "첨부" not in x["report_nm"]]
        if not filings:
            continue
        last_no = fl[-1]["rcept_no"]
        ent = cache.get(cc, {})
        stale_fin = ent.get("fin_checked", "") < (TODAY - timedelta(days=30)).isoformat()
        if ent.get("last_rcept") == last_no and not stale_fin:
            continue
        name = fl[-1]["corp_name"]
        ent.update({
            "corp_code": cc, "corp_name": name, "stock_code": fl[-1]["stock_code"] or ent.get("stock_code"),
            "last_rcept": last_no,
            "filings": [[x["rcept_dt"], x["report_nm"], x["rcept_no"]] for x in fl],
        })
        if ent.get("estk_rcept") != last_no:
            r = api("estkRs.json", corp_code=cc, bgn_de=fl[0]["rcept_dt"], end_de=fl[-1]["rcept_dt"])
            ent["estk"] = r.get("group") if r.get("status") == "000" else None
            ent["estk_rcept"] = last_no
        if stale_fin:
            ent["fin"] = None if SPAC_RE.search(name) else financials(cc)
            ent["fin_checked"] = TODAY.isoformat()
        ent["updated"] = now
        cache[cc] = ent
        n_new += 1
        if n_new % 50 == 0:
            write_json(CACHE, cache)
            print(f"  … {n_new}개 갱신", flush=True)
    write_json(CACHE, cache)
    print(f"DART IPO 기업 {len(cache)}개 (이번에 갱신 {n_new}개)")


if __name__ == "__main__":
    main()
