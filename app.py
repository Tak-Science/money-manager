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
    df_goals   = get_df("Goals", "A:F")
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
# 変動費（今月）
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

    current_month = today.strftime("%Y-%m")
    d = df_forms.copy()
    d["month"] = d["日付"].dt.strftime("%Y-%m")

    return float(d[(d["month"] == current_month) & (d["費目"].isin(EXPENSE_CATEGORIES))]["金額"].sum())


def calculate_monthly_variable_income(df_forms, today):
    if df_forms.empty:
        return 0.0
    if not {"日付", "金額", "費目"}.issubset(set(df_forms.columns)):
        return 0.0

    current_month = today.strftime("%Y-%m")
    d = df_forms.copy()
    d["month"] = d["日付"].dt.strftime("%Y-%m")

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


def get_latest_nisa_value(df_balance):
    if df_balance.empty or not {"日付", "NISA評価額"}.issubset(set(df_balance.columns)):
        return 0.0
    d = df_balance.dropna(subset=["日付"]).sort_values("日付")
    if d.empty:
        return 0.0
    v = pd.to_numeric(d.iloc[-1]["NISA評価額"], errors="coerce")
    return 0.0 if pd.isna(v) else float(v)


# ==================================================
# NISA 積立計算（モード A/B/C）
# ==================================================
def calculate_nisa_amount(df_params, today, available_cash, current_asset):
    mode = get_latest_parameter(df_params, "NISA積立モード", today)
    mode = str(mode).strip() if mode is not None else "C"

    min_nisa = to_float_safe(get_latest_parameter(df_params, "NISA最低積立額", today), default=0.0)
    max_nisa = to_float_safe(get_latest_parameter(df_params, "NISA最大積立額", today), default=0.0)

    # 互換：昔の「目標資産額」系は残しておく（Bで使う）
    target_asset = to_float_safe(get_latest_parameter(df_params, "目標資産額", today), default=100_000_000.0)

    # 終点年齢（未設定なら60、互換で老後年齢）
    end_age = get_latest_parameter(df_params, "働く最長年齢", today)
    if end_age is None:
        end_age = get_latest_parameter(df_params, "老後年齢", today)
    end_age = to_float_safe(end_age, default=60.0)

    current_age = to_float_safe(get_latest_parameter(df_params, "現在年齢", today), default=20.0)

    if max_nisa <= 0:
        max_nisa = float(available_cash)

    if mode == "A":
        nisa = min_nisa
    elif mode == "B":
        years_left = max(end_age - current_age, 1)
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
# メモ頻出分析
# ==================================================
def analyze_memo_frequency_advanced(df_forms, today, is_deficit, variable_cost, monthly_income, top_n=5):
    variable_expected = monthly_income * 0.3
    if (not is_deficit) and (variable_cost <= variable_expected):
        return []

    if df_forms.empty or not {"日付", "金額", "満足度", "メモ"}.issubset(set(df_forms.columns)):
        return []

    current_month = today.strftime("%Y-%m")
    d = df_forms.copy()
    d["month"] = d["日付"].dt.strftime("%Y-%m")

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

    current_month = today.strftime("%Y-%m")
    d = df_forms.copy()
    d["month"] = d["日付"].dt.strftime("%Y-%m")

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

    current_month = today.strftime("%Y-%m")
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
# 生活防衛費（月次シリーズ）
# ==================================================
def build_month_list(today, months_back=12):
    end = pd.Period(today.strftime("%Y-%m"), freq="M")
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
# FI（必要資産）計算
# ==================================================
def get_fi_settings(df_params, today, fi_monthly_override=None):
    if fi_monthly_override is None:
        fi_monthly = to_float_safe(get_latest_parameter(df_params, "FI月生活費（基準）", today), default=400_000.0)
    else:
        fi_monthly = float(fi_monthly_override)

    swr = to_float_safe(get_latest_parameter(df_params, "安全取り崩し率", today), default=0.03)
    swr = min(max(float(swr), 0.005), 0.10)  # 暴走防止

    fi_required = (fi_monthly * 12.0) / swr
    return {"fi_monthly": float(fi_monthly), "swr": float(swr), "fi_required": float(fi_required)}


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
# 将来シミュレーション：共通
# ==================================================
def apply_outflow_bank_first(bank, nisa, outflow):
    bank = float(bank); nisa = float(nisa); outflow = float(outflow)
    used_bank = min(bank, outflow)
    bank -= used_bank
    remain = outflow - used_bank
    used_nisa = min(nisa, remain)
    nisa -= used_nisa
    unpaid = remain - used_nisa
    return bank, nisa, used_bank, used_nisa, unpaid


