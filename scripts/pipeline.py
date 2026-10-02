"""수집한 원천 데이터(KIND·38·DART·네이버)를 회사 단위로 합쳐 사이트용 JSON 을 만든다.

입력: data/raw/*.json, data/prices/*.json, data/manual.csv(수동 보정)
출력: data/ipos.json   — 목록 화면용 요약 (회사 1개 = 1행)
      data/meta.json   — 갱신시각, 일정, 월별/분기별 통계, 모델 검증치
      data/detail/{id}.json — 상세 화면용 (공시, 공모개요, 자금용도, 재무, 유사사례)
"""
import csv
import hashlib
import shutil
from collections import defaultdict
from datetime import date, datetime, timedelta

import model
from common import (DATA, PRICES, RAW, SPAC_RE, START, TODAY, norm_name, read_json,
                    to_int, valid_code, write_json)

T = TODAY.isoformat()
WITHDRAWN = {"심사미승인", "심사철회", "공모철회", "상장철회", "승인효력기간만료"}
STAGES = ["review", "approved", "offering", "listed", "withdrawn"]


def load():
    g = lambda f: read_json(RAW / f"{f}.json", [])
    lst = [x for x in g("kind_listing") if x["market"] in ("KOSPI", "KOSDAQ")]
    return g("kind_invstg"), g("kind_pubofr"), lst, g("38_sched"), g("38_forecast"), g("38_listed"), \
        read_json(RAW / "dart_ipo.json", {})


def merge38(sched, fc, listed):
    """38 의 세 표를 종목번호(no) 기준으로 합친다."""
    by = defaultdict(dict)
    for x in sched:
        by[x["no"]].update(name=x["name"], sub_start=x["sub_start"], sub_end=x["sub_end"], band=x["band"],
                           sub_comp=x["sub_competition"], uw=x["underwriter"],
                           offer_price=x["offer_price"] or by[x["no"]].get("offer_price"))
    for x in fc:
        d = by[x["no"]]
        d.update(name=x["name"], forecast_date=x["forecast_date"], inst_comp=x["inst_competition"],
                 lockup_pct=x["lockup_pct"], amount_mil=x["offer_amount_mil"], uw=d.get("uw") or x["underwriter"])
        d["band"] = d.get("band") or x["band"]
        d["offer_price"] = d.get("offer_price") or x["offer_price"]
    for x in listed:
        d = by[x["no"]]
        d.update(name=x["name"], listing_date=x["listing_date"], open=x["open_price"], first_close=x["first_close"])
        d["offer_price"] = d.get("offer_price") or x["offer_price"]
    for no, d in by.items():
        d["no"] = no
        d["kospi"] = "(유가)" in d.get("name", "")
    return by


def load_manual():
    """data/manual.csv: 회사명,항목,값  (예: 홍길동바이오,offer_price,15000)"""
    out = defaultdict(dict)
    p = DATA / "manual.csv"
    if p.exists():
        for row in csv.DictReader(p.open(encoding="utf-8-sig")):
            if row.get("회사명") and row.get("항목"):
                v = row.get("값", "").strip()
                out[norm_name(row["회사명"])][row["항목"].strip()] = to_int(v) if v.replace(",", "").isdigit() else v
    return out


def price_returns(code, offer, first_close_38):
    rows = read_json(PRICES / f"{code}.json", []) if code else []
    if not rows or not offer:
        return {}, None, None, None
    # 무상증자 등으로 수정주가가 적용되면 공모가와 비교가 틀어지므로 38 의 첫날 종가로 보정
    f = 1.0
    if first_close_38 and rows[0][4] and abs(first_close_38 / rows[0][4] - 1) > 0.02:
        f = first_close_38 / rows[0][4]
    cl = [r[4] * f for r in rows]
    at = lambda i: round(cl[i] / offer - 1, 4) if len(cl) > i else None
    ret = {"open": round(rows[0][1] * f / offer - 1, 4) if rows[0][1] else None,
           "d1": at(0), "w1": at(4), "m1": at(19), "m3": at(59)}
    recent = date.fromisoformat(f"{rows[-1][0][:4]}-{rows[-1][0][4:6]}-{rows[-1][0][6:]}") >= TODAY - timedelta(days=10)
    cur = round(cl[-1]) if recent else None
    peak = round(max(cl[:250]) / offer - 1, 4)
    return ret, cur, peak, f


