# -*- coding: utf-8 -*-
"""
클라리온 매출 ETL 공용 로직 (로컬 실행 etl.py + 웹 업로드 app.py 가 함께 사용)

핵심 함수:
    parse_source(filename, source) -> DataFrame[채널, 상품, 주차, 매출, 수량]
        - 상품명(브랜드 포함 원본명)은 분류(classify)에만 쓰고 저장하지 않는다(공개 노출 방지).
        - filename 으로 채널을 판별하고, 채널별 시트/양식에 맞게 파싱한다.
        - source 는 파일 경로(str) 또는 업로드된 파일 객체(BytesIO 등) 모두 가능.
    merge_tidy(existing, new) -> DataFrame
        - new 에 들어있는 (채널, 주차) 조합은 통째로 교체(최신 업로드 우선)하여 병합.
"""
import os, re, warnings
import pandas as pd

warnings.simplefilter("ignore")

TIDY_COLS = ["채널", "상품", "주차", "매출", "수량"]

# ------------------------------------------------------------- 주차 정의(자동)
# 1주차 시작일(월요일)만 정해두면 이후 주차는 날짜로 자동 계산된다.
# → 새 주차가 생겨도 코드 수정이 필요 없다. (엑셀만 업로드하면 자동 인식)
WEEK1_START = pd.Timestamp("2026-06-29")   # 1주차 = 06/29(월)~07/05(일), 이후 매주 월~일
N_WEEKS = 60                               # 미리 정의해 둘 주차 수(약 1년 이상)


def _week_start(idx):
    return WEEK1_START + pd.Timedelta(days=7 * (idx - 1))


def _week_range_str(idx):
    s = _week_start(idx)
    e = s + pd.Timedelta(days=6)
    return f"{s.strftime('%m/%d')}~{e.strftime('%m/%d')}"


WEEK_ORDER = [f"{i}주차" for i in range(1, N_WEEKS + 1)]
WEEK_RANGE = {f"{i}주차": _week_range_str(i) for i in range(1, N_WEEKS + 1)}


def week_of(date):
    """날짜 → 'N주차'. 1주차 시작 이전이거나 정의범위 밖이면 None."""
    try:
        d = pd.Timestamp(date).normalize()
    except Exception:
        return None
    if d < WEEK1_START:
        return None
    idx = (d - WEEK1_START).days // 7 + 1
    return f"{idx}주차" if 1 <= idx <= N_WEEKS else None


def week_from_filename(fname):
    """파일명의 MMDD-MMDD(시작-종료)에서 시작일로 주차를 계산. 연도 자동 보정."""
    m = re.search(r"(\d{4})-(\d{4})", fname)
    if not m:
        return None
    mm, dd = int(m.group(1)[:2]), int(m.group(1)[2:])
    # 파일명엔 연도가 없으므로, 1주차 시작연도부터 다음 연도까지 중 유효한 날짜를 찾는다.
    for yr in (WEEK1_START.year, WEEK1_START.year + 1):
        try:
            d = pd.Timestamp(yr, mm, dd)
        except ValueError:
            continue
        if d >= WEEK1_START:
            wk = week_of(d)
            if wk:
                return wk
    return None


# ------------------------------------------------------------- 상품 분류
def classify(name):
    if not isinstance(name, str):
        return "기타"
    s = name.replace(" ", "")
    if any(k in s for k in ["세트", "골라담기", "가구템", "효도템", "11종", "밸런스3종"]):
        return "세트/기획전"
    if "+9종" in s:
        return "세트/기획전"
    rules = [
        ("올리브오일", ["올리브"]),
        ("오메가3",    ["오메가3", "알티지", "rtg"]),
        ("혈당컷",     ["혈당컷", "카테킨", "바나바"]),
        ("코엔자임Q10", ["코엔자임", "코큐텐", "q10"]),
        ("칼마디아K",  ["칼마디아"]),
        ("마그네슘",   ["마그네슘"]),
        ("밀크씨슬",   ["밀크씨슬"]),
        ("루테인",     ["루테인"]),
        ("MSM",       ["msm", "엠에스엠"]),
        ("비타민C",    ["비타민c"]),
        ("멀티비타민", ["멀티비타민"]),
    ]
    low = s.lower()
    for label, keys in rules:
        if any(k in low for k in keys):
            return label
    if any(k in s for k in ["데일리케어", "시니어밸런스", "우먼밸런스", "항산화케어"]):
        return "기타/PB"
    return "기타"


def _num(series):
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.replace("원", "", regex=False),
        errors="coerce"
    ).fillna(0)


def _engine_for(filename):
    return "xlrd" if filename.lower().endswith(".xls") else "openpyxl"


