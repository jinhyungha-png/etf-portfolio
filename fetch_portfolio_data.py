#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_portfolio_data.py — portfolio-dashboard.html 용 실제 가격 데이터 수집기

20개 ETF의 월간 조정 종가(adjusted close)를 yfinance로 내려받아
대시보드가 그대로 읽을 수 있는 `window.PRICES` 블록을 생성한다.

대시보드(portfolio-dashboard.html)의 데이터 계약
------------------------------------------------
    window.PRICES = { "<TICKER>": [ <138개 값>, ... ], ... }

    - 배열 인덱스 0 = 2015-01, 인덱스 137 = 2026-06 (총 138개월, 고정 격자)
    - 상장 이전(또는 데이터 없음) 구간은 반드시 null
    - 값은 배당 재투자를 반영한 조정종가. 대시보드는 월간 수익률
      (a[t]/a[t-1]-1)만 사용하므로 절대 수준·스케일은 의미가 없다.
    - window.PRICES 가 존재하면 대시보드는 내장 합성 데이터를 버리고 실제
      데이터를 쓰며, 상단 배너가 "실제 가격 데이터"(초록)로 바뀐다.

사용법
------
    pip install yfinance pandas
    python fetch_portfolio_data.py                          # prices.json + prices.js
    python fetch_portfolio_data.py --inject portfolio-dashboard.html
    python fetch_portfolio_data.py --start 2015-01 --end 2026-06 --out-dir data/

--inject 를 주면 대시보드 HTML 안에 window.PRICES 블록을 직접 삽입/교체한다
(기존 블록이 있으면 덮어씀). 원본은 .bak 으로 백업한다.

주의: 사내망/방화벽 환경에서는 Yahoo Finance 접속이 막혀 있을 수 있다.
네트워크가 열린 PC에서 실행한 뒤 prices.js 만 옮겨 붙여도 된다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from pathlib import Path

# Windows 콘솔 기본 인코딩(cp949/cp1252)에서는 한글 출력이 UnicodeEncodeError 로 죽는다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass

# ---------------------------------------------------------------------------
# 유니버스 — portfolio-dashboard.html 의 UNIVERSE 배열과 티커/순서를 맞춘다.
# (세 번째 항목 = 대시보드 좌측 레일의 카테고리 그룹)
# ---------------------------------------------------------------------------
UNIVERSE = [
    ("VOO", "S&P500", "코어"),
    ("QQQM", "NASDAQ100", "코어"),
    ("SCHD", "배당성장", "코어"),
    ("USMV", "최소변동성", "코어"),
    ("SMH", "반도체·AI", "기술"),
    ("IGV", "소프트웨어", "기술"),
    ("IBIT", "비트코인(현물)", "기술"),
    ("XBI", "바이오테크", "헬스"),
    ("SLIM", "GLP-1·비만", "헬스"),
    ("XLU", "유틸리티(발전·송배전)", "전력·에너지"),
    ("GRID", "전력망·전기장비", "전력·에너지"),
    ("URA", "우라늄·원자력", "전력·에너지"),
    ("TAN", "태양광", "전력·에너지"),
    ("GLDM", "금", "원자재"),
    ("COPX", "구리 광산", "원자재"),
    ("PDBC", "광범위 원자재", "원자재"),
    ("ITA", "방위산업", "방위"),
    ("INDA", "인도", "지역"),
    ("AVUV", "미국 소형가치", "팩터"),
    ("DBMF", "관리형 선물", "헤지"),
]

TICKERS = [t for t, _, _ in UNIVERSE]

DEFAULT_START = "2015-01"
DEFAULT_END = "2026-06"

INJECT_START = "<!-- BEGIN real-prices (fetch_portfolio_data.py) -->"
INJECT_END = "<!-- END real-prices -->"


# ---------------------------------------------------------------------------
# 월 격자 유틸
# ---------------------------------------------------------------------------
def month_key(year: int, month: int) -> str:
    return "%04d-%02d" % (year, month)


