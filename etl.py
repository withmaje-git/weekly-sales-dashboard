# -*- coding: utf-8 -*-
"""
클라리온 매출 로컬 ETL
- 다운로드 폴더의 원본 엑셀들을 읽어 data/sales_tidy.csv 로 정리합니다.
- 실제 파싱 로직은 etl_core.py 를 공용으로 사용합니다.

사용법:  python etl.py
새 데이터가 들어오면 SRC 폴더에 같은 파일명 형식으로 넣고 다시 실행하세요.
(웹 대시보드에서는 앱 안의 '데이터 업데이트' 화면으로 엑셀을 올리면 됩니다.)
"""
import os, glob
import pandas as pd
import etl_core as core

SRC = r"C:\Users\lucky\Downloads"
OUT = os.path.join(os.path.dirname(__file__), "data", "sales_tidy.csv")

# 채널별 원본 파일 패턴
PATTERNS = [
    "클라리온_네이버_매출_*.xlsx",
    "클라리온_11번가_매출_*.xls",
    "클라리온_옥션_매출_*.xlsx",
    "클라리온_지마켓_매출_*.xlsx",
    "클라리온_쿠팡_매출_*.xlsx",
    "클라리온_GS SHOP_매출_*.xlsx",
]


def main():
    parts = []
    for pat in PATTERNS:
        for path in glob.glob(os.path.join(SRC, pat)):
            name = os.path.basename(path)
            try:
                parts.append(core.parse_source(name, path))
                print(f"  · 처리: {name}")
            except Exception as e:
                print(f"  ! 실패: {name} -> {e}")

    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=core.TIDY_COLS)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    print(f"\n저장 완료: {OUT}  ({len(out)} rows)")
    piv = out.pivot_table(index="채널", columns="주차", values="매출", aggfunc="sum", fill_value=0)
    piv = piv.reindex(columns=[w for w in core.WEEK_ORDER if w in piv.columns])
    piv["합계"] = piv.sum(axis=1)
    print("\n[채널 x 주차 매출]")
    print(piv.round(0).astype(int).to_string())
    print(f"\n총매출: {int(out['매출'].sum()):,}원")


if __name__ == "__main__":
    main()
