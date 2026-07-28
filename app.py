# -*- coding: utf-8 -*-
"""
클라리온 브랜드 멀티채널 매출 대시보드
- 로컬 실행:   streamlit run app.py
- 외부 공유:   Streamlit Community Cloud 배포 (배포_가이드.md 참고)
데이터: data/sales_tidy.csv  (앱의 '데이터 업데이트' 탭에서 엑셀 업로드로 갱신)
"""
import os, io, base64, json
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import etl_core as core

# ------------------------------------------------------------------ 기본 설정
st.set_page_config(page_title="클라리온 매출 대시보드", page_icon="📊", layout="wide")

DATA = os.path.join(os.path.dirname(__file__), "data", "sales_tidy.csv")
WEEK_ORDER = core.WEEK_ORDER
WEEK_LABEL = {w: f"{w}<br>{core.WEEK_RANGE[w]}" for w in WEEK_ORDER}

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
           "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#898781", "#e1e0d9", "#fcfcfb"

CHANNELS = ["네이버", "쿠팡", "GS SHOP", "지마켓", "옥션", "11번가"]
CH_COLOR = {c: PALETTE[i] for i, c in enumerate(CHANNELS)}


# ================================================================== 비밀번호 잠금
def secret(key, default=None):
    """secrets.toml 이 없어도 에러 없이 기본값 반환 (로컬 실행 대비)."""
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def check_password():
    pw = secret("app_password", None)
    if not pw:                       # 비번 미설정(로컬 모드) → 통과
        return True
    if st.session_state.get("auth_ok"):
        return True
    st.markdown("### 🔒 클라리온 매출 대시보드")
    st.caption("관계자에게 전달받은 비밀번호를 입력해 주세요.")
    with st.form("login"):
        entered = st.text_input("비밀번호", type="password", label_visibility="collapsed",
                                placeholder="비밀번호")
        ok = st.form_submit_button("입장")
    if ok:
        if entered == pw:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    return False


if not check_password():
    st.stop()


# ================================================================== 데이터 로드
@st.cache_data
def load(_mtime):
    df = pd.read_csv(DATA)
    df["주차"] = pd.Categorical(df["주차"], categories=WEEK_ORDER, ordered=True)
    return df


def data_mtime():
    try:
        return os.path.getmtime(DATA)
    except OSError:
        return 0


def won(x):
    return f"{int(round(x)):,}원"


def fmt_metric(x, metric):
    return won(x) if metric == "매출" else f"{int(round(x)):,}개"


def github_commit(gh, path, content_bytes, message):
    """Streamlit Cloud: data/sales_tidy.csv 를 GitHub 저장소에 커밋 → 자동 재배포."""
    import requests
    repo = gh["repo"]; branch = gh.get("branch", "main"); token = gh["token"]
    api = f"https://api.github.com/repos/{repo}/contents/{path}"
    head = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    try:
        r = requests.get(api, headers=head, params={"ref": branch}, timeout=20)
        sha = r.json().get("sha") if r.status_code == 200 else None
        payload = {"message": message,
                   "content": base64.b64encode(content_bytes).decode(),
                   "branch": branch}
        if sha:
            payload["sha"] = sha
        r2 = requests.put(api, headers=head, data=json.dumps(payload), timeout=20)
        if r2.status_code in (200, 201):
            return True, "ok"
        return False, f"{r2.status_code} {r2.json().get('message', '')}"
    except Exception as e:
        return False, str(e)


def base_layout(fig, height=380):
    fig.update_layout(
        height=height, template="simple_white", plot_bgcolor=SURFACE, paper_bgcolor=SURFACE,
        font=dict(family="system-ui, -apple-system, 'Segoe UI', 'Malgun Gothic', sans-serif",
                  color=INK, size=13),
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hoverlabel=dict(font_size=13),
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, ticks="outside", tickcolor=GRID)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=False, tickformat=",")
    return fig


df = load(data_mtime())

