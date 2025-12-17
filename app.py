import streamlit as st
import pandas as pd
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import re
from collections import defaultdict
import time
import plotly.graph_objects as go

# ==================================================
# Streamlit 設定
# ==================================================
st.set_page_config(page_title="💰 Financial Freedom Dashboard", layout="wide")
st.caption(f"DEBUG: build={int(time.time())}")

# ==================================================
# Google Sheets 設定
# ==================================================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1pb1IH1twG9XDIo6Ma88XKcndnnet-dlHxQPu9zjbJ5w/edit?gid=2102244245#gid=2102244245"

# ==================================================
# Google Sheets 接続
# ==================================================
def get_spreadsheet():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
    service = build("sheets", "v4", credentials=creds)
    return service.spreadsheets()

# ==================================================
# データ読み込み
# ==================================================
@st.cache_data(ttl=60)
def load_data():
    sheet = get_spreadsheet()
    spreadsheet_id = SPREADSHEET_URL.split("/d/")[1].split("/")[0]

    def get_df(sheet_name, range_):
        try:
            res = sheet.values().get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!{range_}").execute()
            values = res.get("values", [])
            if not values:
                return pd.DataFrame()
            return pd.DataFrame(values[1:], columns=values[0])
        except Exception:
            return pd.DataFrame()

    df_params  = get_df("Parameters",  "A:D")
    df_fix     = get_df("Fix_Cost",    "A:G")
    df_forms   = get_df("Forms_Log",   "A:G")
    df_balance = get_df("Balance_Log", "A:C")
    df_goals   = get_df("Goals", "A:F")  # 必要ならA:Gなどに拡張
    return df_params, df_fix, df_forms, df_balance, df_goals

# ==================================================
# 前処理（型だけ整える）
# ==================================================
def preprocess_data(df_params, df_fix, df_forms, df_balance):
    if not df_params.empty and "適用開始日" in df_params.columns:
        df_params["適用開始日"] = pd.to_datetime(df_params["適用開始日"], errors="coerce")

    if not df_fix.empty:
        if "開始日" in df_fix.columns:
            df_fix["開始日"] = pd.to_datetime(df_fix["開始日"], errors="coerce")
        if "終了日" in df_fix.columns:
            df_fix["終了日"] = pd.to_datetime(df_fix["終了日"], errors="coerce")
        if "金額" in df_fix.columns:
            df_fix["金額"] = pd.to_numeric(df_fix["金額"], errors="coerce").fillna(0)
        if "サイクル" in df_fix.columns:
            df_fix["サイクル"] = df_fix["サイクル"].fillna("毎月")

    # ★ Google Form の日付は mm/dd/yyyy でも yyyy/mm/dd でも pd.to_datetime で読み込めます
    if not df_forms.empty:
        if "日付" in df_forms.columns:
            df_forms["日付"] = pd.to_datetime(df_forms["日付"], errors="coerce")
        if "金額" in df_forms.columns:
            df_forms["金額"] = pd.to_numeric(df_forms["金額"], errors="coerce").fillna(0)
        if "満足度" in df_forms.columns:
            df_forms["満足度"] = pd.to_numeric(df_forms["満足度"], errors="coerce")

    if not df_balance.empty:
        if "日付" in df_balance.columns:
            df_balance["日付"] = pd.to_datetime(df_balance["日付"], errors="coerce")
        if "銀行残高" in df_balance.columns:
            df_balance["銀行残高"] = pd.to_numeric(df_balance["銀行残高"], errors="coerce")
        if "NISA評価額" in df_balance.columns:
            df_balance["NISA評価額"] = pd.to_numeric(df_balance["NISA評価額"], errors="coerce")

    return df_params, df_fix, df_forms, df_balance

# ==================================================
# Parameters 取得（履歴対応）
# ==================================================
def get_latest_parameter(df, item, target_date):
    if df.empty:
        return None
    if not {"項目", "値", "適用開始日"}.issubset(set(df.columns)):
        return None

    d = df.copy()
    d = d[d["項目"] == item]
    d = d.dropna(subset=["適用開始日"])
    d = d[d["適用開始日"] <= target_date]
    if d.empty:
        return None
    return d.sort_values("適用開始日").iloc[-1]["値"]

