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
# 前処理
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

    if not df_forms.empty:
        if "日付" in df_forms.columns:
            # mm/dd/yyyy でも yyyy/mm/dd でも読み取る（pandasに任せる）
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
# Parameters 取得
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
# 固定費
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
# 変動費/変動収入（今月）  ★to_periodで頑丈
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
    if df_forms.empty or not {"日付", "金額", "費目"}.issubset(set(df_forms.columns)):
        return 0.0
    d = df_forms.copy()
    d["日付"] = pd.to_datetime(d["日付"], errors="coerce")
    d["金額"] = pd.to_numeric(d["金額"], errors="coerce").fillna(0)
    current_month = pd.Period(pd.to_datetime(today), freq="M")
    d["month"] = d["日付"].dt.to_period("M")
    return float(d[(d["month"] == current_month) & (d["費目"].isin(EXPENSE_CATEGORIES))]["金額"].sum())

def calculate_monthly_variable_income(df_forms, today):
    if df_forms.empty or not {"日付", "金額", "費目"}.issubset(set(df_forms.columns)):
        return 0.0
    d = df_forms.copy()
    d["日付"] = pd.to_datetime(d["日付"], errors="coerce")
    d["金額"] = pd.to_numeric(d["金額"], errors="coerce").fillna(0)
    current_month = pd.Period(pd.to_datetime(today), freq="M")
    d["month"] = d["日付"].dt.to_period("M")
    return float(d[(d["month"] == current_month) & (d["費目"].isin(INCOME_CATEGORIES))]["金額"].sum())

# ==================================================
# 残高
# ==================================================
def get_latest_bank_balance(df_balance):
    if df_balance.empty or not {"日付", "銀行残高"}.issubset(set(df_balance.columns)):
        return None
    d = df_balance.copy().dropna(subset=["日付", "銀行残高"]).sort_values("日付")
    if d.empty:
        return None
    return float(d.iloc[-1]["銀行残高"])

def get_latest_total_asset(df_balance):
    if df_balance.empty or not {"日付", "銀行残高", "NISA評価額"}.issubset(set(df_balance.columns)):
        return 0.0
    d = df_balance.copy().dropna(subset=["日付"]).sort_values("日付")
    d = d.dropna(subset=["銀行残高", "NISA評価額"])
    if d.empty:
        return 0.0
    return float(d.iloc[-1]["銀行残高"] + d.iloc[-1]["NISA評価額"])

# ==================================================
# NISA
# ==================================================
def calculate_nisa_amount(df_params, today, available_cash, current_asset):
    mode = get_latest_parameter(df_params, "NISA積立モード", today)
    mode = str(mode).strip() if mode is not None else "C"
    min_nisa = to_float_safe(get_latest_parameter(df_params, "NISA最低積立額", today), default=0.0)
    max_nisa = to_float_safe(get_latest_parameter(df_params, "NISA最大積立額", today), default=0.0)
    target_asset = to_float_safe(get_latest_parameter(df_params, "目標資産額", today), default=100_000_000.0)
    retire_age = to_float_safe(get_latest_parameter(df_params, "老後年齢", today), default=60.0)
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
# 赤字
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
# メモ分析
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
# 最近増えている費目
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
# 生活防衛費
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
    return d.groupby("month")["金額"].sum().reindex(months, fill_value=0.0).astype(float)

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
# NISA調整
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
# 資産推移
# ==================================================
def plot_asset_trend(df_balance, ef):
    if df_balance.empty:
        st.info("Balance_Log にデータがないため、資産推移を表示できません。")
        return
    required_cols = {"日付", "銀行残高", "NISA評価額"}
    if not required_cols.issubset(set(df_balance.columns)):
        st.info("Balance_Log の列が不足しています。")
        return

    df = df_balance.copy().dropna(subset=["日付"]).sort_values("日付")
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
# 将来シミュレーション共通
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
    bank = float(bank); nisa = float(nisa); outflow = float(outflow)
    used_bank = min(bank, outflow)
    bank -= used_bank
    remain = outflow - used_bank
    used_nisa = min(nisa, remain)
    nisa -= used_nisa
    unpaid = remain - used_nisa
    return bank, nisa, used_bank, used_nisa, unpaid

# ==================================================
# Goals
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

        item = {"name": name, "amount": float(amt), "priority": prio, "deadline": r["達成期限"]}
        if typ == "支出":
            outflows_by_month.setdefault(m, []).append(item)
        else:
            targets_by_month.setdefault(m, []).append(item)

    return outflows_by_month, targets_by_month