def month_grid(start: str, end: str) -> list:
    """'2015-01', '2026-06' -> ['2015-01', ..., '2026-06'] (양끝 포함)."""
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    if (ey, em) < (sy, sm):
        raise SystemExit("--end(%s) 가 --start(%s) 보다 빠릅니다." % (end, start))
    out, y, m = [], sy, sm
    while (y, m) <= (ey, em):
        out.append(month_key(y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def next_month(year: int, month: int):
    return (year + 1, 1) if month == 12 else (year, month + 1)


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------
def download_monthly(tickers: list, start: str, end: str, retries: int = 3):
    """월간 조정종가 DataFrame (index='YYYY-MM' 문자열, columns=티커) 반환."""
    try:
        import pandas as pd
        import yfinance as yf
    except ImportError as exc:
        raise SystemExit(
            "필수 패키지가 없습니다 (%s). `pip install yfinance pandas` 후 다시 실행하세요."
            % getattr(exc, "name", exc)
        )

    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    ny, nm = next_month(ey, em)  # yfinance 의 end 는 배타적
    start_date = "%04d-%02d-01" % (sy, sm)
    end_date = "%04d-%02d-01" % (ny, nm)

    last_err = None
    raw = None
    for attempt in range(1, retries + 1):
        try:
            raw = yf.download(
                tickers,
                start=start_date,
                end=end_date,
                interval="1mo",
                auto_adjust=True,  # 배당·분할 반영 -> Close 가 총수익 기준
                progress=False,
                group_by="column",
                threads=True,
            )
            break
        except Exception as exc:  # 네트워크 / 레이트리밋
            last_err = exc
            print("  [재시도 %d/%d] %s" % (attempt, retries, exc), file=sys.stderr)
    if raw is None:
        raise SystemExit("다운로드 실패: %s" % last_err)
    if raw.empty:
        raise SystemExit("Yahoo Finance 응답이 비어 있습니다. 네트워크/티커를 확인하세요.")

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw[["Close"]]
    if len(tickers) == 1:
        close.columns = list(tickers)

    # 월간 바는 월초 타임스탬프로 오므로 'YYYY-MM' 문자열로 접는다.
    close = close.copy()
    close.index = ["%04d-%02d" % (d.year, d.month) for d in close.index]
    close = close[~close.index.duplicated(keep="last")]
    return close


def to_grid(close, grid: list) -> dict:
    """DataFrame -> {ticker: [값 or None] * len(grid)}. 상장 이전 구간은 None 유지."""
    out = {}
    for tk in TICKERS:
        if tk not in close.columns:
            print("  ! %s: 데이터 없음 — 전 구간 null 로 채웁니다." % tk, file=sys.stderr)
            out[tk] = [None] * len(grid)
            continue
        col = close[tk]
        series = []
        for mk in grid:
            v = col.get(mk)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                series.append(None)
            else:
                series.append(round(float(v), 4))
        # 선행 null(상장 이전)은 그대로 두고, 중간 결측만 직전 값으로 메운다.
        first = next((i for i, v in enumerate(series) if v is not None), None)
        if first is not None:
            for i in range(first + 1, len(series)):
                if series[i] is None:
                    series[i] = series[i - 1]
        out[tk] = series
    return out


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def render_js(prices: dict, grid: list) -> str:
    body = ",\n".join(
        '  "%s": %s' % (tk, json.dumps(prices[tk], ensure_ascii=False))
        for tk in TICKERS
    )
    header = (
        "/* 자동 생성: fetch_portfolio_data.py — 손으로 고치지 마세요.\n"
        "   월 격자: %s ~ %s (%d개월), null = 상장 이전 */" % (grid[0], grid[-1], len(grid))
    )
    return "<script>\n%s\nwindow.PRICES = {\n%s\n};\n</script>\n" % (header, body)


def inject(html_path: Path, block: str) -> None:
    html = html_path.read_text(encoding="utf-8")
    payload = "%s\n%s%s\n" % (INJECT_START, block, INJECT_END)

    pattern = re.compile(
        re.escape(INJECT_START) + ".*?" + re.escape(INJECT_END) + "\n?",
        re.DOTALL,
    )
    if pattern.search(html):
        new = pattern.sub(lambda _m: payload, html)
    else:
        # 대시보드 본체 <script> 앞에 넣어야 buildPrices() 가 window.PRICES 를 본다.
        anchor = html.find('<script>\n"use strict";')
        if anchor == -1:
            anchor = html.find("<script>")
        if anchor == -1:
            raise SystemExit("%s: <script> 앵커를 찾지 못했습니다." % html_path)
        new = html[:anchor] + payload + html[anchor:]

    shutil.copyfile(str(html_path), str(html_path) + ".bak")
    html_path.write_text(new, encoding="utf-8")
    print("  주입 완료 -> %s (백업: %s.bak)" % (html_path, html_path.name))


def report(prices: dict, grid: list) -> None:
    print("\n티커별 커버리지")
    print("  %-6s%-16s%-9s%5s" % ("TK", "분류", "시작", "개월"))
    for tk, _nm, cat in UNIVERSE:
        vals = prices[tk]
        first = next((i for i, v in enumerate(vals) if v is not None), None)
        n = sum(1 for v in vals if v is not None)
        start_lbl = grid[first] if first is not None else "—"
        print("  %-6s%-16s%-9s%5d" % (tk, cat, start_lbl, n))


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="ETF 20종 월간 종가 수집 -> 대시보드용 window.PRICES 생성"
    )
    ap.add_argument("--start", default=DEFAULT_START, help="시작 월 (YYYY-MM)")
    ap.add_argument("--end", default=DEFAULT_END, help="종료 월 (YYYY-MM, 포함)")
    ap.add_argument("--out-dir", default=".", help="출력 디렉터리")
    ap.add_argument("--inject", metavar="HTML", help="이 HTML 에 window.PRICES 직접 주입")
    args = ap.parse_args()

    grid = month_grid(args.start, args.end)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("수집: %d개 티커 × %d개월 (%s ~ %s)" % (len(TICKERS), len(grid), grid[0], grid[-1]))
    close = download_monthly(TICKERS, args.start, args.end)
    prices = to_grid(close, grid)
    report(prices, grid)

    json_path = out_dir / "prices.json"
    json_path.write_text(
        json.dumps({"months": grid, "prices": prices}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print("\n  %s" % json_path)

    js_block = render_js(prices, grid)
    js_path = out_dir / "prices.js"
    js_path.write_text(js_block, encoding="utf-8")
    print("  %s" % js_path)

    if args.inject:
        inject(Path(args.inject), js_block)
    else:
        print("\n대시보드에 반영하려면:")
        print("  python fetch_portfolio_data.py --inject portfolio-dashboard.html")
        print("또는 prices.js 내용을 portfolio-dashboard.html 본체 <script> 앞에 붙여넣으세요.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
