# -*- coding: utf-8 -*-
"""
광고 성과 ETL 공용 로직 (로컬 실행 + 웹 업로드 app.py 가 함께 사용)

대상 광고채널 4종:
    - 네이버 검색광고 (파워링크/성과형 검색 등)
    - 네이버 디스플레이 (GFA / 성과형 디스플레이)
    - 쿠팡 광고
    - 메타 광고 (Ads Manager 내보내기)

핵심 함수:
    parse_ad_source(filename, source) -> DataFrame[광고채널, 주차, 광고비, 광고매출]
        - filename 으로 광고채널을 판별한다.
        - 헤더행/컬럼명을 자동 탐지해 광고비·광고매출·날짜 컬럼을 찾는다.
        - 날짜 컬럼이 있으면 행별로 'N주차'로 묶고, 없으면 파일명 날짜범위로 한 주차에 합산한다.
        - source 는 파일 경로(str) 또는 업로드된 파일 객체(BytesIO 등) 모두 가능.
    merge_ads(existing, new) -> DataFrame
        - new 에 들어있는 (광고채널, 주차) 조합은 통째로 교체(최신 업로드 우선)하여 병합.

ROAS 는 저장하지 않고 화면에서 광고매출/광고비 로 계산한다(집계 후 계산이 정확).
"""
import io
import csv
import pandas as pd

# 주차 계산·숫자 정리 로직은 매출 ETL 과 공유한다.
from etl_core import week_of, week_from_filename, _num, WEEK_ORDER, WEEK_RANGE  # noqa: F401

ADS_TIDY_COLS = ["광고채널", "주차", "광고비", "광고매출"]

AD_CHANNELS = ["네이버 검색광고", "네이버 디스플레이", "쿠팡 광고", "메타 광고"]


# ------------------------------------------------------------- 채널 판별
def detect_ad_channel(fname):
    """파일명으로 광고채널 판별. (디스플레이/메타를 네이버 일반보다 먼저 검사)"""
    raw = str(fname)
    n = raw.replace(" ", "").lower()
    if any(k in raw for k in ("메타", "페이스북", "인스타")) or \
       any(k in n for k in ("meta", "facebook", "instagram", "insight", "인사이트")):
        return "메타 광고"
    if "쿠팡" in raw or "coupang" in n:
        return "쿠팡 광고"
    if any(k in raw for k in ("디스플레이", "성과형", "배너")) or \
       any(k in n for k in ("gfa", "nosp", "display", "dp")):
        return "네이버 디스플레이"
    if "검색" in raw or "파워링크" in raw or "네이버" in raw or "naver" in n:
        return "네이버 검색광고"
    return None


# ------------------------------------------------------------- 컬럼 탐지 설정
# 각 채널별로 우선순위 순서대로 컬럼명을 찾는다(부분일치, 공백/대소문자 무시).
# 광고매출은 "전환매출/전환값" 을 우선하고, 마지막에 일반적인 '매출' 로 폴백한다.
_COL_HINTS = {
    "네이버 검색광고": {
        "cost": ["총비용", "광고비", "비용", "지출"],
        "rev":  ["전환매출액", "전환매출", "전환금액", "직접전환매출", "매출"],
        "date": ["날짜", "일자", "기준일", "일별", "기간"],
    },
    "네이버 디스플레이": {
        "cost": ["광고비", "총비용", "비용", "지출"],
        "rev":  ["전환매출", "전환값", "전환금액", "구매전환값", "매출"],
        "date": ["일자", "날짜", "기준일", "일별", "기간"],
    },
    "쿠팡 광고": {
        # 광고매출은 '14일 전환' 기준(총 전환매출액(14일))을 우선한다. (1일 컬럼 먼저 잡지 않도록)
        "cost": ["광고비", "집행광고비", "비용", "지출"],
        "rev":  ["총전환매출액(14일)", "총전환매출(14일)", "전환매출액(14일)",
                 "총전환매출액", "광고전환매출", "전환매출액", "전환매출", "판매금액", "매출"],
        "date": ["날짜", "일자", "노출일", "기준일", "기간"],
    },
    "메타 광고": {
        "cost": ["지출금액", "지출", "비용", "amountspent", "spend", "cost"],
        "rev":  ["구매전환값", "웹사이트구매전환값", "전환값", "구매전환가치",
                 "purchasesconversionvalue", "conversionvalue", "purchasevalue", "매출"],
        "date": ["일", "날짜", "day", "date", "보고시작", "reportingstarts", "기간"],
    },
}

# 헤더행 자동 탐지에 쓰는 힌트(이 단어들이 2개 이상 있는 행을 헤더로 본다).
_HEADER_HINTS = ["광고비", "총비용", "비용", "지출", "cost", "spend",
                 "전환매출", "전환값", "구매전환값", "roas",
                 "날짜", "일자", "기준일", "day", "date",
                 "캠페인", "campaign", "노출", "클릭", "상품", "광고그룹"]


def _norm(s):
    return str(s).replace(" ", "").replace("\n", "").lower()