# ------------------------------------------------------------------ 사이드바 필터
st.sidebar.header("필터")
metric = st.sidebar.radio("지표", ["매출", "수량"], horizontal=True)
sel_ch = st.sidebar.multiselect("판매채널", CHANNELS, default=CHANNELS)
prod_order_all = df.groupby("상품")["매출"].sum().sort_values(ascending=False).index.tolist()
sel_prod = st.sidebar.multiselect("상품", prod_order_all, default=prod_order_all)
st.sidebar.caption(
    "※ 매출 기준: 네이버=판매금액(순) · 쿠팡=매출(원) · GS SHOP=순주문금액 · "
    "옥션/지마켓=판매금액−취소금액 · 11번가=주문금액. 취소분을 반영한 순매출 기준입니다."
)

f = df[df["채널"].isin(sel_ch) & df["상품"].isin(sel_prod)].copy()
M = metric

# ================================================================== 헤더
st.title("📊 클라리온 브랜드 매출 대시보드")
weeks_present = [w for w in WEEK_ORDER if w in df["주차"].unique()]
rng = f"{core.WEEK_RANGE[weeks_present[0]].split('~')[0]} ~ {core.WEEK_RANGE[weeks_present[-1]].split('~')[1]}" if weeks_present else ""
st.caption(f"최근 {len(weeks_present)}주 ({rng}) · 6개 판매채널 · 상품별 매출 추이  |  내부 공유용")

if f.empty:
    st.warning("선택된 조건에 해당하는 데이터가 없습니다. 필터를 조정해 주세요.")
    st.stop()

n_weeks = max(len(weeks_present), 1)
wk_tot = f.groupby("주차", observed=True)[M].sum().reindex(WEEK_ORDER).fillna(0)
total = f[M].sum()
last_wk = wk_tot.get(weeks_present[-1], 0) if weeks_present else 0
prev_wk = wk_tot.get(weeks_present[-2], 0) if len(weeks_present) >= 2 else 0
wow = (last_wk / prev_wk - 1) * 100 if prev_wk else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{n_weeks}주 누적 {M}", fmt_metric(total, M))
c2.metric(f"주간 평균 {M}", fmt_metric(total / n_weeks, M))
c3.metric(f"{weeks_present[-1] if weeks_present else '-'}(최근)", fmt_metric(last_wk, M),
          delta=f"{wow:+.1f}% (전주 대비)" if prev_wk else None)
c4.metric("판매채널 / 상품 수", f"{f['채널'].nunique()}개 / {f['상품'].nunique()}종")
st.divider()

# ================================================================== 탭
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📈 전체 추이", "🏬 채널별", "💊 상품별", "📄 데이터", "⚙️ 데이터 업데이트"])

# ------------------------------------------------------------------ 1) 전체 추이
with tab1:
    st.subheader("주차별 전체 매출 추이")
    vals = wk_tot.reindex(weeks_present).values
    labels = [WEEK_LABEL[w] for w in weeks_present]
    text = [fmt_metric(v, M) for v in vals]
    fig = go.Figure(go.Bar(x=labels, y=vals, text=text, textposition="outside",
                           marker_color=PALETTE[0], marker_line_width=0, width=0.55,
                           hovertemplate="%{x}<br>" + M + " %{y:,}<extra></extra>"))
    fig.update_traces(cliponaxis=False)
    base_layout(fig, height=420)
    fig.update_yaxes(range=[0, max(vals) * 1.18])
    st.plotly_chart(fig, use_container_width=True)

    if len(weeks_present) >= 2:
        cols = st.columns(len(weeks_present) - 1)
        for i in range(len(weeks_present) - 1):
            prev, cur = weeks_present[i], weeks_present[i + 1]
            a, b = wk_tot.get(prev, 0), wk_tot.get(cur, 0)
            d = (b / a - 1) * 100 if a else 0
            cols[i].metric(f"{prev} → {cur}", fmt_metric(b, M), delta=f"{d:+.1f}%")