def band_pos(offer, band):
    if not offer or not band or not band[1]:
        return None
    lo, hi = band
    if offer > hi:
        return "above"
    if offer == hi:
        return "top"
    if offer < lo:
        return "below"
    if offer == lo:
        return "bottom"
    return "within"


def estk_parse(groups):
    """DART estkRs 응답에서 가장 최근 신고서 기준 값만 추린다."""
    if not groups:
        return None
    out = {}
    for g in groups:
        lst = g.get("list") or []
        if not lst:
            continue
        last = max(x["rcept_no"] for x in lst)
        out[g["title"]] = [{k: v for k, v in x.items() if k not in ("corp_cls", "corp_code", "corp_name")}
                           for x in lst if x["rcept_no"] == last]
    return out


def make_id(rec):
    if rec.get("code"):
        return rec["code"]
    if rec.get("corp_code"):
        return "C" + rec["corp_code"]
    return "N" + hashlib.md5(rec["key"].encode()).hexdigest()[:8]


def build():
    inv, pub, lst, sched, fc, listed38, dart = load()
    s38 = merge38(sched, fc, listed38)
    by_name38 = {}
    for no, d in sorted(s38.items(), key=lambda t: int(t[0] or 0)):
        by_name38[norm_name(d.get("name"))] = d
    by_dl38 = {(d.get("listing_date"), d.get("offer_price")): d for d in s38.values() if d.get("listing_date")}
    dart_by_name, dart_by_code = {}, {}
    for cc, d in dart.items():
        dart_by_name[norm_name(d["corp_name"])] = d
        if d.get("stock_code"):
            dart_by_code[d["stock_code"]] = d
    manual = load_manual()

    recs = {}

    def rec(name):
        k = norm_name(name)
        if k not in recs:
            recs[k] = {"key": k, "name": name}
        return recs[k]

    for x in sorted(inv, key=lambda x: x["apply_date"] or ""):
        if x["list_type"] == "재상장":  # 인적분할 등 재상장은 공모가 아니므로 제외
            continue
        r = rec(x["name"])
        r["invstg"] = x  # 같은 회사가 재청구한 경우 가장 최근 청구 건이 남는다
    for x in pub:
        rec(x["name"])["pub"] = x
    for x in lst:
        r = rec(x["name"])
        r["kl"] = x
        d = by_name38.get(r["key"]) or by_dl38.get((x["listing_date"], x["offer_price"]))
        if d:
            r["s38"] = d
    used = {id(r["s38"]) for r in recs.values() if r.get("s38")}
    for k, d in by_name38.items():
        when = d.get("listing_date") or d.get("sub_start") or d.get("forecast_date") or ""
        if when < START.isoformat() or id(d) in used:
            continue
        if k in recs:
            recs[k]["s38"] = d
            continue
        # 38 은 회사명을 줄여 쓰기도 한다 → 앞부분이 같고 주관사도 같은 미매칭 기업 하나만 연결
        uw = (d.get("uw") or "")[:2]
        cand = [r for rk, r in recs.items() if not r.get("s38") and not r.get("kl") and len(k) >= 2
                and (rk.startswith(k) or k.startswith(rk))
                and uw and ((r.get("invstg") or r.get("pub") or {}).get("underwriter") or "").startswith(uw)]
        if len(cand) == 1:
            cand[0]["s38"] = d
        else:
            rec(d["name"].replace("(유가)", "").strip())["s38"] = d

    items, details = [], {}
    for k, r in recs.items():
        inv_, pub_, kl, d38 = r.get("invstg"), r.get("pub"), r.get("kl"), r.get("s38") or by_name38.get(k) or {}
        kcode = (kl or {}).get("code")
        dt = (dart_by_code.get(kcode) if valid_code(kcode) else None) or dart_by_name.get(k) or {}
        m = manual.get(k, {})
        name = (kl or pub_ or inv_ or {}).get("name") or d38.get("name", "").split("(")[0].strip()
        market = (kl or pub_ or inv_ or {}).get("market") or ("KOSPI" if d38.get("kospi") else "KOSDAQ")
        list_type = (inv_ or {}).get("list_type", "")
        security = (kl or {}).get("security", "")

        if "스팩" in list_type:
            method = "spac_merge"
        elif SPAC_RE.search(name):
            method = "spac"
        elif "리츠" in name or security in ("부동산투자회사", "사회간접자본투융자회사") or "인프라" in name:
            method = "reit"
        elif "이전" in list_type or (kl or {}).get("list_type") == "이전상장":
            method = "transfer"
        else:
            method = "general"

        listing_date = m.get("listing_date") or (kl or {}).get("listing_date") or (pub_ or {}).get("listing_date") \
            or d38.get("listing_date")
        offer = m.get("offer_price") or (kl or {}).get("offer_price") or (pub_ or {}).get("offer_price") \
            or d38.get("offer_price")
        band = d38.get("band")
        amount = ((kl or {}).get("offer_amount") or 0) * 1000 or ((pub_ or {}).get("offer_amount_mil") or 0) * 1e6 \
            or (d38.get("amount_mil") or 0) * 1e6 or None
        if amount is None and offer and dt.get("estk"):
            pass
        forecast = (pub_ or {}).get("forecast") or [d38.get("forecast_date")] * 2
        subscription = (pub_ or {}).get("subscription") or [d38.get("sub_start"), d38.get("sub_end")]
        filings = dt.get("filings") or []
        withdrawn_dart = bool(filings) and "철회" in filings[-1][1]

        # ---- 진행 단계 판정 ----
        res = (inv_ or {}).get("result", "")
        if kl and listing_date and listing_date <= T:
            stage = "listed"
        elif res == "상장승인" and method == "spac_merge":
            stage = "listed"
        elif (listing_date and listing_date > T) or (pub_ and not kl) or (subscription[1] and subscription[1] >= T):
            stage = "withdrawn" if withdrawn_dart else "offering"
        elif res in WITHDRAWN or withdrawn_dart:
            stage = "withdrawn"
        elif res == "심사승인":
            stage = "approved"
        elif res == "청구서접수":
            stage = "review"
        elif res == "상장승인" or (d38.get("listing_date") and d38["listing_date"] <= T):
            stage = "listed"
        else:
            stage = "offering" if filings else "review"
        if m.get("stage") in STAGES:
            stage = m["stage"]

        ref = listing_date or (inv_ or {}).get("apply_date") or subscription[0] or forecast[0] or ""
        if ref < START.isoformat():
            continue
        if method == "transfer" and not offer:  # 코스닥→코스피 이전 등 공모 없는 이전상장 제외
            continue

        code = kcode if valid_code(kcode) else (dt.get("stock_code") or None)
        ret, cur, peak, adj = price_returns(code, offer, d38.get("first_close")) if stage == "listed" else ({}, None, None, None)
        it = {
            "key": k, "name": name, "market": market, "stage": stage, "method": method,
            "code": code, "corp_code": dt.get("corp_code"),
            "apply_date": (inv_ or {}).get("apply_date"), "result": res or None,
            "result_date": (inv_ or {}).get("result_date"),
            "filing_date": (pub_ or {}).get("filing_date") or (next((f[0] for f in filings if "증권신고서" in f[1]), None)),
            "forecast_date": forecast[0], "forecast_end": forecast[1],
            "sub_start": subscription[0], "sub_end": subscription[1],
            "listing_date": listing_date,
            "band": band, "offer_price": offer, "band_pos": band_pos(offer, band),
            "offer_amount": amount,
            "inst_comp": m.get("inst_comp") or d38.get("inst_comp"), "lockup_pct": d38.get("lockup_pct"),
            "sub_comp": d38.get("sub_comp"),
            "underwriter": (kl or pub_ or inv_ or {}).get("underwriter") or d38.get("uw"),
            "industry": (kl or {}).get("industry"), "product": (kl or {}).get("product"),
            "listed_shares": (kl or {}).get("listed_shares"),
            "ret": ret, "cur_price": cur, "peak_ret": peak,
            "no38": d38.get("no"), "kind_id": (inv_ or {}).get("kind_id"),
            "dart_rcept": filings[-1][2] if filings else None,
        }
        it["id"] = make_id(it)
        items.append(it)
        details[it["id"]] = {"filings": filings, "estk": estk_parse(dt.get("estk")), "fin": dt.get("fin"),
                             "price_adj": adj}
    return items, details