def _raw_frame(filename, source):
    """헤더 없이(header=None) 전체를 읽어온다. csv/xlsx/xls, 인코딩·가변칸수 자동."""
    name = str(filename).lower()
    if name.endswith(".csv"):
        data = source.read() if hasattr(source, "read") else open(source, "rb").read()
        text = None
        for enc in ("utf-8-sig", "cp949", "utf-16", "utf-8"):
            try:
                text = data.decode(enc)
                break
            except Exception:
                continue
        if text is None:
            raise ValueError("CSV 인코딩을 인식하지 못했습니다(utf-8/cp949/utf-16).")
        # 광고 리포트 CSV 는 상단 제목행·요약행 등으로 행마다 칸 수가 다를 수 있어
        # pandas 대신 csv 모듈로 읽고 최대 칸수에 맞춰 패딩한다.
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            return pd.DataFrame()
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        return pd.DataFrame(rows, dtype=str)
    eng = "xlrd" if name.endswith(".xls") else "openpyxl"
    return pd.read_excel(source, sheet_name=0, header=None, engine=eng, dtype=str)


def _find_header_row(raw):
    """상단 15행 중 힌트 단어가 2개 이상 들어있는 첫 행을 헤더로 판단."""
    for i in range(min(15, len(raw))):
        cells = [_norm(x) for x in raw.iloc[i].tolist() if pd.notna(x)]
        hits = sum(1 for h in _HEADER_HINTS if any(h in c for c in cells))
        if hits >= 2:
            return i
    return 0


def _find_col(columns, keys):
    """keys 우선순위대로 부분일치하는 컬럼명을 반환(없으면 None)."""
    norm = {c: _norm(c) for c in columns}
    for k in keys:
        kk = _norm(k)
        for c in columns:
            if kk and kk in norm[c]:
                return c
    return None


# ------------------------------------------------------------- 파서
def parse_ad_source(filename, source):
    """filename 으로 채널 판별 후 tidy DataFrame[광고채널,주차,광고비,광고매출] 반환."""
    ch = detect_ad_channel(filename)
    if ch is None:
        raise ValueError(f"광고채널을 인식할 수 없는 파일명입니다: {filename} "
                         f"(파일명에 네이버/검색/디스플레이/쿠팡/메타 중 하나가 들어가야 합니다)")

    raw = _raw_frame(filename, source)
    if raw.empty:
        return pd.DataFrame(columns=ADS_TIDY_COLS)

    hdr = _find_header_row(raw)
    header = [str(x).strip() for x in raw.iloc[hdr].tolist()]
    df = raw.iloc[hdr + 1:].copy()
    df.columns = header
    df = df.loc[:, [c for c in df.columns if c and c.lower() != "nan"]]

    hints = _COL_HINTS[ch]
    cost_col = _find_col(df.columns, hints["cost"])
    rev_col = _find_col(df.columns, hints["rev"])
    date_col = _find_col(df.columns, hints["date"])

    if cost_col is None:
        raise ValueError(f"{filename}: 광고비 컬럼을 찾지 못했습니다. "
                         f"열 후보={list(df.columns)[:15]}")

    df["_cost"] = _num(df[cost_col])
    df["_rev"] = _num(df[rev_col]) if rev_col else 0.0

    # 합계/소계 등 텍스트 요약행 제거: 광고비가 숫자가 아닌(=0) 행 중 날짜도 없는 행은 버린다.
    if date_col is not None:
        wk = pd.to_datetime(df[date_col], errors="coerce").map(week_of)
        # 날짜 파싱 실패 행이 많으면(요약행/기간표기) 파일명 주차로 폴백
        if wk.notna().sum() == 0:
            date_col = None
        else:
            df["_주차"] = wk

    if date_col is None:
        wk = week_from_filename(filename)
        if wk is None:
            raise ValueError(f"{filename}: 날짜 컬럼도 없고 파일명에서 주차(MMDD-MMDD)도 "
                             f"인식하지 못했습니다. 파일명에 기간을 넣어 주세요.")
        df["_주차"] = wk

    g = (df[df["_주차"].notna()]
         .groupby("_주차", as_index=False)
         .agg(광고비=("_cost", "sum"), 광고매출=("_rev", "sum")))
    g["광고채널"] = ch
    out = g[["광고채널", "_주차", "광고비", "광고매출"]].rename(columns={"_주차": "주차"})
    out = out[out["광고비"] != 0].copy()
    return out[ADS_TIDY_COLS]


def merge_ads(existing, new):
    """new 에 들어있는 (광고채널, 주차) 조합은 기존에서 제거하고 new 로 대체."""
    if existing is None or existing.empty:
        return new.copy()
    if new is None or new.empty:
        return existing.copy()
    keys = set(map(tuple, new[["광고채널", "주차"]].drop_duplicates().values))
    mask = existing.apply(lambda r: (r["광고채널"], r["주차"]) in keys, axis=1)
    kept = existing[~mask]
    return pd.concat([kept, new], ignore_index=True)[ADS_TIDY_COLS]