def solve_required_monthly_pmt(pv, fv_target, r_month, n_months):
    pv = float(pv); fv_target = float(fv_target)
    n = int(max(n_months, 1))
    if r_month <= 0:
        return max((fv_target - pv) / n, 0.0)
    a = (1 + r_month) ** n
    denom = (a - 1) / r_month
    pmt = (fv_target - pv * a) / denom
    return max(float(pmt), 0.0)


# ==================================================
# Goals をイベント化
# ==================================================
def convert_to_jpy_stub(amount, currency, date=None):
    try:
        a = float(amount)
    except:
        return None
    c = str(currency).strip().upper() if currency is not None else "JPY"
    if c == "JPY" or c == "":
        return a
    return a  # TODO: FX


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
# 将来シミュレーション（FI目標：v4）
# ==================================================
def simulate_future_paths_v4_fi(
    *,
    today,
    current_bank,
    current_nisa,
    monthly_bank_save_plan,
    monthly_nisa_save_plan,
    annual_return,
    current_age,
    end_age,
    ef,
    ideal_ratios,
    fi_required_asset,
    df_goals=None,
    bank_min_monthly=0.0,
):
    current_bank = float(current_bank)
    current_nisa = float(current_nisa)
    monthly_bank_save_plan = float(monthly_bank_save_plan)
    monthly_nisa_save_plan = float(monthly_nisa_save_plan)
    annual_return = float(annual_return)
    bank_min_monthly = float(bank_min_monthly)

    r = (1 + annual_return) ** (1 / 12) - 1 if annual_return > -1 else 0.0

    months_left = int(max((float(end_age) - float(current_age)) * 12, 1))
    dates = pd.date_range(start=pd.to_datetime(today).normalize(), periods=months_left + 1, freq="MS")

    pv_total = current_bank + current_nisa

    # 理想：終点で「FI必要資産」に到達する毎月積立
    ideal_pmt = solve_required_monthly_pmt(
        pv=pv_total,
        fv_target=float(fi_required_asset),
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

        # 支出イベント
        items = outflows_by_month.get(month_key, [])
        outflow = float(sum(x["amount"] for x in items)) if items else 0.0

        outflow_name = ""
        if items:
            names = [x["name"] for x in items]
            outflow_name = " / ".join(names[:3]) + (" …" if len(names) > 3 else "")

        if outflow > 0:
            bank, nisa, used_bank, used_nisa, unpaid_real = apply_outflow_bank_first(bank, nisa, outflow)
            ideal_bank, ideal_nisa, _, _, unpaid_ideal = apply_outflow_bank_first(ideal_bank, ideal_nisa, outflow)
        else:
            used_bank = used_nisa = 0.0
            unpaid_real = unpaid_ideal = 0.0

        total = bank + nisa
        ideal_total = ideal_bank + ideal_nisa

        # 理想比率（防衛費ステータス連動）
        ratio = choose_ideal_nisa_ratio_by_emergency_from_params(ideal_bank, ef, ideal_ratios)
        ratio = min(max(float(ratio), 0.0), 1.0)

        # 理想積立（銀行最低積立優先）
        bank_first = min(bank_min_monthly, ideal_pmt)
        remaining = max(ideal_pmt - bank_first, 0.0)
        ideal_bank_add = bank_first + remaining * (1 - ratio)
        ideal_nisa_add = remaining * ratio

        # 目標チェック
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

            "bank": bank,
            "nisa": nisa,
            "total": total,

            "ideal_bank": ideal_bank,
            "ideal_nisa": ideal_nisa,
            "ideal_total": ideal_total,

            "ideal_pmt": ideal_pmt,
            "ideal_nisa_ratio": ratio,

            "fi_required": float(fi_required_asset),
            "fi_achieved_real": (total >= float(fi_required_asset)),
            "fi_achieved_ideal": (ideal_total >= float(fi_required_asset)),

            "outflow": outflow,
            "outflow_name": outflow_name,
            "outflow_used_bank": used_bank,
            "outflow_used_nisa": used_nisa,
            "outflow_unpaid_real": unpaid_real,
            "outflow_unpaid_ideal": unpaid_ideal,
            "outflow_ok_real": (unpaid_real <= 0),
            "outflow_ok_ideal": (unpaid_ideal <= 0),

            "goal_count": goal_count,
            "goal_name": goal_name,
            "goal_note": goal_note,
            "goal_achieved_real": achieved_real,
            "goal_achieved_ideal": achieved_ideal,

            "gap_vs_ideal": total - ideal_total,
        })

        if i == len(dates) - 1:
            break

        # 次月へ（現実）
        bank = bank + monthly_bank_save_plan
        nisa = (nisa + monthly_nisa_save_plan) * (1 + r)

        # 次月へ（理想）
        ideal_bank = ideal_bank + ideal_bank_add
        ideal_nisa = (ideal_nisa + ideal_nisa_add) * (1 + r)

    df_sim = pd.DataFrame(rows)
    return df_sim, ideal_pmt, months_left