# ==================================================
# 比率
# ==================================================
def get_ideal_nisa_ratios_from_params(df_params, today):
    def g(name, default):
        v = get_latest_parameter(df_params, name, today)
        try:
            return float(v)
        except:
            return default
    return {"safe": g("理想NISA比率_安心", 0.85), "rec": g("理想NISA比率_推奨", 0.70),
            "min": g("理想NISA比率_最低限", 0.50), "danger": g("理想NISA比率_危険", 0.00)}

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
# 将来シミュレーション
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
    ideal_pmt = solve_required_monthly_pmt(pv=pv_total, fv_target=float(target_real_end), r_month=r, n_months=months_left)

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

        if outflow > 0:
            bank, nisa, used_bank, used_nisa, unpaid_real = apply_outflow_bank_first(bank, nisa, outflow)
            ideal_bank, ideal_nisa, used_ideal_bank, used_ideal_nisa, unpaid_ideal = apply_outflow_bank_first(ideal_bank, ideal_nisa, outflow)
        else:
            used_bank = used_nisa = used_ideal_bank = used_ideal_nisa = 0.0
            unpaid_real = unpaid_ideal = 0.0

        total = bank + nisa
        ideal_total = ideal_bank + ideal_nisa

        safe_cash_sim = ideal_bank
        ratio = choose_ideal_nisa_ratio_by_emergency_from_params(safe_cash=safe_cash_sim, ef=ef, ratios=ideal_ratios)
        ratio = min(max(float(ratio), 0.0), 1.0)

        bank_first = min(bank_min_monthly, ideal_pmt)
        remaining = max(ideal_pmt - bank_first, 0.0)
        ideal_bank_add = bank_first + remaining * (1 - ratio)
        ideal_nisa_add = remaining * ratio

        goal_items = targets_by_month.get(month_key, [])
        goal_count = len(goal_items)
        achieved_real = 0
        achieved_ideal = 0
        goal_note = ""
        goal_name = ""

        if goal_count > 0:
            first = goal_items[0]
            goal_name = str(first.get("name", ""))
            goal_note = f"{goal_name}（{int(first['amount']):,}円）"
            for g in goal_items:
                if total >= g["amount"]:
                    achieved_real += 1
                if ideal_total >= g["amount"]:
                    achieved_ideal += 1

        rows.append({
            "date": dt,
            "bank": bank, "nisa": nisa, "total": total,
            "ideal_bank": ideal_bank, "ideal_nisa": ideal_nisa, "ideal_total": ideal_total,
            "ideal_pmt": ideal_pmt, "ideal_nisa_ratio": ratio,
            "target_real_nominal": target_real_curve[i],
            "outflow": outflow, "outflow_name": outflow_name,
            "outflow_used_bank": used_bank, "outflow_used_nisa": used_nisa,
            "outflow_unpaid_real": unpaid_real, "outflow_unpaid_ideal": unpaid_ideal,
            "outflow_ok_real": (unpaid_real <= 0), "outflow_ok_ideal": (unpaid_ideal <= 0),
            "goal_count": goal_count, "goal_name": goal_name, "goal_note": goal_note,
            "goal_achieved_real": achieved_real, "goal_achieved_ideal": achieved_ideal,
            "gap_vs_ideal": total - ideal_total,
        })

        if i == len(dates) - 1:
            break

        bank = bank + monthly_bank_save_plan
        nisa = (nisa + monthly_nisa_save_plan) * (1 + r)
        ideal_bank = ideal_bank + ideal_bank_add
        ideal_nisa = (ideal_nisa + ideal_nisa_add) * (1 + r)

    df_sim = pd.DataFrame(rows)
    return df_sim, ideal_pmt, months_left, target_real_end

