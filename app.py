# -*- coding: utf-8 -*-
"""
주간 매출 대시보드 (멀티채널)
- 로컬 실행:   streamlit run app.py
- 외부 공유:   Streamlit Community Cloud 배포 (배포_가이드.md 참고)
데이터: data/sales_tidy.csv  (앱의 '데이터 업데이트' 탭에서 엑셀 업로드로 갱신)
"""
import os, io, base64, json
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import etl_core as core
import ads_core as ads

# ------------------------------------------------------------------ 기본 설정
st.set_page_config(page_title="주간 매출 대시보드", page_icon="📊", layout="wide")

DATA = os.path.join(os.path.dirname(__file__), "data", "sales_tidy.csv")
ADS_DATA = os.path.join(os.path.dirname(__file__), "data", "ads_tidy.csv")
MONTHLY_DATA = os.path.join(os.path.dirname(__file__), "data", "monthly_tidy.csv")
WEEK_ORDER = core.WEEK_ORDER
WEEK_LABEL = {w: f"{w}<br>{core.WEEK_RANGE[w]}" for w in WEEK_ORDER}

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
           "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#898781", "#e1e0d9", "#fcfcfb"

CHANNELS = ["네이버", "쿠팡", "GS SHOP", "지마켓", "옥션", "11번가"]
CH_COLOR = {c: PALETTE[i] for i, c in enumerate(CHANNELS)}

AD_CHANNELS = ads.AD_CHANNELS   # 네이버 검색광고 / 네이버 디스플레이 / 쿠팡 광고 / 메타 광고
AD_COLOR = {c: PALETTE[i] for i, c in enumerate(AD_CHANNELS)}


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
    st.markdown("### 🔒 주간 매출 대시보드")
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


@st.cache_data
def load_ads(_mtime):
    """광고 성과 데이터. 파일이 없거나 비어 있으면 빈 DataFrame 반환."""
    try:
        d = pd.read_csv(ADS_DATA)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame(columns=ads.ADS_TIDY_COLS)
    if d.empty:
        return d
    d["주차"] = pd.Categorical(d["주차"], categories=WEEK_ORDER, ordered=True)
    return d


def ads_mtime():
    try:
        return os.path.getmtime(ADS_DATA)
    except OSError:
        return 0


@st.cache_data
def load_monthly(_mtime):
    """월별(달력 월) 매출 데이터. 없거나 비어 있으면 빈 DataFrame."""
    try:
        d = pd.read_csv(MONTHLY_DATA, dtype={"월": str})
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame(columns=core.MONTHLY_TIDY_COLS)
    return d


def monthly_mtime():
    try:
        return os.path.getmtime(MONTHLY_DATA)
    except OSError:
        return 0


def won(x):
    return f"{int(round(x)):,}원"


def fmt_metric(x, metric):
    return won(x) if metric == "매출" else f"{int(round(x)):,}개"


def roas_val(rev, cost):
    """스칼라 ROAS(%) = 광고매출 / 광고비 × 100. 광고비 0 이면 0."""
    return (rev / cost * 100) if cost else 0.0


def fmt_roas(x):
    return f"{x:,.0f}%"


def fmt_ad(x, metric):
    return fmt_roas(x) if metric == "ROAS" else won(x)


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
ads_df = load_ads(ads_mtime())
monthly_df = load_monthly(monthly_mtime())

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

st.sidebar.divider()
st.sidebar.subheader("📣 광고 성과 필터")
sel_ad_ch = st.sidebar.multiselect("광고채널", AD_CHANNELS, default=AD_CHANNELS)
st.sidebar.caption("※ 광고매출은 각 매체가 보고한 전환매출(광고 기여 매출) 기준, "
                   "ROAS = 광고매출 ÷ 광고비 × 100%. ‘📣 광고 성과’ 탭에 적용됩니다.")

f = df[df["채널"].isin(sel_ch) & df["상품"].isin(sel_prod)].copy()
af = ads_df[ads_df["광고채널"].isin(sel_ad_ch)].copy() if not ads_df.empty else ads_df
mf = (monthly_df[monthly_df["채널"].isin(sel_ch) & monthly_df["상품"].isin(sel_prod)].copy()
      if not monthly_df.empty else monthly_df)
M = metric