# ------------------------------------------------------------------ 2) 채널별
with tab2:
    st.subheader("채널별 · 주차별 매출")
    ch_wk = f.groupby(["주차", "채널"], observed=True)[M].sum().reset_index()
    present = [c for c in CHANNELS if c in ch_wk["채널"].unique()]
    fig = go.Figure()
    for c in present:
        sub = ch_wk[ch_wk["채널"] == c].set_index("주차")[M].reindex(weeks_present).fillna(0)
        fig.add_bar(name=c, x=[WEEK_LABEL[w] for w in weeks_present], y=sub.values,
                    marker_color=CH_COLOR[c], marker_line=dict(color=SURFACE, width=2),
                    hovertemplate=f"{c}<br>%{{x}}<br>{M} %{{y:,}}<extra></extra>")
    fig.update_layout(barmode="stack")
    base_layout(fig, height=440)
    st.plotly_chart(fig, use_container_width=True)

    col_a, col_b = st.columns([3, 2])
    with col_a:
        st.markdown(f"**채널별 {n_weeks}주 누적**")
        ch_tot = f.groupby("채널", observed=True)[M].sum().reindex(present).fillna(0).sort_values()
        figh = go.Figure(go.Bar(y=ch_tot.index, x=ch_tot.values, orientation="h",
                                marker_color=[CH_COLOR[c] for c in ch_tot.index], marker_line_width=0,
                                text=[fmt_metric(v, M) for v in ch_tot.values], textposition="auto",
                                hovertemplate=f"%{{y}}<br>{M} %{{x:,}}<extra></extra>"))
        base_layout(figh, height=300)
        figh.update_xaxes(showgrid=True)
        st.plotly_chart(figh, use_container_width=True)
    with col_b:
        st.markdown(f"**채널 비중 ({n_weeks}주 누적)**")
        share = ch_tot.sort_values(ascending=False)
        figp = go.Figure(go.Pie(labels=share.index, values=share.values, hole=0.5, sort=False,
                                marker=dict(colors=[CH_COLOR[c] for c in share.index],
                                            line=dict(color=SURFACE, width=2)),
                                textinfo="label+percent",
                                hovertemplate="%{label}<br>%{percent}<extra></extra>"))
        base_layout(figp, height=300)
        figp.update_layout(showlegend=False)
        st.plotly_chart(figp, use_container_width=True)

# ------------------------------------------------------------------ 3) 상품별
with tab3:
    st.subheader("상품별 · 주차별 매출")
    prod_tot = f.groupby("상품", observed=True)[M].sum().sort_values(ascending=False)
    top = prod_tot.head(7).index.tolist()
    g = f.copy()
    g["상품군"] = g["상품"].where(g["상품"].isin(top), "기타")
    order = top + (["기타"] if (g["상품군"] == "기타").any() else [])
    PCOLOR = {p: PALETTE[i] for i, p in enumerate(order)}
    pw = g.groupby(["주차", "상품군"], observed=True)[M].sum().reset_index()
    fig = go.Figure()
    for p in order:
        sub = pw[pw["상품군"] == p].set_index("주차")[M].reindex(weeks_present).fillna(0)
        fig.add_bar(name=p, x=[WEEK_LABEL[w] for w in weeks_present], y=sub.values,
                    marker_color=PCOLOR[p], marker_line=dict(color=SURFACE, width=2),
                    hovertemplate=f"{p}<br>%{{x}}<br>{M} %{{y:,}}<extra></extra>")
    fig.update_layout(barmode="stack")
    base_layout(fig, height=460)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown(f"**상품별 {n_weeks}주 누적 순위**")
    rank = prod_tot.sort_values()
    figr = go.Figure(go.Bar(y=rank.index, x=rank.values, orientation="h",
                            marker_color=PALETTE[0], marker_line_width=0,
                            text=[fmt_metric(v, M) for v in rank.values], textposition="auto",
                            hovertemplate=f"%{{y}}<br>{M} %{{x:,}}<extra></extra>"))
    base_layout(figr, height=max(300, 26 * len(rank)))
    figr.update_xaxes(showgrid=True)
    st.plotly_chart(figr, use_container_width=True)
    st.caption("상품은 상품명 메인 키워드로 자동 분류했습니다 (예: '유기농 올리브오일 30캡슐 6박스' → 올리브오일). "
               "GS SHOP의 Plus/PB 상품도 같은 키워드로 매칭됩니다.")

