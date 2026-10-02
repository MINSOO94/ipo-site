"""유사사례 기반 수익 확률 모델.

과거 상장 사례 중 '수요예측 결과가 비슷한' 기업들을 골라,
그 기업들이 상장 후 각 시점에 공모가보다 높았던 비율을 확률로 쓴다.

특징값: 기관경쟁률(log), 의무보유확약 비율, 공모가의 밴드 내 위치, 시장(코스피/코스닥), 공모규모(log)
- 미래 정보 누수를 막기 위해, 대상 기업의 기준일 이전에 3개월이 지난 사례만 사용한다.
"""
import math
from datetime import date, timedelta

HORIZONS = [("d1", "상장일"), ("w1", "1주"), ("m1", "1개월"), ("m3", "3개월")]
K = 25


def features(x):
    if x.get("inst_comp") is None or not x.get("offer_price"):
        return None
    band = x.get("band") or [x["offer_price"], x["offer_price"]]
    hi = band[1] or x["offer_price"]
    return [
        math.log1p(x["inst_comp"]),
        (x.get("lockup_pct") or 0) / 10,
        (x["offer_price"] / hi - 1) * 10 if hi else 0,
        1.0 if x.get("market") == "KOSDAQ" else 0.0,
        math.log10(max(x.get("offer_amount") or 1e9, 1e8)),
    ]


def build_pool(items):
    return [x for x in items
            if x.get("stage") == "listed" and x.get("method") in ("general", "transfer")
            and x.get("ret", {}).get("m3") is not None and features(x)]


def _scale(pool_f):
    n = len(pool_f)
    cols = list(zip(*pool_f))
    mu = [sum(c) / n for c in cols]
    sd = [max((sum((v - m) ** 2 for v in c) / n) ** 0.5, 1e-6) for c, m in zip(cols, mu)]
    return mu, sd


def predict(target, pool):
    """target 과 비슷한 과거 사례 K개로 시점별 '공모가 초과' 확률을 계산."""
    f = features(target)
    ref = target.get("listing_date") or target.get("forecast_date") or date.today().isoformat()
    cutoff = (date.fromisoformat(ref) - timedelta(days=95)).isoformat()
    cand = [x for x in pool if x["listing_date"] <= cutoff and x is not target]
    if len(cand) < K:
        return None
    if f is None:
        # 수요예측 전: 같은 시장의 최근 1년 사례 평균을 기준 확률로 사용
        since = (date.fromisoformat(cutoff) - timedelta(days=365)).isoformat()
        near = [x for x in cand if x["listing_date"] >= since and x.get("market") == target.get("market")] \
            or [x for x in cand if x["listing_date"] >= since]
        if len(near) < 10:
            return None
        return _summary(near, prior=True)
    cf = [features(x) for x in cand]
    mu, sd = _scale(cf)
    z = lambda v: [(a - m) / s for a, m, s in zip(v, mu, sd)]
    tz = z(f)
    dist = sorted(((sum((a - b) ** 2 for a, b in zip(tz, z(v))) ** 0.5, x) for v, x in zip(cf, cand)),
                  key=lambda t: t[0])[:K]
    return _summary([x for _, x in dist], prior=False)


def _summary(cases, prior):
    out = {"prior": prior, "n": len(cases), "prob": {}, "median": {}}
    for h, _ in HORIZONS:
        vals = sorted(x["ret"][h] for x in cases if x["ret"].get(h) is not None)
        if vals:
            out["prob"][h] = round(sum(v > 0 for v in vals) / len(vals), 3)
            out["median"][h] = round(vals[len(vals) // 2], 4)
    if not prior:
        out["cases"] = [{"id": x["id"], "name": x["name"], "listing_date": x["listing_date"],
                         "inst_comp": x.get("inst_comp"), "lockup_pct": x.get("lockup_pct"),
                         "d1": x["ret"].get("d1"), "m3": x["ret"].get("m3")} for x in cases[:10]]
    return out