months_present = sorted(mf["월"].astype(str).unique()) if not mf.empty else []
_one_year = len({m.split("-")[0] for m in months_present}) <= 1


def mlabel(mk):
    """'YYYY-MM' → 'M월'(단일연도) 또는 'YY.MM'(여러 해)."""
    y, m = mk.split("-")
    return f"{int(m)}월" if _one_year else f"{y[2:]}.{m}"

# ================================================================== 헤더
st.title("📊 주간 매출 대시보드")
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

# ================================================================== 핵심 인사이트
def _signed(v):
    return ("+" if v >= 0 else "−") + fmt_metric(abs(v), M)


with st.container(border=True):
    if len(weeks_present) >= 2:
        _prev, _last = weeks_present[-2], weeks_present[-1]
        fw = f[f["주차"].isin([_prev, _last])]

        def _delta(index):
            p = fw.pivot_table(index=index, columns="주차", values=M,
                               aggfunc="sum", fill_value=0, observed=True)
            for w in (_prev, _last):
                if w not in p.columns:
                    p[w] = 0
            p["Δ"] = p[_last] - p[_prev]
            return p

        def _line(name, row):
            base, d = row[_prev], row["Δ"]
            pct = f" ({d / base * 100:+.0f}%)" if base > 0 else " (신규)" if d > 0 else ""
            return f"{name} **{_signed(d)}**{pct}"

        cp = _delta(["채널", "상품"])
        ups = cp[cp["Δ"] > 0].sort_values("Δ", ascending=False).head(3)
        downs = cp[cp["Δ"] < 0].sort_values("Δ").head(3)
        ch = _delta("채널")

        arrow = "▲ 증가" if last_wk >= prev_wk else "▼ 감소"
        st.markdown(f"#### 🔎 핵심 인사이트 · {_prev} → {_last}")
        st.markdown(
            f"전체 {M}은 전주 대비 **{wow:+.1f}% {arrow}** "
            f"({fmt_metric(prev_wk, M)} → {fmt_metric(last_wk, M)}, {_signed(last_wk - prev_wk)})"
        )
        col_up, col_down = st.columns(2)
        with col_up:
            st.markdown("**📈 증가 주도 (채널 · 상품)**")
            if len(ups):
                for (c_, p_), row in ups.iterrows():
                    st.markdown(f"- {_line(f'{c_} · {p_}', row)}")
            else:
                st.markdown("- 증가 항목 없음")
        with col_down:
            st.markdown("**📉 감소 주도 (채널 · 상품)**")
            if len(downs):
                for (c_, p_), row in downs.iterrows():
                    st.markdown(f"- {_line(f'{c_} · {p_}', row)}")
            else:
                st.markdown("- 감소 항목 없음")

        parts = []
        ch_up = ch[ch["Δ"] > 0].sort_values("Δ", ascending=False)
        ch_dn = ch[ch["Δ"] < 0].sort_values("Δ")
        if len(ch_up):
            parts.append(f"가장 크게 늘어난 채널 **{ch_up.index[0]}** ({_signed(ch_up.iloc[0]['Δ'])})")
        if len(ch_dn):
            parts.append(f"가장 크게 줄어든 채널 **{ch_dn.index[0]}** ({_signed(ch_dn.iloc[0]['Δ'])})")
        if parts:
            st.caption("· " + " · ".join(parts))
    else:
        st.markdown("#### 🔎 핵심 인사이트")
        st.caption("전주 대비 변화는 최소 2개 주차가 쌓이면 자동으로 표시됩니다.")

st.divider()