def to_float_safe(x, default=0.0):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

# ==================================================
# 固定費（今月）
# ==================================================
def calculate_monthly_fix_cost(df_fix, today):
    if df_fix.empty:
        return 0.0
    needed_cols = {"開始日", "終了日", "金額"}
    if not needed_cols.issubset(set(df_fix.columns)):
        return 0.0

    d = df_fix.copy()
    active = d[
        (d["開始日"].notna()) &
        (d["開始日"] <= today) &
        ((d["終了日"].isna()) | (d["終了日"] >= today))
    ]
    return float(active["金額"].sum())

# ==================================================
# 変動費 / 変動収入（今月） ★日付形式に強い
# ==================================================
EXPENSE_CATEGORIES = [
    "食費（外食・交際）",
    "食費（日常）",
    "趣味・娯楽",
    "研究・書籍",
    "日用品",
    "交通費",
    "その他",
]
INCOME_CATEGORIES = ["給与・バイト代", "臨時収入"]

def calculate_monthly_variable_cost(df_forms, today):
    if df_forms.empty:
        return 0.0
    if not {"日付", "金額", "費目"}.issubset(set(df_forms.columns)):
        return 0.0

    d = df_forms.copy()
    d["日付"] = pd.to_datetime(d["日付"], errors="coerce")
    d["金額"] = pd.to_numeric(d["金額"], errors="coerce").fillna(0)

    current_month = pd.Period(pd.to_datetime(today), freq="M")
    d["month"] = d["日付"].dt.to_period("M")

    return float(d[(d["month"] == current_month) & (d["費目"].isin(EXPENSE_CATEGORIES))]["金額"].sum())

def calculate_monthly_variable_income(df_forms, today):
    if df_forms.empty:
        return 0.0
    if not {"日付", "金額", "費目"}.issubset(set(df_forms.columns)):
        return 0.0

    d = df_forms.copy()
    d["日付"] = pd.to_datetime(d["日付"], errors="coerce")
    d["金額"] = pd.to_numeric(d["金額"], errors="coerce").fillna(0)

    current_month = pd.Period(pd.to_datetime(today), freq="M")
    d["month"] = d["日付"].dt.to_period("M")

    return float(d[(d["month"] == current_month) & (d["費目"].isin(INCOME_CATEGORIES))]["金額"].sum())

# ==================================================
# 残高（最新）
# ==================================================
def get_latest_bank_balance(df_balance):
    if df_balance.empty:
        return None
    if not {"日付", "銀行残高"}.issubset(set(df_balance.columns)):
        return None

    d = df_balance.copy().dropna(subset=["日付", "銀行残高"]).sort_values("日付")
    if d.empty:
        return None
    return float(d.iloc[-1]["銀行残高"])

def get_latest_total_asset(df_balance):
    if df_balance.empty:
        return 0.0
    if not {"日付", "銀行残高", "NISA評価額"}.issubset(set(df_balance.columns)):
        return 0.0

    d = df_balance.copy().dropna(subset=["日付"]).sort_values("日付")
    d = d.dropna(subset=["銀行残高", "NISA評価額"])
    if d.empty:
        return 0.0
    return float(d.iloc[-1]["銀行残高"] + d.iloc[-1]["NISA評価額"])

# ==================================================
# NISA 積立計算（モード A/B/C）
# ==================================================
def calculate_nisa_amount(df_params, today, available_cash, current_asset):
    mode = get_latest_parameter(df_params, "NISA積立モード", today)
    mode = str(mode).strip() if mode is not None else "C"

    min_nisa = to_float_safe(get_latest_parameter(df_params, "NISA最低積立額", today), default=0.0)
    max_nisa = to_float_safe(get_latest_parameter(df_params, "NISA最大積立額", today), default=0.0)
    target_asset = to_float_safe(get_latest_parameter(df_params, "目標資産額", today), default=100_000_000.0)
    retire_age = to_float_safe(get_latest_parameter(df_params, "老後年齢", today), default=60.0)

    # Profile未導入なので仮（将来profileで置換）
    current_age = 20.0

    if max_nisa <= 0:
        max_nisa = float(available_cash)

    if mode == "A":
        nisa = min_nisa
    elif mode == "B":
        years_left = max(retire_age - current_age, 1)
        months_left = years_left * 12
        ideal = (target_asset - current_asset) / months_left
        nisa = max(min(ideal, max_nisa), min_nisa)
    else:
        nisa = max(min(float(available_cash), max_nisa), min_nisa)

    nisa = max(min(float(nisa), float(available_cash)), 0.0)
    return float(nisa), mode

