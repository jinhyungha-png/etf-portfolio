# ETF Portfolio

미국 ETF 바벨 포트폴리오(코어 ~50% + 저상관 위성) 조사·계획·시뮬레이터 저장소.

| 파일 | 내용 |
|---|---|
| [portfolio-dashboard.html](portfolio-dashboard.html) | 대화형 시뮬레이터. 비중을 조절해 CAGR·변동성·MDD·상관·거시 레짐별 성과를 비교 |
| [fetch_portfolio_data.py](fetch_portfolio_data.py) | yfinance로 20개 티커 월간 종가를 받아 대시보드용 `window.PRICES` 생성 |
| [sector-etf-research.md](sector-etf-research.md) | zero-base 섹터·ETF 조사 |
| [etf-portfolio-plan.md](etf-portfolio-plan.md) | 목표 배분 3안 + repo/collar 유동화 실행 계획 |

## 실제 데이터로 교체

대시보드는 기본적으로 각 ETF의 대략적 수익·변동성·상관 특성을 반영한 **합성(예시) 데이터**로 동작한다
(상단 배너가 노란색). 실제 가격으로 바꾸려면:

```
pip install yfinance pandas
python fetch_portfolio_data.py --inject portfolio-dashboard.html
```

배너가 초록색 "실제 가격 데이터"로 바뀌면 성공이다.

같은 명령을 다시 실행하면 **실행일 기준 가장 최근 거래일까지** 기간이 자동으로 늘어난다
(대시보드 파일을 고칠 필요 없음). 진행 중인 달은 부분월로 표시되며, 완결된 달까지만 원하면
`--end 2026-08` 처럼 끝 월을 지정한다.

> 투자자문이 아닙니다. 모든 수치는 조사 시점의 대략치이며, 집행 전 각 운용사 팩트시트와
> 세무·증권사 확인이 필요합니다.
