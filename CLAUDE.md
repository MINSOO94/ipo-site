# IPO 동향 분석 사이트

국내 공모주(코스피·코스닥, 2020년~)를 KIND·38커뮤니케이션·DART·네이버 금융에서 매일 수집해
GitHub Pages 정적 사이트로 보여준다. 서버 없음: 파이썬이 `data/*.json`을 만들고 `index.html`이 읽는다.

## 구조
- `scripts/common.py` 경로·HTTP 세션(재시도)·회사명 정규화(`norm_name`)·숫자 파싱
- `scripts/kind.py` KIND 예비심사 / 공모진행 / 신규상장 (POST, `currentPageSize=3000`)
- `scripts/s38.py` 38커뮤니케이션 청약일정(o=k) / 수요예측(o=r1) / 신규상장(o=nw)
- `scripts/dart.py` DART C001 공시목록 → estkRs(공모개요·자금용도) + fnlttSinglAcnt(재무). 캐시: `data/raw/dart_ipo.json`
- `scripts/prices.py` 네이버 `siseJson` 일별 시세 → `data/prices/{코드}.json`
- `scripts/model.py` 유사사례(KNN, K=25) 공모가 초과 확률
- `scripts/pipeline.py` 전부 합쳐 `data/ipos.json`, `data/meta.json`, `data/detail/{id}.json` 생성
- `scripts/update.py` 위 순서대로 전체 실행 (출처별 실패/건수 급감 시 이전 데이터로 복구)
- `index.html` 화면 전체(CSS·JS 인라인, 외부 라이브러리 없음, 차트는 직접 그린 SVG)
- `.github/workflows/update.yml` 평일 16:40 KST 자동 수집 → 커밋 → Pages 배포

## 실행
```
python scripts/update.py              # 전체 수집 + 생성
python scripts/update.py pipeline     # 수집 없이 화면 데이터만 재생성
python -m http.server 8000            # 로컬 미리보기 (file:// 로 열면 fetch 가 안 됨)
```

## 규칙
- 답변은 한국어로.
- API 키는 `.env`(로컬) / GitHub Secrets `DART_API_KEY`(Actions)에만. 코드·커밋에 절대 넣지 않는다.
- 38.co.kr 은 오래된 TLS 라 **http** 로, 인코딩 **EUC-KR**.
- 스크래핑은 요청 사이 0.7~1초 쉬기. 새 수집기/수정 후에는 반드시 실행해서 건수 확인.
- 출처 간 매칭 키: 정규화된 회사명. 상장사는 종목코드로 DART 와 매칭(사명 변경 대응).
  이름 앞부분만 같은 회사는 다른 회사일 수 있다(예: 영광 ≠ 영광와이케이엠씨) — 느슨한 매칭 추가 시 주의.
- 자동 수집이 틀리거나 빠진 값은 `data/manual.csv`(회사명,항목,값)로 보정.
  항목: offer_price, listing_date, inst_comp, stage(review/approved/offering/listed/withdrawn)
- 화면 색: 상승=빨강(`--up`), 하락=파랑(`--down`) 한국식. 색은 `:root` 토큰으로만, 다크모드 지원 유지.

## 알려진 한계
- DART estkRs 는 공모가 확정 전 신고서 기준 값(밴드 하단)일 수 있음.
- 재무는 상장 후 사업보고서 기준만 자동 수집(상장 전 재무는 증권신고서 원문 파싱 필요).
- 스팩합병 상장은 상장일·종목코드가 없어 수익률 미계산.
- 외국기업(DR) 일부는 종목코드를 못 찾아 주가 없음.