# ==================================================
# 赤字分析
# ==================================================
def analyze_deficit(monthly_income, fix_cost, variable_cost):
    total_deficit = (fix_cost + variable_cost) - monthly_income
    if total_deficit <= 0:
        return None

    variable_expected = monthly_income * 0.3
    fix_over = max(fix_cost - monthly_income, 0.0)
    var_over = max(variable_cost - variable_expected, 0.0)

    return {
        "total_deficit": float(total_deficit),
        "fix_over": float(fix_over),
        "var_over": float(var_over),
        "var_expected": float(variable_expected),
        "var_actual": float(variable_cost),
    }

# ==================================================
# メモ頻出分析（強化版）
# ==================================================
def analyze_memo_frequency_advanced(df_forms, today, is_deficit, variable_cost, monthly_income, top_n=5):
    variable_expected = monthly_income * 0.3
    if (not is_deficit) and (variable_cost <= variable_expected):
        return []

    if df_forms.empty or not {"日付", "金額", "満足度", "メモ"}.issubset(set(df_forms.columns)):
        return []

    current_month = pd.Period(pd.to_datetime(today), freq="M")
    d = df_forms.copy()
    d["month"] = d["日付"].dt.to_period("M")

    target = d[(d["month"] == current_month) & (d["満足度"] <= 2) & (d["メモ"].notna())]
    if target.empty:
        return []

    memo_stats = defaultdict(lambda: {"count": 0, "amount": 0.0})
    for _, row in target.iterrows():
        words = re.findall(r"[一-龥ぁ-んァ-ンA-Za-z0-9]+", str(row["メモ"]))
        for w in words:
            memo_stats[w]["count"] += 1
            memo_stats[w]["amount"] += float(row["金額"])

    result = [(word, v["count"], v["amount"]) for word, v in memo_stats.items()]
    result.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return result[:top_n]

def analyze_memo_by_category(df_forms, today, is_deficit, variable_cost, monthly_income):
    variable_expected = monthly_income * 0.3
    if (not is_deficit) and (variable_cost <= variable_expected):
        return {}

    if df_forms.empty or not {"日付", "金額", "満足度", "メモ", "費目"}.issubset(set(df_forms.columns)):
        return {}

    current_month = pd.Period(pd.to_datetime(today), freq="M")
    d = df_forms.copy()
    d["month"] = d["日付"].dt.to_period("M")

    target = d[(d["month"] == current_month) & (d["満足度"] <= 2) & (d["メモ"].notna())]
    if target.empty:
        return {}

    result = {}
    for _, row in target.iterrows():
        category = row["費目"]
        memo = row["メモ"]

        result.setdefault(category, {})
        result[category].setdefault(memo, {"count": 0, "amount": 0.0})
        result[category][memo]["count"] += 1
        result[category][memo]["amount"] += float(row["金額"])

    return result

# ==================================================
# 最近増えている費目（直近月 vs 過去3か月平均）
# ==================================================
def analyze_category_trend_3m(df_forms, today):
    if df_forms.empty or not {"日付", "金額", "費目"}.issubset(set(df_forms.columns)):
        return []

    d = df_forms.copy()
    d = d[d["費目"].isin(EXPENSE_CATEGORIES)]
    d["month"] = d["日付"].dt.to_period("M").astype(str)

    current_month = pd.Period(pd.to_datetime(today), freq="M").strftime("%Y-%m")
    months = pd.period_range(end=pd.Period(current_month, freq="M"), periods=4, freq="M").astype(str)
    d = d[d["month"].isin(months)]
    if d.empty:
        return []

    pivot = (
        d.groupby(["month", "費目"], as_index=False)["金額"]
        .sum()
        .pivot(index="費目", columns="month", values="金額")
        .fillna(0)
    )

    if current_month not in pivot.columns:
        return []

    past_months = [m for m in pivot.columns if m != current_month]
    if not past_months:
        return []

    pivot["past_3m_avg"] = pivot[past_months].mean(axis=1)
    pivot["diff"] = pivot[current_month] - pivot["past_3m_avg"]

    increased = pivot[pivot["diff"] > 0].sort_values("diff", ascending=False)

    result = []
    for category, row in increased.iterrows():
        result.append({
            "category": category,
            "current": float(row[current_month]),
            "past_avg": float(row["past_3m_avg"]),
            "diff": float(row["diff"]),
        })
    return result