# ================================================================== 탭
tab1, tab2, tab3, tabA, tab4, tab5 = st.tabs(
    ["📈 전체 추이", "🏬 채널별", "💊 상품별", "📣 광고 성과", "📄 데이터", "⚙️ 데이터 업데이트"])

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

    # ---------------- 월별 매출 추이 (별도 업로드, 달력 월 1일~말일) ----------------
    st.divider()
    st.subheader(f"월별 {M} 추이")

    if mf.empty:
        st.info("월별 매출 데이터가 없습니다. **⚙️ 데이터 업데이트 → 🗓️ 월별 매출 데이터**에서 "
                "채널별 ‘한 달치’ 원본 엑셀을 올려 주세요. 실제 판매일자 기준으로 달력 월(1일~말일)로 집계합니다.")
    else:
        months = months_present
        mon_tot = mf.groupby("월")[M].sum().reindex(months).fillna(0)
        mvals = mon_tot.values
        mlabels = [mlabel(m) for m in months]
        mtext = [fmt_metric(v, M) for v in mvals]
        figm = go.Figure(go.Bar(x=mlabels, y=mvals, text=mtext, textposition="outside",
                                marker_color=PALETTE[3], marker_line_width=0, width=0.5,
                                hovertemplate="%{x}<br>" + M + " %{y:,}<extra></extra>"))
        figm.update_traces(cliponaxis=False)
        base_layout(figm, height=360)
        figm.update_yaxes(range=[0, max(mvals) * 1.18])
        st.plotly_chart(figm, use_container_width=True)

        if len(months) >= 2:
            cols = st.columns(len(months) - 1)
            for i in range(len(months) - 1):
                a, b = mon_tot.iloc[i], mon_tot.iloc[i + 1]
                d = (b / a - 1) * 100 if a else 0
                cols[i].metric(f"{mlabel(months[i])} → {mlabel(months[i+1])}",
                               fmt_metric(b, M), delta=f"{d:+.1f}%")

        st.caption("월별은 별도로 올린 ‘한 달치’ 원본에서 **실제 판매일자 기준 달력 월(1일~말일)**로 집계합니다. "
                   "판매채널·상품·지표 필터가 함께 적용됩니다. (주차 데이터와 독립적으로 업로드) "
                   "채널별·상품별 월 분해는 **🏬 채널별 · 💊 상품별 탭 하단**에서 볼 수 있습니다.")

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

    # ---------------- 월별 · 채널별 (달력 월) ----------------
    st.divider()
    st.subheader(f"채널별 · 월별 {M}")
    if mf.empty:
        st.info("월별 매출 데이터가 없습니다. **⚙️ 데이터 업데이트 → 🗓️ 월별 매출 데이터**에서 "
                "채널별 ‘한 달치’ 원본을 올려 주세요.")
    else:
        m_present = [c for c in CHANNELS if c in mf["채널"].unique()]
        mlabels = [mlabel(m) for m in months_present]
        figmc = go.Figure()
        for c in m_present:
            sub = mf[mf["채널"] == c].groupby("월")[M].sum().reindex(months_present).fillna(0)
            figmc.add_bar(name=c, x=mlabels, y=sub.values, marker_color=CH_COLOR[c],
                          marker_line=dict(color=SURFACE, width=2),
                          hovertemplate=f"{c}<br>%{{x}}<br>{M} %{{y:,}}<extra></extra>")
        figmc.update_layout(barmode="stack")
        base_layout(figmc, height=400)
        st.plotly_chart(figmc, use_container_width=True)

        pivm = mf.pivot_table(index="채널", columns="월", values=M, aggfunc="sum", fill_value=0)
        pivm = pivm.reindex(index=m_present, columns=months_present, fill_value=0)
        disp = pivm.copy()
        disp.columns = [mlabel(c) for c in disp.columns]
        if len(months_present) >= 2:
            a, b = months_present[-2], months_present[-1]
            disp[f"{mlabel(b)} Δ"] = pivm[b] - pivm[a]
        disp["합계"] = pivm.sum(axis=1)
        disp = disp.sort_values("합계", ascending=False)
        st.dataframe(disp.style.format("{:,.0f}"), use_container_width=True)
        if len(months_present) >= 2:
            st.caption(f"‘{mlabel(b)} Δ’ = {mlabel(b)} − {mlabel(a)} (전월 대비 증감). "
                       "달력 월(1일~말일) 기준, 채널·상품·지표 필터 적용.")

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

    # ---------------- 월별 · 상품별 (달력 월) ----------------
    st.divider()
    st.subheader(f"상품별 · 월별 {M}")
    if mf.empty:
        st.info("월별 매출 데이터가 없습니다. **⚙️ 데이터 업데이트 → 🗓️ 월별 매출 데이터**에서 "
                "채널별 ‘한 달치’ 원본을 올려 주세요.")
    else:
        m_prod_tot = mf.groupby("상품")[M].sum().sort_values(ascending=False)
        m_top = m_prod_tot.head(7).index.tolist()
        gm = mf.copy()
        gm["상품군"] = gm["상품"].where(gm["상품"].isin(m_top), "기타")
        m_order = m_top + (["기타"] if (gm["상품군"] == "기타").any() else [])
        PCOLORm = {p: PALETTE[i] for i, p in enumerate(m_order)}
        mlabels = [mlabel(m) for m in months_present]
        figmp = go.Figure()
        for p in m_order:
            sub = gm[gm["상품군"] == p].groupby("월")[M].sum().reindex(months_present).fillna(0)
            figmp.add_bar(name=p, x=mlabels, y=sub.values, marker_color=PCOLORm[p],
                          marker_line=dict(color=SURFACE, width=2),
                          hovertemplate=f"{p}<br>%{{x}}<br>{M} %{{y:,}}<extra></extra>")
        figmp.update_layout(barmode="stack")
        base_layout(figmp, height=440)
        st.plotly_chart(figmp, use_container_width=True)

        pivm = mf.pivot_table(index="상품", columns="월", values=M, aggfunc="sum", fill_value=0)
        pivm = pivm.reindex(columns=months_present, fill_value=0)
        disp = pivm.copy()
        disp.columns = [mlabel(c) for c in disp.columns]
        if len(months_present) >= 2:
            a, b = months_present[-2], months_present[-1]
            disp[f"{mlabel(b)} Δ"] = pivm[b] - pivm[a]
        disp["합계"] = pivm.sum(axis=1)
        disp = disp.sort_values("합계", ascending=False)
        st.dataframe(disp.style.format("{:,.0f}"), use_container_width=True)
        st.caption("막대는 상위 7개 상품 + 기타, 표는 전체 상품 × 월. "
                   + (f"‘{mlabel(b)} Δ’ = 전월 대비 증감. " if len(months_present) >= 2 else "")
                   + "달력 월(1일~말일) 기준.")

