"""여러 스크립트가 함께 쓰는 경로, HTTP 세션, 이름 정규화 함수."""
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
PRICES = DATA / "prices"
START = date(2020, 1, 1)  # 수집 시작일
TODAY = date.today()

for d in (DATA, RAW, PRICES):
    d.mkdir(parents=True, exist_ok=True)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
session = requests.Session()
session.headers.update(UA)


def http(method, url, retries=4, **kw):
    """간단한 재시도 포함 요청. 실패하면 마지막 예외를 그대로 던진다."""
    kw.setdefault("timeout", 60)
    for i in range(retries):
        try:
            r = session.request(method, url, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if i == retries - 1:
                raise
            time.sleep(3 * (i + 1))


def load_env():
    """ipo-site/.env 의 KEY=VALUE 를 환경변수로 읽는다 (이미 있는 값은 유지)."""
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, obj, indent=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent, separators=None if indent else (",", ":")),
                    encoding="utf-8")


SPAC_RE = re.compile(r"스팩|기업인수목적")


def norm_name(name):
    """출처마다 다른 회사명 표기를 비교용 키로 통일한다."""
    s = name or ""
    s = re.sub(r"\(구\.?[^)]*\)", "", s)          # (구.넵코어스)
    s = re.sub(r"\(유가\)|\(코스닥\)", "", s)
    s = re.sub(r"주식회사|\(주\)|㈜|\(유\)", "", s)
    s = s.replace("기업인수목적", "스팩").replace("엔에이치", "NH").replace("케이비", "KB")
    s = s.replace("아이비케이", "IBK").replace("에스케이", "SK").replace("디비", "DB")
    s = s.replace("에이치엠씨", "HMC").replace("비엔케이", "BNK").replace("유안타", "유안타")
    s = re.sub(r"[\s\.\-·,&()]", "", s).upper()
    # 스팩은 'KB제34호스팩' / 'KB스팩34호' 처럼 표기가 제각각 → '증권사+스팩+번호'로 통일
    m = re.search(r"(\d+)호", s)
    if "스팩" in s and m:
        brand = re.split(r"제?\d+호|스팩", s)[0]
        s = f"{brand}스팩{m.group(1)}"
    return s


CODE_RE = re.compile(r"[0-9][0-9A-Z]{5}")


def valid_code(code):
    """KIND 가 외국기업에 주는 'USA280' 같은 값은 종목코드가 아니다."""
    return bool(code and CODE_RE.fullmatch(code))


def num(s):
    """'1,234' / '12.3%' / '1136.84:1' → float. 값이 없으면 None."""
    if s is None:
        return None
    m = re.search(r"-?[\d,]*\.?\d+", str(s))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def to_int(s):
    v = num(s)
    return int(v) if v is not None else None