# ==================================================
# 生活防衛費（月次シリーズ作成）
# ==================================================
def build_month_list(today, months_back=12):
    end = pd.Period(pd.to_datetime(today).strftime("%Y-%m"), freq="M")
    return list(pd.period_range(end=end, periods=months_back, freq="M").astype(str))

def monthly_variable_cost_series(df_forms, months):
    if df_forms.empty or not {"日付", "金額", "費目"}.issubset(set(df_forms.columns)):
        return pd.Series(0.0, index=months, dtype=float)

    d = df_forms.copy()
    d = d[d["費目"].isin(EXPENSE_CATEGORIES)]
    d["month"] = d["日付"].dt.to_period("M").astype(str)

    s = d.groupby("month")["金額"].sum().reindex(months, fill_value=0.0).astype(float)
    return s

def monthly_fix_cost_series(df_fix, months):
    if df_fix.empty or not {"開始日", "終了日", "金額", "サイクル"}.issubset(set(df_fix.columns)):
        return pd.Series(0.0, index=months, dtype=float)

    d = df_fix.copy()
    out = pd.Series(0.0, index=months, dtype=float)

    for m in months:
        p = pd.Period(m, freq="M")
        month_start = p.start_time
        month_end = p.end_time

        active = d[
            (d["開始日"].notna()) &
            (d["開始日"] <= month_end) &
            ((d["終了日"].isna()) | (d["終了日"] >= month_start))
        ].copy()

        if active.empty:
            continue

        active["monthly_amount"] = active.apply(
            lambda r: r["金額"] if "毎月" in str(r["サイクル"]) else (r["金額"] / 12.0 if "毎年" in str(r["サイクル"]) else r["金額"]),
            axis=1
        )

        out[m] = float(active["monthly_amount"].sum())

    return out

def estimate_emergency_fund(df_params, df_fix, df_forms, today):
    n = get_latest_parameter(df_params, "生活防衛費係数（月のN数）", today)
    try:
        n_months = int(float(n))
    except Exception:
        n_months = 6

    months = build_month_list(today, months_back=12)
    fix_s = monthly_fix_cost_series(df_fix, months)
    var_s = monthly_variable_cost_series(df_forms, months)
    total_s = fix_s + var_s

    nonzero = total_s[total_s > 0]
    if len(nonzero) == 0:
        base = float(calculate_monthly_fix_cost(df_fix, today) + calculate_monthly_variable_cost(df_forms, today))
        p75 = base
        method = "暫定（今月のみ）"
    else:
        base = float(nonzero.median())
        p75 = float(nonzero.quantile(0.75))
        method = f"過去{int(len(nonzero))}か月（中央値・P75）"

    min_months = 3
    comfort_months = 9

    fund_min = base * min_months
    fund_rec = base * n_months
    fund_comfort = p75 * comfort_months

    return {
        "months_factor": n_months,
        "method": method,
        "monthly_est_median": base,
        "monthly_est_p75": p75,
        "fund_min": fund_min,
        "fund_rec": fund_rec,
        "fund_comfort": fund_comfort,
        "fund_median": fund_rec,
        "fund_p75": p75 * n_months,
        "series_fix": fix_s,
        "series_var": var_s,
        "series_total": total_s,
    }