def find_first_achieved_month(df_sim, col_bool="fi_achieved_real"):
    if df_sim is None or df_sim.empty or col_bool not in df_sim.columns:
        return None
    d = df_sim.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"]).sort_values("date")
    hit = d[d[col_bool] == True]
    if hit.empty:
        return None
    return hit.iloc[0]["date"]


# ==================================================
# グラフ描画（FI版）
# ==================================================
def plot_future_simulation_fi(df_sim, show_goals=True, max_goal_marks=12, chart_key="future_sim"):
    if df_sim is None or df_sim.empty:
        st.info("シミュレーションに必要なデータが不足しています。")
        return

    df = df_sim.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["total"],
        mode="lines",
        name="💰 予測（現実）合計資産",
        customdata=df[["ideal_total", "gap_vs_ideal", "fi_required"]].values,
        hovertemplate=(
            "日付: %{x|%Y-%m}<br>"
            "現実 合計: %{y:,.0f} 円<br>"
            "理想 合計: %{customdata[0]:,.0f} 円<br>"
            "差分（現実-理想）: %{customdata[1]:,.0f} 円<br>"
            "FI必要資産: %{customdata[2]:,.0f} 円"
            "<extra></extra>"
        )
    ))

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["ideal_total"],
        mode="lines",
        name="🎯 理想 合計（FI達成ペース）",
        line=dict(dash="dash"),
        visible="legendonly",
        hovertemplate="日付: %{x|%Y-%m}<br>理想 合計: %{y:,.0f} 円<extra></extra>"
    ))

    fi_required = float(df["fi_required"].iloc[0]) if "fi_required" in df.columns else None
    if fi_required is not None:
        fig.add_hline(
            y=fi_required,
            line_dash="dash",
            annotation_text="🏁 FIライン（必要資産）",
            annotation_position="top left",
        )

    achieved_dt = find_first_achieved_month(df, "fi_achieved_real")
    if achieved_dt is not None:
        tmp = df[df["date"] == achieved_dt]
        if not tmp.empty:
            y = float(tmp.iloc[0]["total"])
            fig.add_trace(go.Scatter(
                x=[achieved_dt],
                y=[y],
                mode="markers",
                name="✅ FI達成（月）",
                marker=dict(size=10),
                hovertemplate="FI達成: %{x|%Y-%m}<br>合計資産: %{y:,.0f} 円<extra></extra>",
            ))

    for col, nm in [
        ("bank", "🏦 現実 銀行（予測）"),
        ("nisa", "📈 現実 NISA（予測）"),
        ("ideal_bank", "🏦 理想 銀行"),
        ("ideal_nisa", "📈 理想 NISA"),
    ]:
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df[col],
                mode="lines",
                name=nm,
                line=dict(dash="dot"),
                visible="legendonly",
                hovertemplate="日付: %{x|%Y-%m}<br>%{y:,.0f} 円<extra></extra>"
            ))

    # Goals表示
    if show_goals:
        if "outflow" in df.columns:
            out_df = df[df["outflow"].fillna(0) > 0].copy()
            if not out_df.empty:
                out_df = out_df.sort_values("date").head(max_goal_marks)
                max_labels = 4
                label_idx = set(range(len(out_df))) if len(out_df) <= max_labels else set(
                    int(round(k * (len(out_df) - 1) / (max_labels - 1))) for k in range(max_labels)
                )

                for i2, r2 in enumerate(out_df.itertuples()):
                    x = pd.to_datetime(r2.date).to_pydatetime()
                    amt = float(getattr(r2, "outflow"))
                    fig.add_vline(x=x, line_dash="dot", line_width=1, opacity=0.5)
                    if i2 in label_idx:
                        fig.add_annotation(
                            x=x, y=1.0, yref="paper",
                            text=f"支出 -{int(amt):,}",
                            showarrow=False,
                            xanchor="left", yanchor="top",
                            font=dict(size=10),
                            opacity=0.8,
                        )

        if {"goal_count", "goal_achieved_real", "goal_note"}.issubset(df.columns):
            goal_df = df[df["goal_count"].fillna(0) > 0].copy()
            if not goal_df.empty:
                goal_df = goal_df.sort_values("date").head(max_goal_marks)
                goal_df["goal_status"] = goal_df.apply(
                    lambda r: "🟢" if r["goal_achieved_real"] == r["goal_count"] else "🔴",
                    axis=1
                )

                fig.add_trace(go.Scatter(
                    x=goal_df["date"],
                    y=goal_df["total"],
                    mode="markers",
                    name="🎯 目標チェック（現実）",
                    marker=dict(size=10),
                    text=goal_df["goal_status"],
                    customdata=goal_df[["goal_note", "goal_achieved_real", "goal_count"]].values,
                    hovertemplate=(
                        "日付: %{x|%Y-%m}<br>"
                        "現実 合計: %{y:,.0f} 円<br>"
                        "目標: %{customdata[0]}<br>"
                        "達成（現実）: %{customdata[1]}/%{customdata[2]}"
                        "<extra></extra>"
                    ),
                    visible="legendonly",
                ))

    fig.update_layout(
        title="🔮 将来シミュレーション（FI基準：現実 vs 理想 + Goals）",
        xaxis_title="日付",
        yaxis_title="金額（円）",
        hovermode="x unified",
        height=560,
    )

    st.plotly_chart(fig, use_container_width=True, key=chart_key)
    st.caption("※ 理想ラインは凡例クリックで表示/非表示を切り替えできます。")