def detect_channel(filename):
    n = filename.replace(" ", "")
    if "네이버" in n: return "네이버"
    if "11번가" in n: return "11번가"
    if "옥션" in n:   return "옥션"
    if "지마켓" in n: return "지마켓"
    if "쿠팡" in n:   return "쿠팡"
    if "GSSHOP" in n.upper() or "GS" in n.upper(): return "GS SHOP"
    return None


# ------------------------------------------------------------- 채널별 파서
def _tidy(channel, name, week, sales, qty):
    # name(원본 상품명, 브랜드 포함)은 classify 분류에만 사용하고 결과에는 담지 않는다.
    return {"채널": channel, "상품": classify(name),
            "주차": week, "매출": float(sales), "수량": float(qty)}


def parse_source(filename, source):
    """filename 으로 채널 판별 후 tidy DataFrame 반환. source = 경로 또는 파일객체."""
    ch = detect_channel(filename)
    if ch is None:
        raise ValueError(f"채널을 인식할 수 없는 파일명입니다: {filename}")
    eng = _engine_for(filename)
    rows = []

    if ch == "네이버":
        df = pd.read_excel(source, sheet_name="SALES", header=0, engine=eng)
        df = df[df["채널상품명"] != "전체"].copy()
        df["주차"] = df["날짜"].map(week_of)
        df["매출"] = _num(df["판매금액(순)"]); df["수량"] = _num(df["결제상품수량"])
        g = df.groupby(["채널상품명", "주차"], as_index=False).agg(매출=("매출", "sum"), 수량=("수량", "sum"))
        for _, r in g.iterrows():
            rows.append(_tidy(ch, r["채널상품명"], r["주차"], r["매출"], r["수량"]))

    elif ch == "11번가":
        df = pd.read_excel(source, sheet_name=0, header=5, engine=eng)
        df = df[df["상품명"].notna()].copy()
        df["주차"] = pd.to_datetime(df["주문일시"], errors="coerce").map(week_of)
        df["매출"] = _num(df["주문금액"]); df["수량"] = _num(df["수량"])
        g = df.groupby(["상품명", "주차"], as_index=False).agg(매출=("매출", "sum"), 수량=("수량", "sum"))
        for _, r in g.iterrows():
            rows.append(_tidy(ch, r["상품명"], r["주차"], r["매출"], r["수량"]))

    elif ch in ("옥션", "지마켓"):
        df = pd.read_excel(source, sheet_name="상품별 판매내역", header=2, engine=eng)
        df = df[df["상품명"].notna()].copy()
        df["주차"] = pd.to_datetime(df["기준일"], errors="coerce").map(week_of)
        df["매출"] = _num(df["판매금액"]) - _num(df["취소금액"])
        df["수량"] = _num(df["판매수량"]) - _num(df["취소수량"])
        g = df.groupby(["상품명", "주차"], as_index=False).agg(매출=("매출", "sum"), 수량=("수량", "sum"))
        for _, r in g.iterrows():
            rows.append(_tidy(ch, r["상품명"], r["주차"], r["매출"], r["수량"]))

    elif ch == "쿠팡":
        wk = week_from_filename(filename)
        df = pd.read_excel(source, sheet_name="vendor item metrics", header=0, engine=eng)
        df = df[df["상품명"].notna()].copy()
        df["매출"] = _num(df["매출(원)"]); df["수량"] = _num(df["판매량"])
        g = df.groupby(["상품명"], as_index=False).agg(매출=("매출", "sum"), 수량=("수량", "sum"))
        for _, r in g.iterrows():
            rows.append(_tidy(ch, r["상품명"], wk, r["매출"], r["수량"]))

    elif ch == "GS SHOP":
        wk = week_from_filename(filename)
        df = pd.read_excel(source, sheet_name="Sheet0", header=0, engine=eng)
        df = df[df["브랜드명"].notna()].copy()
        df["매출"] = _num(df["순주문금액"]); df["수량"] = _num(df["순주문수량"])
        g = df.groupby(["상품명"], as_index=False).agg(매출=("매출", "sum"), 수량=("수량", "sum"))
        for _, r in g.iterrows():
            rows.append(_tidy(ch, r["상품명"], wk, r["매출"], r["수량"]))

    out = pd.DataFrame(rows, columns=TIDY_COLS)
    out = out[(out["주차"].notna()) & (out["매출"] != 0)].copy()
    return out


def merge_tidy(existing, new):
    """new 에 들어있는 (채널, 주차) 조합은 기존 데이터에서 제거하고 new 로 대체."""
    if existing is None or existing.empty:
        return new.copy()
    if new is None or new.empty:
        return existing.copy()
    keys = set(map(tuple, new[["채널", "주차"]].drop_duplicates().values))
    mask = existing.apply(lambda r: (r["채널"], r["주차"]) in keys, axis=1)
    kept = existing[~mask]
    return pd.concat([kept, new], ignore_index=True)[TIDY_COLS]