# ==================================================
# 生活防衛費ステータスによる NISA 調整
# ==================================================
def adjust_nisa_by_emergency_status(nisa_amount, safe_cash, ef):
    if safe_cash is None:
        return float(nisa_amount), "銀行残高が未取得のため調整なし"
    if safe_cash < ef["fund_min"]:
        return 0.0, "危険ゾーン：NISA停止"
    if safe_cash < ef["fund_rec"]:
        return float(int(nisa_amount * 0.5)), "最低限ゾーン：NISA 50%抑制"
    return float(nisa_amount), "推奨以上：抑制なし"

# ==================================================
# 今月サマリー
# ==================================================
def calculate_monthly_summary(df_params, df_fix, df_forms, df_balance, today):
    base_income = to_float_safe(get_latest_parameter(df_params, "月収", today), default=0.0)
    variable_income = calculate_monthly_variable_income(df_forms, today)
    monthly_income = base_income + variable_income

    fix_cost = calculate_monthly_fix_cost(df_fix, today)
    variable_cost = calculate_monthly_variable_cost(df_forms, today)

    available_cash = max(monthly_income - fix_cost - variable_cost, 0.0)
    current_asset = get_latest_total_asset(df_balance)

    nisa_amount, nisa_mode = calculate_nisa_amount(df_params, today, available_cash, current_asset)
    bank_save = max(available_cash - nisa_amount, 0.0)

    return {
        "monthly_income": float(monthly_income),
        "base_income": float(base_income),
        "variable_income": float(variable_income),
        "fix_cost": float(fix_cost),
        "variable_cost": float(variable_cost),
        "bank_save": float(bank_save),
        "nisa_save": float(nisa_amount),
        "free_cash": float(max(available_cash - bank_save - nisa_amount, 0.0)),
        "nisa_mode": nisa_mode,
        "current_asset": float(current_asset),
        "available_cash": float(available_cash),
    }

# ==================================================
# 資産推移グラフ
# ==================================================
def plot_asset_trend(df_balance, ef):
    if df_balance.empty:
        st.info("Balance_Log にデータがないため、資産推移を表示できません。")
        return

    required_cols = {"日付", "銀行残高", "NISA評価額"}
    if not required_cols.issubset(set(df_balance.columns)):
        st.info("Balance_Log の列が不足しています。")
        return

    df = df_balance.copy()
    df = df.dropna(subset=["日付"]).sort_values("日付")

    df["銀行残高"] = pd.to_numeric(df["銀行残高"], errors="coerce").fillna(0)
    df["NISA評価額"] = pd.to_numeric(df["NISA評価額"], errors="coerce").fillna(0)
    df["合計資産"] = df["銀行残高"] + df["NISA評価額"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["日付"], y=df["銀行残高"], mode="lines+markers", name="🏦 銀行残高"))
    fig.add_trace(go.Scatter(x=df["日付"], y=df["NISA評価額"], mode="lines+markers", name="📈 NISA評価額"))
    fig.add_trace(go.Scatter(x=df["日付"], y=df["合計資産"], mode="lines+markers", name="💰 合計資産", line=dict(width=4)))

    fig.add_hline(y=ef["fund_rec"], line_dash="dash", annotation_text="🛡️ 生活防衛費（推奨）", annotation_position="top left")
    fig.add_hline(y=ef["fund_min"], line_dash="dot", annotation_text="⚠️ 生活防衛費（最低）", annotation_position="bottom left")

    fig.update_layout(
        title="📊 資産推移（銀行・NISA・合計）",
        xaxis_title="日付",
        yaxis_title="金額（円）",
        hovermode="x unified",
        height=500
    )
    st.plotly_chart(fig, use_container_width=True)

# ==================================================
# 将来シミュレーション：共通関数
# ==================================================
def solve_required_monthly_pmt(pv, fv_target, r_month, n_months):
    pv = float(pv)
    fv_target = float(fv_target)
    n = int(max(n_months, 1))

    if r_month <= 0:
        return max((fv_target - pv) / n, 0.0)

    a = (1 + r_month) ** n
    denom = (a - 1) / r_month
    pmt = (fv_target - pv * a) / denom
    return max(float(pmt), 0.0)

