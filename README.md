# IPO 동향 분석

국내 공모주(코스피·코스닥 일반상장·이전상장·스팩합병, 2020년~)의 진행 상황을 단계별로 보여주는 사이트입니다.
예비심사 → 승인 → 공모 → 상장 → 철회·미승인까지 한눈에 보고, 향후 3주 일정, 월별 상장 건수,
분기별 시장 온도, 기업별 공모 개요·자금 사용 목적·재무·상장 후 주가·유사 사례 기반 수익 확률을 제공합니다.

데이터: KIND(한국거래소) · 38커뮤니케이션 · DART · 네이버 금융 — 평일 16:40(KST) 자동 갱신.

## 처음 설정
1. DART 인증키 발급: https://opendart.fss.or.kr (무료)
2. 로컬: `.env.example` 을 `.env` 로 복사하고 키 입력
3. GitHub: Settings → Secrets and variables → Actions → `DART_API_KEY` 등록
4. GitHub: Settings → Pages → Source 를 **GitHub Actions** 로
5. Actions 탭 → "데이터 업데이트 & 배포" → Run workflow

## 로컬 실행
```
pip install -r scripts/requirements.txt
python scripts/update.py
python -m http.server 8000
```

## 수동 보정
자동 수집이 틀린 값은 `data/manual.csv` 에 `회사명,항목,값` 으로 적으면 우선 적용됩니다.

> 수익 확률은 과거 유사 사례 통계이며 투자 권유가 아닙니다.