# ==================================================
# 直近6か月の平均積立推定
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

    adjusted_nisa, nisa_reason = adjust_nisa_by_emergency_status(
        nisa_amount=summary["nisa_save"],
        safe_cash=safe_cash,
        ef=ef
    )
    bank_save_adjusted = summary["bank_save"] + (summary["nisa_save"] - adjusted_nisa)

    # KPI（2枚）
    k1, k2 = st.columns(2)
    k1.metric("💾 今月の積立（銀行＋NISA）", f"{int(bank_save_adjusted + adjusted_nisa):,} 円")
    k2.metric("🎉 自由に使えるお金", f"{int(summary['free_cash']):,} 円")

    st.caption(f"生活防衛費ステータスによるNISA調整：{nisa_reason}")
    if summary["available_cash"] <= 0:
        st.caption("※ 今月は収支が赤字のため、積立原資がありません（NISAは 0 円になります）")
    else:
        st.caption(f"※ 今月の積立原資（余剰資金）：{int(summary['available_cash']):,} 円")

    st.caption(
        f"月収：{int(summary['monthly_income']):,} 円 "
        f"(固定 {int(summary['base_income']):,} / 臨時 {int(summary['variable_income']):,})"
    )
    st.caption(f"固定費：{int(summary['fix_cost']):,} 円 / 変動費：{int(summary['variable_cost']):,} 円")
    st.caption(f"※ 現在資産：{int(summary['current_asset']):,} 円")

    deficit = analyze_deficit(summary["monthly_income"], summary["fix_cost"], summary["variable_cost"])
    if deficit is not None:
        st.warning(f"⚠️ 今月は {int(deficit['total_deficit']):,} 円の赤字です")
        st.markdown("**主な要因：**")
        if deficit["fix_over"] > 0:
            st.write(f"固定費が月収を {int(deficit['fix_over']):,} 円 上回っています")
        if deficit["var_over"] > 0:
            st.write(f"変動費が想定を {int(deficit['var_over']):,} 円 上回っています")
        else:
            st.write(f"変動費は想定範囲内です（想定：{int(deficit['var_expected']):,} 円 / 実際：{int(deficit['var_actual']):,} 円）")

    st.subheader("🧠 今月の振り返り（メモ分析）")
    memo = analyze_memo_frequency_advanced(
        df_forms, today,
        is_deficit=(deficit is not None),
        variable_cost=summary["variable_cost"],
        monthly_income=summary["monthly_income"]
    )
    if not memo:
        st.success("🎉 気になる頻出メモは特にありませんでした！")
    else:
        st.markdown("**控え候補として気になるもの：**")
        for word, count, amount in memo:
            st.markdown(f"- **{word}**（{count} 回 / 合計 {int(amount):,} 円）")

    st.subheader("📂 控え候補の内訳（カテゴリ別）")
    category_analysis = analyze_memo_by_category(
        df_forms, today,
        is_deficit=(deficit is not None),
        variable_cost=summary["variable_cost"],
        monthly_income=summary["monthly_income"]
    )
    if not category_analysis:
        st.info("カテゴリ別に見直す必要のある支出は特にありませんでした")
    else:
        for category, memos in category_analysis.items():
            st.markdown(f"**費目：{category}**")
            for memo_text, stats in memos.items():
                st.markdown(f"- {memo_text}：{stats['count']} 回 / 合計 {int(stats['amount']):,} 円")

    st.subheader("📈 最近増えている費目（直近月 vs 過去3か月平均）")
    trend = analyze_category_trend_3m(df_forms, today)
    if not trend:
        st.info("最近増えている費目は特にありませんでした")
    else:
        for item in trend:
            st.markdown(
                f"- **{item['category']}**：今月 {int(item['current']):,} 円 / "
                f"過去平均 {int(item['past_avg']):,} 円（**+{int(item['diff']):,} 円**）"
            )

    st.subheader("🛡️ 生活防衛費（自動算出）")
    c1, c2, c3 = st.columns(3)
    c1.metric("推定 1か月生活費（中央値）", f"{int(ef['monthly_est_median']):,} 円")
    c2.metric("推定 1か月生活費（P75）", f"{int(ef['monthly_est_p75']):,} 円")
    c3.metric(f"係数（{ef['months_factor']}か月分）", f"{ef['months_factor']} か月")
    st.caption(f"算出方法：{ef['method']}")

    st.subheader("✅ 生活防衛費の達成状況")
    if safe_cash is None:
        st.info("Balance_Log に銀行残高が無いため、達成状況を計算できませんでした。")
    else:
        need_median = float(ef["fund_median"])
        ratio = 0.0 if need_median <= 0 else min(safe_cash / need_median, 1.0)
        gap = need_median - safe_cash

        d1, d2, d3 = st.columns(3)
        d1.metric("現在の安全資金（銀行残高）", f"{int(safe_cash):,} 円")
        d2.metric("必要額（中央値ベース）", f"{int(need_median):,} 円")
        d3.metric("達成率（中央値ベース）", f"{int(ratio*100)} %")
        st.progress(ratio)

        if gap > 0:
            st.warning(f"中央値ベースで **あと {int(gap):,} 円** 不足しています。")
        else:
            st.success(f"中央値ベースは達成済みです（**+{int(abs(gap)):,} 円** 余裕）。")

    with st.expander("内訳（月次）を見る"):
        df_ef_view = pd.DataFrame({
            "固定費": ef["series_fix"],
            "変動費": ef["series_var"],
            "合計":  ef["series_total"],
        })
        df_ef_view = df_ef_view.apply(pd.to_numeric, errors="coerce").fillna(0)
        st.dataframe(df_ef_view, use_container_width=True)

    st.subheader("📊 資産推移")
    plot_asset_trend(df_balance, ef)

    # ==========================================
    # FI 設計（UIで35/40/45切替）
    # ==========================================
    st.subheader("🏁 FI設計（目標ライン）")

    # 既定値：ParametersのFI月生活費（なければ40万）
    fi_monthly_default = to_float_safe(get_latest_parameter(df_params, "FI月生活費（基準）", today), default=400_000.0)
    choices = [350_000, 400_000, 450_000]
    try:
        default_idx = choices.index(int(fi_monthly_default))
    except Exception:
        default_idx = 1  # 40万

    label = st.radio(
        "老後の月生活費（FIライン）を選択",
        options=["35万円", "40万円", "45万円"],
        index=default_idx,
        horizontal=True,
        key="fi_monthly_choice",
    )
    fi_monthly_map = {"35万円": 350_000, "40万円": 400_000, "45万円": 450_000}
    fi_monthly_selected = fi_monthly_map[label]

    fi = get_fi_settings(df_params, today, fi_monthly_override=fi_monthly_selected)

    # ==========================================
    # 将来シミュレーション（FI版）
    # ==========================================
    st.subheader("🔮 将来シミュレーション（FI基準＋Goals）")

    annual_return = to_float_safe(get_latest_parameter(df_params, "投資年利", today), default=0.05)

    end_age = get_latest_parameter(df_params, "働く最長年齢", today)
    if end_age is None:
        end_age = get_latest_parameter(df_params, "老後年齢", today)
    end_age = to_float_safe(end_age, default=60.0)

    current_age = to_float_safe(get_latest_parameter(df_params, "現在年齢", today), default=20.0)
    bank_min_monthly = to_float_safe(get_latest_parameter(df_params, "銀行最低積立額", today), default=0.0)
    ideal_ratios = get_ideal_nisa_ratios_from_params(df_params, today)

    current_bank = get_latest_bank_balance(df_balance) or 0.0
    current_nisa = get_latest_nisa_value(df_balance)

    real_total_pmt = estimate_realistic_monthly_contribution(df_balance, months=6)

    den = float(bank_save_adjusted + adjusted_nisa)
    nisa_share = (adjusted_nisa / den) if den > 0 else 0.5
    monthly_nisa_save_plan = real_total_pmt * nisa_share
    monthly_bank_save_plan = real_total_pmt * (1 - nisa_share)

    df_sim, ideal_pmt, months_left = simulate_future_paths_v4_fi(
        today=today,
        current_bank=current_bank,
        current_nisa=current_nisa,
        monthly_bank_save_plan=monthly_bank_save_plan,
        monthly_nisa_save_plan=monthly_nisa_save_plan,
        annual_return=annual_return,
        current_age=current_age,
        end_age=end_age,
        ef=ef,
        ideal_ratios=ideal_ratios,
        fi_required_asset=fi["fi_required"],
        df_goals=df_goals,
        bank_min_monthly=bank_min_monthly,
    )

    # ---------- FI達成月（カード表示） ----------
    achieved_dt_all = find_first_achieved_month(df_sim, "fi_achieved_real")
    achieved_text = achieved_dt_all.strftime("%Y-%m") if achieved_dt_all is not None else "未達"

    # FIカード（3枚）
    f1, f2, f3 = st.columns(3)
    f1.metric("FI月生活費（選択）", f"{int(fi['fi_monthly']):,} 円")
    f2.metric("FI必要資産", f"{int(fi['fi_required']):,} 円")
    f3.metric("FI達成月（現実予測）", achieved_text)

    st.caption(
        f"前提：投資年利 {annual_return*100:.1f}% / 年齢 {current_age:.0f} → {end_age:.0f} 歳（残り {months_left} か月）"
    )
    st.caption(f"現実（予測）に使う月次積立（直近平均）：{int(real_total_pmt):,} 円 / 月（銀行 {int(monthly_bank_save_plan):,} ・NISA {int(monthly_nisa_save_plan):,}）")
    st.caption(f"FIを“終点年齢までに満たす”理想積立（逆算）：**{int(ideal_pmt):,} 円 / 月**（理想比率は防衛費ステータス連動）")

    # 期間スライダー（表示だけ切る）
    chart_slot = st.empty()

    df_sim["date"] = pd.to_datetime(df_sim["date"], errors="coerce")
    df_sim = df_sim.dropna(subset=["date"])

    min_d = df_sim["date"].min().date()
    max_d = df_sim["date"].max().date()

    start_d, end_d = st.slider(
        "表示期間",
        min_value=min_d,
        max_value=max_d,
        value=(min_d, max_d),
        key="sim_range",
    )

    mask = (df_sim["date"].dt.date >= start_d) & (df_sim["date"].dt.date <= end_d)
    df_sim_view = df_sim.loc[mask].copy()

    with chart_slot.container():
        plot_future_simulation_fi(df_sim_view, chart_key="future_sim_all")

    st.markdown("### 🧾 シミュレーション詳細（表示期間内）")
    tab1, tab2 = st.tabs(["💸 支出", "🎯 目標"])

    with tab1:
        out = df_sim_view[df_sim_view["outflow"].fillna(0) > 0].copy()
        if out.empty:
            st.info("表示期間内に支出イベントはありません。")
        else:
            out["月"] = out["date"].dt.strftime("%Y-%m")
            out["支出"] = out["outflow"].astype(float)
            out["払えた？（現実）"] = out["outflow_ok_real"].map(lambda x: "✅" if x else "❌")
            out["未払い（現実）"] = out["outflow_unpaid_real"].astype(float)
            out["払えた？（理想）"] = out["outflow_ok_ideal"].map(lambda x: "✅" if x else "❌")
            out["未払い（理想）"] = out["outflow_unpaid_ideal"].astype(float)

            view = out[["月", "outflow_name", "支出", "払えた？（現実）", "未払い（現実）", "払えた？（理想）", "未払い（理想）"]]
            st.dataframe(view, use_container_width=True)

    with tab2:
        g = df_sim_view[df_sim_view["goal_count"].fillna(0) > 0].copy()
        if g.empty:
            st.info("表示期間内に目標チェックはありません。")
        else:
            g["月"] = g["date"].dt.strftime("%Y-%m")
            g["到達？（現実）"] = (g["goal_achieved_real"] == g["goal_count"]).map(lambda x: "✅" if x else "❌")
            g["到達？（理想）"] = (g["goal_achieved_ideal"] == g["goal_count"]).map(lambda x: "✅" if x else "❌")

            view = g[["月", "goal_name", "goal_note", "goal_count", "goal_achieved_real", "到達？（現実）", "goal_achieved_ideal", "到達？（理想）"]]
            st.dataframe(view, use_container_width=True)


if __name__ == "__main__":
    main()