def apply_outflow_bank_first(bank, nisa, outflow):
    bank = float(bank)
    nisa = float(nisa)
    outflow = float(outflow)

    used_bank = min(bank, outflow)
    bank -= used_bank
    remain = outflow - used_bank

    used_nisa = min(nisa, remain)
    nisa -= used_nisa

    unpaid = remain - used_nisa
    return bank, nisa, used_bank, used_nisa, unpaid

# ==================================================
# Goals：通貨変換（今はJPYのみ）
# ==================================================
def convert_to_jpy_stub(amount, currency, date=None):
    try:
        a = float(amount)
    except:
        return None
    c = str(currency).strip().upper() if currency is not None else "JPY"
    if c == "JPY" or c == "":
        return a
    return a

# ==================================================
# 機能①：Goalsに「達成年齢」がある場合、達成期限を補完
# ==================================================
def enrich_goals_deadline_by_age(df_goals, today, current_age):
    if df_goals is None or df_goals.empty:
        return df_goals

    df = df_goals.copy()

    if "達成年齢" not in df.columns:
        return df

    if "達成期限" not in df.columns:
        df["達成期限"] = None

    df["達成期限"] = pd.to_datetime(df["達成期限"], errors="coerce")
    df["達成年齢"] = pd.to_numeric(df["達成年齢"], errors="coerce")

    m = df["達成期限"].isna() & df["達成年齢"].notna()
    if not m.any():
        return df

    base = pd.to_datetime(today).normalize().replace(day=1)
    months = ((df.loc[m, "達成年齢"] - float(current_age)) * 12).round().astype(int).clip(lower=0)
    df.loc[m, "達成期限"] = [base + pd.DateOffset(months=int(k)) for k in months]
    return df

# ==================================================
# 機能③：Goals(支出)の先送り/削除
# ==================================================
def apply_deferral_to_goals_df(df_goals, selected_names, defer_months, delete_instead=False):
    if df_goals is None or df_goals.empty:
        return df_goals

    df = df_goals.copy()
    if "目標名" not in df.columns or "タイプ" not in df.columns:
        return df
    if "達成期限" not in df.columns:
        return df

    df["達成期限"] = pd.to_datetime(df.get("達成期限"), errors="coerce")
    m = (df["タイプ"].astype(str).str.strip() == "支出") & (df["目標名"].isin(selected_names))

    if delete_instead:
        return df.loc[~m].copy()

    defer_months = int(defer_months)
    df.loc[m, "達成期限"] = df.loc[m, "達成期限"] + pd.DateOffset(months=defer_months)
    return df

# ==================================================
# Goals をイベント化
# ==================================================
def prepare_goals_events(df_goals, today):
    if df_goals is None or df_goals.empty:
        return {}, {}

    df = df_goals.copy()
    required = ["目標名", "金額", "通貨", "達成期限", "優先度", "タイプ"]
    for col in required:
        if col not in df.columns:
            return {}, {}

    df["達成期限"] = pd.to_datetime(df["達成期限"], errors="coerce")
    df = df.dropna(subset=["達成期限"])
    if df.empty:
        return {}, {}

    df = df[df["達成期限"] >= pd.to_datetime(today).normalize()]
    df["month"] = df["達成期限"].dt.to_period("M").astype(str)

    outflows_by_month = {}
    targets_by_month = {}

    for _, r in df.iterrows():
        name = str(r["目標名"])
        typ = str(r["タイプ"]).strip()
        prio = str(r["優先度"]).strip()
        m = str(r["month"])

        amt = convert_to_jpy_stub(r["金額"], r["通貨"], r["達成期限"])
        if amt is None:
            continue

        item = {
            "name": name,
            "amount": float(amt),
            "priority": prio,
            "deadline": r["達成期限"],
        }

        if typ == "支出":
            outflows_by_month.setdefault(m, []).append(item)
        else:
            targets_by_month.setdefault(m, []).append(item)

    return outflows_by_month, targets_by_month

# ==================================================
# Parameters から「比率セット」を取得
# ==================================================
def get_ideal_nisa_ratios_from_params(df_params, today):
    def g(name, default):
        v = get_latest_parameter(df_params, name, today)
        try:
            return float(v)
        except:
            return default

    return {
        "safe": g("理想NISA比率_安心", 0.85),
        "rec": g("理想NISA比率_推奨", 0.70),
        "min": g("理想NISA比率_最低限", 0.50),
        "danger": g("理想NISA比率_危険", 0.00),
    }