# ==================================================
# グラフ（比較線対応）
# ==================================================
def plot_future_simulation_v3(
    df_sim,
    show_goals=True,
    max_goal_marks=12,
    chart_key="future_sim",
    df_compare=None,
    compare_label="🔁 先送り/削除適用後（現実）合計資産",
):
    if df_sim is None or df_sim.empty:
        st.info("シミュレーションに必要なデータが不足しています。")
        return

    df = df_sim.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["total"], mode="lines",
        name="💰 予測（現実）合計資産",
        customdata=df[["ideal_total", "gap_vs_ideal", "target_real_nominal"]].values,
        hovertemplate=(
            "日付: %{x|%Y-%m}<br>"
            "現実（予測）合計: %{y:,.0f} 円<br>"
            "理想 合計: %{customdata[0]:,.0f} 円<br>"
            "差分（現実-理想）: %{customdata[1]:,.0f} 円<br>"
            "実質1億(今日価値)の名目目標: %{customdata[2]:,.0f} 円"
            "<extra></extra>"
        )
    ))

    if df_compare is not None and (not df_compare.empty) and ("total" in df_compare.columns):
        dc = df_compare.copy()
        dc["date"] = pd.to_datetime(dc["date"], errors="coerce")
        dc = dc.dropna(subset=["date"]).sort_values("date")
        fig.add_trace(go.Scatter(
            x=dc["date"], y=dc["total"], mode="lines",
            name=compare_label, line=dict(dash="dot"),
            hovertemplate="日付: %{x|%Y-%m}<br>合計: %{y:,.0f} 円<extra></extra>"
        ))

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["ideal_total"], mode="lines",
        name="🎯 理想 合計（実質1億ペース）",
        line=dict(dash="dash"),
        hovertemplate="日付: %{x|%Y-%m}<br>理想 合計: %{y:,.0f} 円<extra></extra>"
    ))

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["target_real_nominal"], mode="lines",
        name="🏁 実質1億(今日価値)の名目目標",
        line=dict(dash="dashdot"),
        hovertemplate="日付: %{x|%Y-%m}<br>名目目標: %{y:,.0f} 円<extra></extra>"
    ))

    for col, nm in [
        ("ideal_bank", "🏦 理想 銀行"),
        ("ideal_nisa", "📈 理想 NISA"),
        ("bank", "🏦 現実 銀行（予測）"),
        ("nisa", "📈 現実 NISA（予測）"),
    ]:
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df[col], mode="lines",
                name=nm, line=dict(dash="dot"),
                visible="legendonly",
                hovertemplate="日付: %{x|%Y-%m}<br>%{y:,.0f} 円<extra></extra>"
            ))

    if show_goals and "outflow" in df.columns:
        out_df = df[df["outflow"].fillna(0) > 0].copy()
        if not out_df.empty:
            out_df = out_df.sort_values("date").head(max_goal_marks)

            max_labels = 4
            label_idx = set()
            if len(out_df) <= max_labels:
                label_idx = set(range(len(out_df)))
            else:
                for k in range(max_labels):
                    label_idx.add(int(round(k * (len(out_df) - 1) / (max_labels - 1))))

            for i2, r2 in enumerate(out_df.itertuples()):
                x = pd.to_datetime(r2.date).to_pydatetime()
                amt = float(getattr(r2, "outflow"))
                fig.add_vline(x=x, line_dash="dot", line_width=1, opacity=0.5)
                if i2 in label_idx:
                    fig.add_annotation(
                        x=x, y=1.0, yref="paper",
                        text=f"支出 -{int(amt):,}",
                        showarrow=False, xanchor="left", yanchor="top",
                        font=dict(size=10), opacity=0.8,
                    )

    fig.update_layout(
        title="🔮 将来シミュレーション（現実 vs 理想 + 実質1億 + Goals）",
        xaxis_title="日付",
        yaxis_title="金額（円）",
        hovermode="x unified",
        height=560,
    )
    st.plotly_chart(fig, use_container_width=True, key=chart_key)
    st.caption("※ 下のバー（期間スライダー）をドラッグすると、表示期間を自由に変更できます。")

# ==================================================
# 直近積立推定
# ==================================================
def estimate_realistic_monthly_contribution(df_balance, months=6):
    if df_balance.empty:
        return 0.0
    df = df_balance.copy()
    df["日付"] = pd.to_datetime(df["日付"], errors="coerce")
    df["銀行残高"] = pd.to_numeric(df["銀行残高"], errors="coerce")
    df["NISA評価額"] = pd.to_numeric(df["NISA評価額"], errors="coerce")
    df = df.dropna(subset=["日付"]).sort_values("日付")
    if df.empty or len(df) < 2:
        return 0.0
    df["total"] = df["銀行残高"].fillna(0) + df["NISA評価額"].fillna(0)
    df["month"] = df["日付"].dt.to_period("M").astype(str)
    monthly_last = df.groupby("month", as_index=False)["total"].last()
    monthly_last["diff"] = monthly_last["total"].diff()
    diffs = monthly_last["diff"].dropna().tail(months)
    if diffs.empty:
        return 0.0
    return float(diffs[diffs > 0].mean()) if (diffs > 0).any() else 0.0

