"""전체 갱신: 수집(KIND → 38 → DART → 네이버) 후 파이프라인 실행.

- 한 출처가 실패해도 이전에 받아 둔 데이터로 사이트는 계속 갱신된다.
- 새로 받은 건수가 직전보다 크게 줄면(사이트 구조 변경 등) 이전 파일로 되돌린다.
사용법: python scripts/update.py            (전체)
        python scripts/update.py pipeline   (수집 없이 화면 데이터만 다시 생성)
"""
import json
import shutil
import sys
import traceback

import dart
import kind
import pipeline
import prices
import s38
from common import RAW

GUARDED = {
    "kind": ["kind_invstg.json", "kind_listing.json"],
    "38": ["38_sched.json", "38_forecast.json", "38_listed.json"],
}


def count(path):
    try:
        return len(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return 0


def run(name, fn):
    files = [RAW / f for f in GUARDED.get(name, [])]
    backup = {f: (count(f), f.with_suffix(".bak")) for f in files if f.exists()}
    for f, (_, b) in backup.items():
        shutil.copy2(f, b)
    print(f"\n=== {name} ===", flush=True)
    ok = True
    try:
        fn()
    except BaseException:
        traceback.print_exc()
        ok = False
    for f, (before, b) in backup.items():
        after = count(f)
        if not ok or after < before * 0.8:
            shutil.copy2(b, f)
            print(f"  ! {f.name}: {before} → {after}건, 이전 데이터로 복구")
        b.unlink(missing_ok=True)
    return ok


def main():
    only = sys.argv[1:]
    steps = [("kind", kind.main), ("38", s38.main), ("dart", dart.main), ("prices", prices.main)]
    failed = [n for n, fn in steps if (not only or n in only) and not run(n, fn)]
    print("\n=== pipeline ===", flush=True)
    pipeline.main()  # 파이프라인 실패는 그대로 오류로 끝낸다
    if failed:
        print(f"\n경고: 일부 수집 실패 → {', '.join(failed)} (이전 데이터 사용)")


if __name__ == "__main__":
    main()