def choose_ideal_nisa_ratio_by_emergency_from_params(safe_cash, ef, ratios: dict):
    if safe_cash is None:
        return ratios["rec"]
    if safe_cash < ef["fund_min"]:
        return ratios["danger"]
    if safe_cash < ef["fund_rec"]:
        return ratios["min"]
    if safe_cash < ef["fund_comfort"]:
        return ratios["rec"]
    return ratios["safe"]

# ==================================================
# 将来シミュレーション（v3：月ごと比率＋Goals）
# ==================================================
def simulate_future_paths_v3_dynamic_ratio(
    *,
    today,
    current_bank,
    current_nisa,
    monthly_bank_save_plan,
    monthly_nisa_save_plan,
    annual_return,
    inflation_rate,
    current_age,
    end_age,
    target_real_today,
    ef,
    ideal_ratios,
    df_goals=None,
    bank_min_monthly=0.0,
):
    current_bank = float(current_bank)
    current_nisa = float(current_nisa)
    monthly_bank_save_plan = float(monthly_bank_save_plan)
    monthly_nisa_save_plan = float(monthly_nisa_save_plan)
    annual_return = float(annual_return)
    inflation_rate = float(inflation_rate)
    bank_min_monthly = float(bank_min_monthly)

    r = (1 + annual_return) ** (1 / 12) - 1 if annual_return > -1 else 0.0
    inf_m = (1 + inflation_rate) ** (1 / 12) - 1 if inflation_rate > -1 else 0.0

    months_left = int(max((float(end_age) - float(current_age)) * 12, 1))
    dates = pd.date_range(start=pd.to_datetime(today).normalize(), periods=months_left + 1, freq="MS")

    target_real_curve = [float(target_real_today) * ((1 + inf_m) ** i) for i in range(len(dates))]
    target_real_end = target_real_curve[-1]

    pv_total = current_bank + current_nisa
    ideal_pmt = solve_required_monthly_pmt(
        pv=pv_total,
        fv_target=float(target_real_end),
        r_month=r,
        n_months=months_left
    )

    outflows_by_month, targets_by_month = prepare_goals_events(df_goals, today)

    bank = current_bank
    nisa = current_nisa
    ideal_bank = current_bank
    ideal_nisa = current_nisa

    rows = []
    for i, dt in enumerate(dates):
        month_key = pd.Period(dt, freq="M").strftime("%Y-%m")

        items = outflows_by_month.get(month_key, [])
        outflow = float(sum(x["amount"] for x in items)) if items else 0.0

        outflow_name = ""
        if items:
            names = [x["name"] for x in items]
            outflow_name = " / ".join(names[:3]) + (" …" if len(names) > 3 else "")

        used_bank = used_nisa = 0.0
        used_ideal_bank = used_ideal_nisa = 0.0

        if outflow > 0:
            bank, nisa, used_bank, used_nisa, unpaid_real = apply_outflow_bank_first(bank, nisa, outflow)
            ideal_bank, ideal_nisa, used_ideal_bank, used_ideal_nisa, unpaid_ideal = apply_outflow_bank_first(ideal_bank, ideal_nisa, outflow)
        else:
            unpaid_real = 0.0
            unpaid_ideal = 0.0

        total = bank + nisa
        ideal_total = ideal_bank + ideal_nisa

        safe_cash_sim = ideal_bank
        ratio = choose_ideal_nisa_ratio_by_emergency_from_params(
            safe_cash=safe_cash_sim,
            ef=ef,
            ratios=ideal_ratios
        )
        ratio = min(max(float(ratio), 0.0), 1.0)

        bank_first = min(bank_min_monthly, ideal_pmt)
        remaining = max(ideal_pmt - bank_first, 0.0)
        ideal_bank_add = bank_first + remaining * (1 - ratio)
        ideal_nisa_add = remaining * ratio

        goal_items = targets_by_month.get(month_key, [])
        goal_count = len(goal_items)
        achieved_real = 0
        achieved_ideal_