# ==================================================
# UI
# ==================================================
def main():
    st.title("💰 今月サマリー")

    df_params, df_fix, df_forms, df_balance, df_goals = load_data()
    df_params, df_fix, df_forms, df_balance = preprocess_data(df_params, df_fix, df_forms, df_balance)

    today = datetime.today()

    ef = estimate_emergency_fund(df_params, df_fix, df_forms, today)
    safe_cash = get_latest_bank_balance(df_balance)

    summary = calculate_monthly_summary(df_params, df_fix, df_forms, df_balance, today)

    adjusted_nisa, nisa_reason = adjust_nisa_by_emergency_status(summary["nisa_save"], safe_cash, ef)
    bank_save_adjusted = summary["bank_save"] + (summary["nisa_save"] - adjusted_nisa)

    col1, col2, col3 = st.columns(3)
    col1.metric("🏦 銀行への積立", f"{int(bank_save_adjusted):,} 円")
    col2.metric(f"📈 NISA積立（モード {summary['nisa_mode']}）", f"{int(adjusted_nisa):,} 円")
    col3.metric("🎉 自由に使えるお金", f"{int(summary['free_cash']):,} 円")

    st.caption(f"生活防衛費ステータスによるNISA調整：{nisa_reason}")
    st.caption(
        f"月収：{int(summary['monthly_income']):,} 円 "
        f"(固定 {int(summary['base_income']):,} / 臨時 {int(summary['variable_income']):,})"
    )
    st.caption(f"固定費：{int(summary['fix_cost']):,} 円 / 変動費：{int(summary['variable_cost']):,} 円")
    st.caption(f"※ 現在資産：{int(summary['current_asset']):,} 円")

    deficit = analyze_deficit(summary["monthly_income"], summary["fix_cost"], summary["variable_cost"])
    if deficit is not None:
        st.warning(f"⚠️ 今月は {int(deficit['total_deficit']):,} 円の赤字です")

    st.subheader("📊 資産推移")
    plot_asset_trend(df_balance, ef)

    # ==========================================
    # 将来シミュレーション
    # ==========================================
    st.subheader("🔮 将来シミュレーション（実質1億＋内訳）")

    annual_return = to_float_safe(get_latest_parameter(df_params, "投資年利", today), default=0.05)
    inflation_rate = to_float_safe(get_latest_parameter(df_params, "インフレ率", today), default=0.02)
    end_age = to_float_safe(get_latest_parameter(df_params, "老後年齢", today), default=60.0)
    current_age = to_float_safe(get_latest_parameter(df_params, "現在年齢", today), default=20.0)
    bank_min_monthly = to_float_safe(get_latest_parameter(df_params, "銀行最低積立額", today), default=0.0)

    target_real_today = 100_000_000.0
    ideal_ratios = get_ideal_nisa_ratios_from_params(df_params, today)

    current_bank = get_latest_bank_balance(df_balance) or 0.0
    current_nisa = 0.0
    if not df_balance.empty and {"日付", "NISA評価額"}.issubset(df_balance.columns):
        dtmp = df_balance.dropna(subset=["日付"]).sort_values("日付")
        if not dtmp.empty:
            v = pd.to_numeric(dtmp.iloc[-1]["NISA評価額"], errors="coerce")
            current_nisa = 0.0 if pd.isna(v) else float(v)

    real_total_pmt = estimate_realistic_monthly_contribution(df_balance, months=6)
    den = float(bank_save_adjusted + adjusted_nisa)
    nisa_share = (adjusted_nisa / den) if den > 0 else 0.5
    monthly_nisa_save_plan = real_total_pmt * nisa_share
    monthly_bank_save_plan = real_total_pmt * (1 - nisa_share)

    st.caption(
        f"現実（予測）に使う月次積立（直近平均）：{int(real_total_pmt):,} 円 / 月 "
        f"（銀行 {int(monthly_bank_save_plan):,} ・NISA {int(monthly_nisa_save_plan):,}）"
    )

    # 機能①：達成年齢→達成期限
    df_goals_base = enrich_goals_deadline_by_age(df_goals, today, current_age)

    # ベースシミュレーション（先に作る）
    df_sim, ideal_pmt, months_left, target_real_end = simulate_future_paths_v3_dynamic_ratio(
        today=today,
        current_bank=current_bank,
        current_nisa=current_nisa,
        monthly_bank_save_plan=monthly_bank_save_plan,
        monthly_nisa_save_plan=monthly_nisa_save_plan,
        annual_return=annual_return,
        inflation_rate=inflation_rate,
        current_age=current_age,
        end_age=end_age,
        target_real_today=target_real_today,
        ef=ef,
        ideal_ratios=ideal_ratios,
        df_goals=df_goals_base,
        bank_min_monthly=bank_min_monthly,
    )

    df_sim["date"] = pd.to_datetime(df_sim["date"], errors="coerce")
    df_sim = df_sim.dropna(subset=["date"])

    min_d = df_sim["date"].min().date()
    max_d = df_sim["date"].max().date()

    # ① 表示期間（先に表示）
    start_d, end_d = st.slider(
        "表示期間",
        min_value=min_d,
        max_value=max_d,
        value=(min_d, max_d),
        key="sim_range",
    )

    # ② ここに「先送り・削除 UI」を移動（希望どおり）
    df_goals_alt = None
    with st.expander("🔁 支出の先送り・削除シミュレーション（比較線をグラフに重ねます）"):
        if df_goals_base is not None and (not df_goals_base.empty) and {"目標名", "タイプ"}.issubset(df_goals_base.columns):
            outflow_candidates = sorted(
                df_goals_base[df_goals_base["タイプ"].astype(str).str.strip() == "支出"]["目標名"]
                .dropna().astype(str).unique().tolist()
            )
        else:
            outflow_candidates = []

        selected = st.multiselect("先送り/削除したい支出（Goalsのタイプ=支出）", outflow_candidates)
        delete_instead = st.checkbox("削除（先送りではなくシミュレーションから除外）", value=False)
        defer_months = st.slider("何か月先送りする？", 0, 24, 3, disabled=delete_instead)

        apply_deferral = st.checkbox("この条件を適用して比較する（ONで比較線が出ます）", value=False)

        if apply_deferral and selected:
            df_goals_alt = apply_deferral_to_goals_df(
                df_goals_base,
                selected_names=selected,
                defer_months=defer_months,
                delete_instead=delete_instead
            )
            st.caption("✅ 比較条件を適用しました")
        else:
            st.caption("（比較しない場合はベース予測のみ表示します）")

    # ③ 比較シミュレーション（必要時のみ）
    df_sim_alt = None
    if df_goals_alt is not None:
        df_sim_alt, _, _, _ = simulate_future_paths_v3_dynamic_ratio(
            today=today,
            current_bank=current_bank,
            current_nisa=current_nisa,
            monthly_bank_save_plan=monthly_bank_save_plan,
            monthly_nisa_save_plan=monthly_nisa_save_plan,
            annual_return=annual_return,
            inflation_rate=inflation_rate,
            current_age=current_age,
            end_age=end_age,
            target_real_today=target_real_today,
            ef=ef,
            ideal_ratios=ideal_ratios,
            df_goals=df_goals_alt,
            bank_min_monthly=bank_min_monthly,
        )
        df_sim_alt["date"] = pd.to_datetime(df_sim_alt["date"], errors="coerce")
        df_sim_alt = df_sim_alt.dropna(subset=["date"])

    # 表示期間で切り出し
    mask = (df_sim["date"].dt.date >= start_d) & (df_sim["date"].dt.date <= end_d)
    df_sim_view = df_sim.loc[mask].copy()

    df_sim_alt_view = None
    if df_sim_alt is not None and (not df_sim_alt.empty):
        mask2 = (df_sim_alt["date"].dt.date >= start_d) & (df_sim_alt["date"].dt.date <= end_d)
        df_sim_alt_view = df_sim_alt.loc[mask2].copy()

    st.caption(
        f"前提：投資年利 {annual_return*100:.1f}% / インフレ率 {inflation_rate*100:.1f}% / "
        f"年齢 {current_age:.0f} → {end_age:.0f} 歳（残り {months_left} か月）"
    )
    st.caption(f"実質1億（今日価値）を達成するための最終名目目標：{int(target_real_end):,} 円")
    st.caption(f"理想軌道に必要な毎月の積立（逆算）：**{int(ideal_pmt):,} 円 / 月**")

    # グラフ
    plot_future_simulation_v3(
        df_sim_view,
        chart_key="future_sim_all",
        df_compare=df_sim_alt_view,
        compare_label="🔁 先送り/削除適用後（現実）合計資産"
    )

if __name__ == "__main__":
    main()