# ------------------------------------------------------------------ 4) 데이터
with tab4:
    st.subheader("데이터 (채널 × 상품 × 주차)")
    pivot = pd.pivot_table(f, index=["채널", "상품"], columns="주차", values=M,
                           aggfunc="sum", fill_value=0, observed=True)
    pivot = pivot.reindex(columns=weeks_present, fill_value=0)
    pivot["합계"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("합계", ascending=False)
    st.dataframe(pivot.style.format("{:,.0f}"), use_container_width=True, height=460)
    csv = f.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("⬇️ 원본 데이터 CSV 내려받기", csv,
                       file_name="클라리온_매출_tidy.csv", mime="text/csv")

# ------------------------------------------------------------------ 5) 데이터 업데이트
with tab5:
    st.subheader("주간 매출 데이터 업데이트")
    admin_pw = secret("admin_password", None)
    gh = secret("github", None)   # {token, repo, branch}

    # 관리자 인증 (admin_password 미설정 시 = 로컬 모드, 바로 허용)
    allowed = True
    if admin_pw:
        if not st.session_state.get("admin_ok"):
            entered = st.text_input("관리자 비밀번호", type="password")
            if st.button("확인"):
                if entered == admin_pw:
                    st.session_state["admin_ok"] = True
                    st.rerun()
                else:
                    st.error("관리자 비밀번호가 올바르지 않습니다.")
            allowed = False
        else:
            allowed = st.session_state.get("admin_ok", False)

    if not allowed:
        st.info("데이터를 갱신하려면 관리자 비밀번호가 필요합니다.")
        st.stop()

    st.markdown(
        "이번 주 채널별 엑셀 파일을 그대로 올려 주세요. 파일명으로 채널·주차를 자동 인식합니다.\n\n"
        "- 지원 파일: `클라리온_네이버_매출_MMDD-MMDD.xlsx` / `_11번가_ .xls` / `_옥션_` / `_지마켓_` / "
        "`_쿠팡_` / `_GS SHOP_` \n"
        "- 같은 채널·주차 데이터는 **최신 업로드로 자동 교체**됩니다. (일부 채널만 올려도 됨)"
    )
    ups = st.file_uploader("엑셀 파일 (여러 개 선택 가능)", type=["xlsx", "xls"],
                           accept_multiple_files=True)

    if ups:
        parsed, errs = [], []
        for up in ups:
            try:
                part = core.parse_source(up.name, io.BytesIO(up.getvalue()))
                if part.empty:
                    errs.append(f"{up.name}: 인식된 매출 행이 없습니다(주차 정의 확인).")
                else:
                    parsed.append(part)
            except Exception as e:
                errs.append(f"{up.name}: {e}")
        for e in errs:
            st.error(e)

        if parsed:
            new = pd.concat(parsed, ignore_index=True)
            prev = df.copy()
            prev["주차"] = prev["주차"].astype(str)
            merged = core.merge_tidy(prev, new)

            st.markdown("**미리보기 — 반영될 (채널 × 주차) 매출**")
            prev_piv = prev.pivot_table(index="채널", columns="주차", values="매출",
                                        aggfunc="sum", fill_value=0)
            new_piv = merged.pivot_table(index="채널", columns="주차", values="매출",
                                         aggfunc="sum", fill_value=0)
            cols_order = [w for w in WEEK_ORDER if w in new_piv.columns]
            st.dataframe(new_piv.reindex(columns=cols_order).style.format("{:,.0f}"),
                         use_container_width=True)
            changed = new[["채널", "주차"]].drop_duplicates()
            st.caption("변경 대상: " + ", ".join(f"{r.채널}·{r.주차}" for r in changed.itertuples()))

            if st.button("💾 이 데이터로 저장하기", type="primary"):
                csv_bytes = merged.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                if gh:  # Streamlit Cloud: GitHub 에 커밋 → 자동 재배포
                    ok, msg = github_commit(gh, "data/sales_tidy.csv", csv_bytes,
                                            "주간 매출 데이터 업데이트")
                    if ok:
                        st.success("저장 완료! 30초~1분 뒤 대시보드에 반영됩니다. (자동 재배포)")
                        st.cache_data.clear()
                    else:
                        st.error(f"GitHub 저장 실패: {msg}")
                else:   # 로컬: 파일로 저장
                    with open(DATA, "wb") as fp:
                        fp.write(csv_bytes)
                    st.cache_data.clear()
                    st.success("저장 완료! 상단 탭을 새로고침하면 반영됩니다.")
                    st.rerun()