# ------------------------------------------------------------------ A) 광고 성과
with tabA:
    st.subheader("광고 채널별 주간 성과")
    if af.empty:
        st.info(
            "아직 광고 데이터가 없습니다. **⚙️ 데이터 업데이트** 탭에서 광고 리포트를 올려 주세요.\n\n"
            "지원 광고채널: 네이버 검색광고 · 네이버 디스플레이 · 쿠팡 광고 · 메타 광고 (각 매체 원본 리포트 파일)."
        )
    else:
        aw = [w for w in WEEK_ORDER if w in af["주차"].unique()]
        wk = af.groupby("주차", observed=True)[["광고비", "광고매출"]].sum().reindex(aw).fillna(0)
        wk["ROAS"] = (wk["광고매출"] / wk["광고비"].replace(0, pd.NA) * 100).fillna(0)

        tot_cost, tot_rev = af["광고비"].sum(), af["광고매출"].sum()
        tot_roas = roas_val(tot_rev, tot_cost)
        n_aw = max(len(aw), 1)
        _last = aw[-1] if aw else None
        _prev = aw[-2] if len(aw) >= 2 else None
        last_roas = wk.loc[_last, "ROAS"] if _last else 0
        prev_roas = wk.loc[_prev, "ROAS"] if _prev else 0

        k1, k2, k3, k4 = st.columns(4)
        k1.metric(f"{n_aw}주 누적 광고비", won(tot_cost))
        k2.metric(f"{n_aw}주 누적 광고매출", won(tot_rev))
        k3.metric("통합 ROAS", fmt_roas(tot_roas))
        k4.metric(f"{_last or '-'}(최근) ROAS", fmt_roas(last_roas),
                  delta=f"{last_roas - prev_roas:+.0f}%p (전주 대비)" if _prev else None)

        # ---------------- 핵심 인사이트 (전주 대비) ----------------
        with st.container(border=True):
            if _prev:
                p_cost, l_cost = wk.loc[_prev, "광고비"], wk.loc[_last, "광고비"]
                p_rev, l_rev = wk.loc[_prev, "광고매출"], wk.loc[_last, "광고매출"]
                cost_pct = (l_cost / p_cost - 1) * 100 if p_cost else 0
                rev_pct = (l_rev / p_rev - 1) * 100 if p_rev else 0
                roas_arrow = "▲ 개선" if last_roas >= prev_roas else "▼ 악화"

                cw = af[af["주차"].isin([_prev, _last])].pivot_table(
                    index="광고채널", columns="주차", values=["광고비", "광고매출"],
                    aggfunc="sum", fill_value=0, observed=True)
                rows = []
                for c_ in cw.index:
                    pc = cw.loc[c_, ("광고비", _prev)] if ("광고비", _prev) in cw.columns else 0
                    lc = cw.loc[c_, ("광고비", _last)] if ("광고비", _last) in cw.columns else 0
                    pr = cw.loc[c_, ("광고매출", _prev)] if ("광고매출", _prev) in cw.columns else 0
                    lr = cw.loc[c_, ("광고매출", _last)] if ("광고매출", _last) in cw.columns else 0
                    rows.append({"채널": c_, "ΔROAS": roas_val(lr, lc) - roas_val(pr, pc),
                                 "Δ광고비": lc - pc, "prev_roas": roas_val(pr, pc),
                                 "last_roas": roas_val(lr, lc)})
                cd = pd.DataFrame(rows)

                st.markdown(f"#### 🔎 핵심 인사이트 · {_prev} → {_last}")
                st.markdown(
                    f"- 전체 **ROAS {prev_roas:,.0f}% → {last_roas:,.0f}%** "
                    f"(**{last_roas - prev_roas:+.0f}%p {roas_arrow}**)\n"
                    f"- 광고비 {won(p_cost)} → {won(l_cost)} (**{cost_pct:+.1f}%**) · "
                    f"광고매출 {won(p_rev)} → {won(l_rev)} (**{rev_pct:+.1f}%**)"
                )
                col_up, col_dn = st.columns(2)
                with col_up:
                    st.markdown("**📈 ROAS 개선 채널**")
                    ups = cd[cd["ΔROAS"] > 0].sort_values("ΔROAS", ascending=False).head(3)
                    if len(ups):
                        for _, r in ups.iterrows():
                            st.markdown(f"- {r['채널']} **{r['ΔROAS']:+.0f}%p** "
                                        f"({r['prev_roas']:,.0f}%→{r['last_roas']:,.0f}%)")
                    else:
                        st.markdown("- 개선 채널 없음")
                with col_dn:
                    st.markdown("**📉 ROAS 악화 채널**")
                    dns = cd[cd["ΔROAS"] < 0].sort_values("ΔROAS").head(3)
                    if len(dns):
                        for _, r in dns.iterrows():
                            st.markdown(f"- {r['채널']} **{r['ΔROAS']:+.0f}%p** "
                                        f"({r['prev_roas']:,.0f}%→{r['last_roas']:,.0f}%)")
                    else:
                        st.markdown("- 악화 채널 없음")

                sp = cd.sort_values("Δ광고비")
                parts = []
                if len(sp) and sp.iloc[-1]["Δ광고비"] > 0:
                    parts.append(f"광고비를 가장 늘린 채널 **{sp.iloc[-1]['채널']}** "
                                 f"({won(sp.iloc[-1]['Δ광고비'])}↑)")
                if len(sp) and sp.iloc[0]["Δ광고비"] < 0:
                    parts.append(f"가장 줄인 채널 **{sp.iloc[0]['채널']}** "
                                 f"({won(-sp.iloc[0]['Δ광고비'])}↓)")
                if parts:
                    st.caption("· " + " · ".join(parts))
            else:
                st.markdown("#### 🔎 핵심 인사이트")
                st.caption("전주 대비 변화는 최소 2개 주차가 쌓이면 자동으로 표시됩니다.")

        st.divider()

        # ---------------- 주차별 광고비·광고매출·ROAS ----------------
        st.markdown("**주차별 광고비 · 광고매출 · ROAS**")
        xl = [WEEK_LABEL[w] for w in aw]
        fig = go.Figure()
        fig.add_bar(name="광고비", x=xl, y=wk["광고비"].values, marker_color=PALETTE[0],
                    marker_line_width=0, hovertemplate="광고비 %{y:,}원<extra></extra>")
        fig.add_bar(name="광고매출", x=xl, y=wk["광고매출"].values, marker_color=PALETTE[2],
                    marker_line_width=0, hovertemplate="광고매출 %{y:,}원<extra></extra>")
        fig.add_scatter(name="ROAS", x=xl, y=wk["ROAS"].values, yaxis="y2", mode="lines+markers+text",
                        line=dict(color=PALETTE[1], width=3), marker=dict(size=8),
                        text=[f"{v:,.0f}%" for v in wk["ROAS"].values], textposition="top center",
                        hovertemplate="ROAS %{y:,.0f}%<extra></extra>")
        base_layout(fig, height=440)
        fig.update_layout(
            barmode="group",
            yaxis=dict(title="광고비·광고매출(원)", tickformat=","),
            yaxis2=dict(title="ROAS(%)", overlaying="y", side="right",
                        showgrid=False, rangemode="tozero", ticksuffix="%"),
        )
        st.plotly_chart(fig, use_container_width=True)

        # ---------------- 채널별 ----------------
        present_ad = [c for c in AD_CHANNELS if c in af["광고채널"].unique()]
        ad_metric = st.radio("채널 비교 지표", ["광고비", "광고매출", "ROAS"],
                             horizontal=True, key="ad_metric")
        col_l, col_r = st.columns([3, 2])
        with col_l:
            st.markdown(f"**채널별 · 주차별 {ad_metric}**")
            figc = go.Figure()
            for c in present_ad:
                sub = af[af["광고채널"] == c].groupby("주차", observed=True)[
                    ["광고비", "광고매출"]].sum().reindex(aw).fillna(0)
                if ad_metric == "ROAS":
                    yv = (sub["광고매출"] / sub["광고비"].replace(0, pd.NA) * 100).fillna(0).values
                    figc.add_scatter(name=c, x=xl, y=yv, mode="lines+markers",
                                     line=dict(color=AD_COLOR[c], width=2.5),
                                     hovertemplate=f"{c}<br>%{{x}}<br>ROAS %{{y:,.0f}}%<extra></extra>")
                else:
                    figc.add_bar(name=c, x=xl, y=sub[ad_metric].values, marker_color=AD_COLOR[c],
                                 marker_line=dict(color=SURFACE, width=2),
                                 hovertemplate=f"{c}<br>%{{x}}<br>{ad_metric} %{{y:,}}원<extra></extra>")
            if ad_metric != "ROAS":
                figc.update_layout(barmode="stack")
            base_layout(figc, height=360)
            if ad_metric == "ROAS":
                figc.update_yaxes(ticksuffix="%")
            st.plotly_chart(figc, use_container_width=True)
        with col_r:
            st.markdown(f"**채널별 {n_aw}주 누적**")
            ct = af.groupby("광고채널", observed=True)[["광고비", "광고매출"]].sum().reindex(present_ad)
            ct["ROAS"] = (ct["광고매출"] / ct["광고비"].replace(0, pd.NA) * 100).fillna(0)
            disp = ct.copy()
            disp["광고비"] = disp["광고비"].map(won)
            disp["광고매출"] = disp["광고매출"].map(won)
            disp["ROAS"] = disp["ROAS"].map(fmt_roas)
            st.dataframe(disp, use_container_width=True)

        # ---------------- 표 + 다운로드 ----------------
        st.markdown(f"**데이터 (광고채널 × 주차 · {ad_metric})**")
        if ad_metric == "ROAS":
            piv_c = af.pivot_table(index="광고채널", columns="주차", values="광고비",
                                   aggfunc="sum", fill_value=0, observed=True).reindex(columns=aw, fill_value=0)
            piv_r = af.pivot_table(index="광고채널", columns="주차", values="광고매출",
                                   aggfunc="sum", fill_value=0, observed=True).reindex(columns=aw, fill_value=0)
            piv = (piv_r / piv_c.replace(0, pd.NA) * 100).fillna(0)
            st.dataframe(piv.style.format("{:,.0f}%"), use_container_width=True)
        else:
            piv = af.pivot_table(index="광고채널", columns="주차", values=ad_metric,
                                 aggfunc="sum", fill_value=0, observed=True).reindex(columns=aw, fill_value=0)
            piv["합계"] = piv.sum(axis=1)
            piv = piv.sort_values("합계", ascending=False)
            st.dataframe(piv.style.format("{:,.0f}"), use_container_width=True)
        acsv = af.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button("⬇️ 광고 성과 데이터 CSV 내려받기", acsv,
                           file_name="광고성과_tidy.csv", mime="text/csv")

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
                       file_name="매출_tidy.csv", mime="text/csv")

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

    st.markdown("### 📊 매출 데이터")
    st.markdown(
        "이번 주 채널별 엑셀 파일을 그대로 올려 주세요. 파일명으로 채널·주차를 자동 인식합니다.\n\n"
        "- 지원 파일: `네이버_매출_MMDD-MMDD.xlsx` / `11번가_ .xls` / `옥션_` / `지마켓_` / "
        "`_쿠팡_` / `_GS SHOP_` \n"
        "- 같은 채널·주차 데이터는 **최신 업로드로 자동 교체**됩니다. (일부 채널만 올려도 됨)"
    )
    ups = st.file_uploader("매출 엑셀 파일 (여러 개 선택 가능)", type=["xlsx", "xls"],
                           accept_multiple_files=True, key="sales_up")

    if ups:
        parsed, errs = [], []
        for up in ups:
            try:
                part = core.parse_source(up.name, io.BytesIO(up.getvalue()))
                if part.empty:
                    errs.append(f"{up.name}: 인식된 매출 행이 없습니다(파일 날짜/형식 확인).")
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

    # ============================================================== 광고 데이터
    st.divider()
    st.markdown("### 📣 광고 데이터")
    st.markdown(
        "네이버 검색광고 · 네이버 디스플레이 · 쿠팡 광고 · 메타 광고의 **원본 리포트 파일**을 그대로 올려 주세요. "
        "파일명으로 광고채널을, 리포트 안의 날짜(없으면 파일명 기간)로 주차를 자동 인식합니다.\n\n"
        "- 파일명 예: `네이버_검색광고_0811-0817.xlsx` · `네이버_디스플레이_0811-0817.xlsx` · "
        "`쿠팡_광고_0811-0817.xlsx` · `메타_광고_0811-0817.csv`\n"
        "- 리포트에 **날짜 컬럼**이 있으면 여러 주가 섞여 있어도 주차별로 자동 분리됩니다. "
        "날짜 컬럼이 없으면 **파일명의 기간(MMDD-MMDD)** 으로 한 주차에 합산합니다.\n"
        "- 같은 광고채널·주차 데이터는 **최신 업로드로 자동 교체**됩니다."
    )
    a_ups = st.file_uploader("광고 리포트 파일 (여러 개 선택 가능)", type=["xlsx", "xls", "csv"],
                             accept_multiple_files=True, key="ads_up")

    if a_ups:
        a_parsed, a_errs = [], []
        for up in a_ups:
            try:
                part = ads.parse_ad_source(up.name, io.BytesIO(up.getvalue()))
                if part.empty:
                    a_errs.append(f"{up.name}: 인식된 광고 행이 없습니다(파일 형식/기간 확인).")
                else:
                    a_parsed.append(part)
            except Exception as e:
                a_errs.append(f"{up.name}: {e}")
        for e in a_errs:
            st.error(e)

        if a_parsed:
            a_new = pd.concat(a_parsed, ignore_index=True)
            a_prev = ads_df.copy()
            if not a_prev.empty:
                a_prev["주차"] = a_prev["주차"].astype(str)
            a_merged = ads.merge_ads(a_prev, a_new)
            a_merged["ROAS"] = (a_merged["광고매출"] /
                                a_merged["광고비"].replace(0, pd.NA) * 100).fillna(0)

            st.markdown("**미리보기 — 반영될 (광고채널 × 주차)**")
            aw_cols = [w for w in WEEK_ORDER if w in a_merged["주차"].unique()]
            show = a_merged.copy()
            show["표시"] = (show["광고비"].map(lambda v: f"{v:,.0f}") + "원 / " +
                           show["광고매출"].map(lambda v: f"{v:,.0f}") + "원 / ROAS " +
                           show["ROAS"].map(lambda v: f"{v:,.0f}%"))
            prev_piv = show.pivot_table(index="광고채널", columns="주차", values="표시",
                                        aggfunc="first")
            st.dataframe(prev_piv.reindex(columns=[c for c in aw_cols if c in prev_piv.columns]),
                         use_container_width=True)
            st.caption("셀 형식: 광고비 / 광고매출 / ROAS")
            a_changed = a_new[["광고채널", "주차"]].drop_duplicates()
            st.caption("변경 대상: " + ", ".join(f"{r.광고채널}·{r.주차}" for r in a_changed.itertuples()))

            if st.button("💾 광고 데이터 저장하기", type="primary", key="ads_save"):
                a_bytes = a_merged[ads.ADS_TIDY_COLS].to_csv(
                    index=False, encoding="utf-8-sig").encode("utf-8-sig")
                if gh:
                    ok, msg = github_commit(gh, "data/ads_tidy.csv", a_bytes,
                                            "주간 광고 성과 데이터 업데이트")
                    if ok:
                        st.success("저장 완료! 30초~1분 뒤 대시보드에 반영됩니다. (자동 재배포)")
                        st.cache_data.clear()
                    else:
                        st.error(f"GitHub 저장 실패: {msg}")
                else:
                    with open(ADS_DATA, "wb") as fp:
                        fp.write(a_bytes)
                    st.cache_data.clear()
                    st.success("저장 완료! 상단 탭을 새로고침하면 반영됩니다.")
                    st.rerun()

    # ============================================================== 월별 매출 데이터
    st.divider()
    st.markdown("### 🗓️ 월별 매출 데이터")
    st.markdown(
        "채널별 원본 엑셀을 **한 달치(1일~말일)**로 올려 주세요. 실제 판매일자 기준으로 달력 월에 집계합니다. "
        "(주차 데이터와 별개로 저장 — `전체 추이` 탭의 ‘월별 매출 추이’에 쓰입니다.)\n\n"
        "- 네이버 · 11번가 · 옥션 · 지마켓 = 리포트 안의 **판매일자**로 월 자동 분리\n"
        "- 쿠팡 · GS SHOP = **파일명의 월**로 인식 (예: `_0701-0731` · `_2026-07` · `_7월`)\n"
        "- 같은 채널·월 데이터는 **최신 업로드로 자동 교체**됩니다."
    )
    m_ups = st.file_uploader("월별 매출 엑셀 (여러 개 선택 가능)", type=["xlsx", "xls"],
                             accept_multiple_files=True, key="monthly_up")

    if m_ups:
        m_parsed, m_errs = [], []
        for up in m_ups:
            try:
                part = core.parse_source_monthly(up.name, io.BytesIO(up.getvalue()))
                if part.empty:
                    m_errs.append(f"{up.name}: 인식된 매출 행이 없습니다"
                                  "(파일 형식/판매일자, 쿠팡·GS는 파일명 월 확인).")
                else:
                    m_parsed.append(part)
            except Exception as e:
                m_errs.append(f"{up.name}: {e}")
        for e in m_errs:
            st.error(e)

        if m_parsed:
            m_new = pd.concat(m_parsed, ignore_index=True)
            m_prev = monthly_df.copy()
            if not m_prev.empty:
                m_prev["월"] = m_prev["월"].astype(str)
            m_merged = core.merge_monthly(m_prev, m_new)

            st.markdown("**미리보기 — 반영될 (채널 × 월) 매출**")
            m_piv = m_merged.pivot_table(index="채널", columns="월", values="매출",
                                         aggfunc="sum", fill_value=0)
            m_cols = sorted(m_piv.columns)
            st.dataframe(m_piv.reindex(columns=m_cols).style.format("{:,.0f}"),
                         use_container_width=True)
            m_changed = m_new[["채널", "월"]].drop_duplicates()
            st.caption("변경 대상: " + ", ".join(f"{r.채널}·{r.월}" for r in m_changed.itertuples()))

            if st.button("💾 월별 매출 저장하기", type="primary", key="monthly_save"):
                m_bytes = m_merged[core.MONTHLY_TIDY_COLS].to_csv(
                    index=False, encoding="utf-8-sig").encode("utf-8-sig")
                if gh:
                    ok, msg = github_commit(gh, "data/monthly_tidy.csv", m_bytes,
                                            "월별 매출 데이터 업데이트")
                    if ok:
                        st.success("저장 완료! 30초~1분 뒤 대시보드에 반영됩니다. (자동 재배포)")
                        st.cache_data.clear()
                    else:
                        st.error(f"GitHub 저장 실패: {msg}")
                else:
                    with open(MONTHLY_DATA, "wb") as fp:
                        fp.write(m_bytes)
                    st.cache_data.clear()
                    st.success("저장 완료! 상단 탭을 새로고침하면 반영됩니다.")
                    st.rerun()