def quarter(d):
    return f"{d[:4]}Q{(int(d[5:7]) - 1) // 3 + 1}"


def stats(items):
    listed = [x for x in items if x["stage"] == "listed" and x["listing_date"]]
    core = [x for x in listed if x["method"] in ("general", "transfer")]

    # 월별 상장 건수 (최근 24개월, 스팩 공모 제외)
    months = []
    y, mth = TODAY.year, TODAY.month
    for _ in range(24):
        months.append(f"{y:04d}-{mth:02d}")
        y, mth = (y, mth - 1) if mth > 1 else (y - 1, 12)
    months.reverse()
    monthly = {mo: {"KOSPI": 0, "KOSDAQ": 0} for mo in months}
    for x in listed:
        mo = x["listing_date"][:7]
        if mo in monthly and x["method"] != "spac":
            monthly[mo][x["market"]] = monthly[mo].get(x["market"], 0) + 1

    # 분기별 시장 온도
    qs = defaultdict(list)
    for x in core:
        if x.get("offer_price"):
            qs[quarter(x["listing_date"])].append(x)
    quarterly = []
    for q in sorted(qs):
        g = qs[q]
        d1 = sorted(x["ret"]["d1"] for x in g if x["ret"].get("d1") is not None)
        m3 = [x["ret"]["m3"] for x in g if x["ret"].get("m3") is not None]
        ic = [x["inst_comp"] for x in g if x.get("inst_comp")]
        top = [x for x in g if x.get("band_pos")]
        med = d1[len(d1) // 2] if d1 else None
        quarterly.append({
            "q": q, "n": len(g),
            "inst_comp": round(sum(ic) / len(ic), 1) if ic else None,
            "top_ratio": round(sum(x["band_pos"] in ("top", "above") for x in top) / len(top), 3) if top else None,
            "d1_avg": round(sum(d1) / len(d1), 4) if d1 else None, "d1_med": med,
            "m3_win": round(sum(v > 0 for v in m3) / len(m3), 3) if m3 else None,
            "temp": None if med is None else ("과열" if med >= 1 else "활황" if med >= 0.5 else
                                               "보통" if med >= 0.15 else "냉각"),
        })

    # 향후 3주 일정
    end = (TODAY + timedelta(days=21)).isoformat()
    events = []
    for x in items:
        if x["stage"] in ("withdrawn",):
            continue
        for kind, s, e in (("수요예측", x["forecast_date"], x["forecast_end"]),
                           ("청약", x["sub_start"], x["sub_end"]),
                           ("상장", x["listing_date"], x["listing_date"])):
            if s and (e or s) >= T and s <= end:
                events.append({"id": x["id"], "name": x["name"], "market": x["market"], "type": kind,
                               "start": s, "end": e or s, "method": x["method"]})
    events.sort(key=lambda e: (e["start"], e["type"]))
    return monthly, quarterly, events


def main():
    items, details = build()
    pool = model.build_pool(items)
    bt = []
    for x in items:
        if x["method"] in ("spac", "spac_merge", "reit") or x["stage"] == "withdrawn":
            continue
        p = model.predict(x, pool)
        if p:
            x["prob"] = p["prob"].get("m3")
            x["prob_prior"] = p["prior"]
            details[x["id"]]["model"] = p
            if x in pool and not p["prior"] and x["listing_date"] >= (TODAY - timedelta(days=730)).isoformat():
                bt.append((p["prob"].get("m3"), x["ret"]["m3"] > 0))
    monthly, quarterly, events = stats(items)

    det_dir = DATA / "detail"
    if det_dir.exists():
        shutil.rmtree(det_dir)
    for x in items:
        write_json(det_dir / f"{x['id']}.json", {**details[x["id"]], "item": x})

    bt = [(p, y) for p, y in bt if p is not None]
    backtest = {
        "n": len(bt),
        "brier": round(sum((p - y) ** 2 for p, y in bt) / len(bt), 4) if bt else None,
        "acc": round(sum((p >= 0.5) == y for p, y in bt) / len(bt), 3) if bt else None,
        "base": round(sum(y for _, y in bt) / len(bt), 3) if bt else None,
    }
    counts = {s: sum(x["stage"] == s for x in items) for s in STAGES}
    meta = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "today": T, "counts": counts,
            "monthly": monthly, "quarterly": quarterly, "events": events, "backtest": backtest}
    items.sort(key=lambda x: x.get("listing_date") or x.get("sub_start") or x.get("apply_date") or "", reverse=True)
    write_json(DATA / "ipos.json", items)
    write_json(DATA / "meta.json", meta, indent=1)
    print(f"파이프라인 완료: {len(items)}개 기업 {counts} / 모델 검증 {backtest}")


if __name__ == "__main__":
    main()
