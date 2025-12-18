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

    df_params     = get_df("Parameters",       "A:D")
    df_fix        = get_df("Fix_Cost",         "A:G")
    df_forms      = get_df("Forms_Log",        "A:G")
    df_balance    = get_df("Balance_Log",      "A:C")
    df_goals      = get_df("Goals",            "A:F")
    df_goals_save = get_df("Goals_Save_Log",   "A:C")   # ★追加：実績入力ログ

    return df_params, df_fix, df_forms, df_balance, df_goals, df_goals_save


# ==================================================
# 前処理（型変換）
# ==================================================
def preprocess_data(df_params, df_fix, df_forms, df_balance, df_goals, df_goals_save):
    # Parameters
    if not df_params.empty and "適用開始日" in df_params.columns:
        df_params["適用開始日"] = pd.to_datetime(df_params["適用開始日"], errors="coerce")

    # Fix_Cost
    if not df_fix.empty:
        if "開始日" in df_fix.columns:
            df_fix["開始日"] = pd.to_datetime(df_fix["開始日"], errors="coerce")
        if "終了日" in df_fix.columns:
            df_fix["終了日"] = pd.to_datetime(df_fix["終了日"], errors="coerce")
        if "金額" in df_fix.columns:
            df_fix["金額"] = pd.to_numeric(df_fix["金額"], errors="coerce").fillna(0)
        if "サイクル" in df_fix.columns:
            df_fix["サイクル"] = df_fix["サイクル"].fillna("毎月")

    # Forms_Log
    if not df_forms.empty:
        if "日付" in df_forms.columns:
            df_forms["日付"] = pd.to_datetime(df_forms["日付"], errors="coerce")
        if "金額" in df_forms.columns:
            df_forms["金額"] = pd.to_numeric(df_forms["金額"], errors="coerce").fillna(0)
        if "満足度" in df_forms.columns:
            df_forms["満足度"] = pd.to_numeric(df_forms["満足度"], errors="coerce")

    # Balance_Log
    if not df_balance.empty:
        if "日付" in df_balance.columns:
            df_balance["日付"] = pd.to_datetime(df_balance["日付"], errors="coerce")
        if "銀行残高" in df_balance.columns:
            df_balance["銀行残高"] = pd.to_numeric(df_balance["銀行残高"], errors="coerce")
        if "NISA評価額" in df_balance.columns:
            df_balance["NISA評価額"] = pd.to_numeric(df_balance["NISA評価額"], errors="coerce")

    # Goals
    if not df_goals.empty:
        if "達成期限" in df_goals.columns:
            df_goals["達成期限"] = pd.to_datetime(df_goals["達成期限"], errors="coerce")
        if "金額" in df_goals.columns:
            df_goals["金額"] = pd.to_numeric(df_goals["金額"], errors="coerce")

    # Goals_Save_Log
    if not df_goals_save.empty:
        if "日付" in df_goals_save.columns:
            df_goals_save["日付"] = pd.to_datetime(df_goals_save["日付"], errors="coerce")
        if "実績Goals積立額" in df_goals_save.columns:
            df_goals_save["実績Goals積立額"] = pd.to_numeric(df_goals_save["実績Goals積立額"], errors="coerce").fillna(0)

    return df_params, df_fix, df_forms, df_balance, df_goals, df_goals_save


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


def to_int_safe(x, default=0):
    try:
        if x is None:
            return default
        return int(float(x))
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


# ==================================================
# NISA 積立計算（モード A/B/C）
# ==================================================
def calculate_nisa_amount(df_params, today, available_cash, current_asset):
    mode = get_latest_parameter(df_params, "NISA積立モード", today)
    mode = str(mode).strip() if mode is not None else "C"

    min_nisa = to_float_safe(get_latest_parameter(df_params, "NISA最低積立額", today), default=0.0)
    max_nisa = to_float_safe(get_latest_parameter(df_params, "NISA最大積立額", today), default=0.0)

    # 互換：目標資産額（古いロジック用）※FIに移行しても残してOK
    target_asset = to_float_safe(get_latest_parameter(df_params, "目標資産額", today), default=100_000_000.0)
    retire_age = to_float_safe(get_latest_parameter(df_params, "老後年齢", today), default=60.0)
    current_age = to_float_safe(get_latest_parameter(df_params, "現在年齢", today), default=20.0)

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
# 最近増えている費目（直近月 vs 過去3か月平均）
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
# 生活防衛費（月次シリーズ作成）
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
def emergency_status(safe_cash, ef):
    if safe_cash is None:
        return "unknown"
    if safe_cash < ef["fund_min"]:
        return "danger"
    if safe_cash < ef["fund_rec"]:
        return "min"
    if safe_cash < ef["fund_comfort"]:
        return "rec"
    return "safe"


def adjust_nisa_by_emergency_status(nisa_amount, safe_cash, ef):
    if safe_cash is None:
        return float(nisa_amount), "銀行残高が未取得のため調整なし"

    if safe_cash < ef["fund_min"]:
        return 0.0, "危険ゾーン：NISA停止"

    if safe_cash < ef["fund_rec"]:
        return float(int(nisa_amount * 0.5)), "最低限ゾーン：NISA 50%抑制"

    return float(nisa_amount), "推奨以上：抑制なし"


# ==================================================
# Goals：距離判定＆月次積立（必須のみ・距離係数＋状態係数）
# ==================================================
def get_distance_bucket(deadline, today, near_years=2, mid_years=5):
    if pd.isna(deadline):
        return None
    months = (pd.Period(deadline, freq="M") - pd.Period(today, freq="M")).n
    if months < 0:
        return None
    years = months / 12.0
    if years <= near_years:
        return "near"
    if years <= mid_years:
        return "mid"
    return "long"


def goals_state_factor(emg_status):
    # ユーザー指定：生活防衛費未達のみ 1.2、他はそのまま（=1.0）
    if emg_status in ["danger", "min"]:
        return 1.2
    return 1.0


def planned_goals_pmt_required(
    df_goals,
    today,
    emg_status,
    horizon_years=5,
    near_years=2,
    mid_years=5,
    coef_near=1.0,
    coef_mid=0.5,
    coef_long=0.2,
):
    """
    案A：距離係数×状態係数で、必須Goalsの月次積立（planned）を算出
    - 対象：優先度=必須 のみ
    - 対象期限：今日〜 horizon_years 年以内（それより先は planned から除外）
    """
    if df_goals is None or df_goals.empty:
        return 0.0, pd.DataFrame()

    needed = {"目標名", "金額", "達成期限", "優先度", "タイプ"}
    if not needed.issubset(set(df_goals.columns)):
        return 0.0, pd.DataFrame()

    d = df_goals.copy()
    d = d[(d["優先度"].astype(str).str.strip() == "必須")].copy()

    # 支出/目標 のうち、積立対象は「支出」（期限に向けて貯める）
    d = d[d["タイプ"].astype(str).str.strip() == "支出"].copy()

    d = d.dropna(subset=["達成期限", "金額"])
    if d.empty:
        return 0.0, pd.DataFrame()

    # horizon
    horizon_end = (pd.to_datetime(today).normalize() + pd.DateOffset(years=horizon_years))
    d = d[(d["達成期限"] >= pd.to_datetime(today).normalize()) & (d["達成期限"] <= horizon_end)].copy()
    if d.empty:
        return 0.0, pd.DataFrame()

    # 期限までの月数
    d["months_to_deadline"] = d["達成期限"].apply(
        lambda x: max((pd.Period(x, freq="M") - pd.Period(today, freq="M")).n, 1)
    )

    # 距離
    d["distance"] = d["達成期限"].apply(lambda x: get_distance_bucket(x, today, near_years, mid_years))

    # 距離係数
    dist_map = {"near": coef_near, "mid": coef_mid, "long": coef_long}
    d["distance_coef"] = d["distance"].map(dist_map).fillna(0.0)

    # 状態係数（防衛費未達のみ 1.2）
    s_coef = goals_state_factor(emg_status)
    d["state_coef"] = s_coef

    # ベース（月割り）
    d["base_pmt"] = (d["金額"].astype(float) / d["months_to_deadline"].astype(float))

    # 調整後（月次）
    d["planned_pmt"] = d["base_pmt"] * d["distance_coef"] * d["state_coef"]

    # 合計
    total = float(d["planned_pmt"].sum())
    return total, d


# ==================================================
# Goals_Save_Log：今月実績 / 累計配賦（近→中→長の順）
# ==================================================
def actual_goals_pmt_this_month(df_goals_save, today):
    if df_goals_save is None or df_goals_save.empty:
        return 0.0
    if not {"日付", "実績Goals積立額"}.issubset(set(df_goals_save.columns)):
        return 0.0
    cur = today.strftime("%Y-%m")
    d = df_goals_save.copy()
    d = d.dropna(subset=["日付"])
    d["month"] = d["日付"].dt.strftime("%Y-%m")
    return float(d[d["month"] == cur]["実績Goals積立額"].sum())


def allocate_goals_savelog_to_required_goals(
    df_goals,
    df_goals_save,
    today,
    horizon_years=5,
    near_years=2,
    mid_years=5,
):
    """
    必須支出Goalsに対して、Goals_Save_Log（実績積立）を月次で配賦し、
    goal別の「累計積立」「達成率」「残り」を作る。

    配賦順：近距離→中距離→長距離（同距離は期限が近い順）
    """
    if df_goals is None or df_goals.empty:
        return pd.DataFrame()

    needed_goals = {"目標名", "金額", "達成期限", "優先度", "タイプ"}
    if not needed_goals.issubset(set(df_goals.columns)):
        return pd.DataFrame()

    d = df_goals.copy()
    d = d[(d["優先度"].astype(str).str.strip() == "必須")].copy()
    d = d[d["タイプ"].astype(str).str.strip() == "支出"].copy()
    d = d.dropna(subset=["達成期限", "金額"])
    if d.empty:
        return pd.DataFrame()

    horizon_end = (pd.to_datetime(today).normalize() + pd.DateOffset(years=horizon_years))
    d = d[(d["達成期限"] >= pd.to_datetime(today).normalize()) & (d["達成期限"] <= horizon_end)].copy()
    if d.empty:
        return pd.DataFrame()

    d["distance"] = d["達成期限"].apply(lambda x: get_distance_bucket(x, today, near_years, mid_years))
    d["deadline_month"] = d["達成期限"].dt.to_period("M").astype(str)

    # ソートキー：距離→期限（距離は near, mid, long の順）
    dist_order = {"near": 0, "mid": 1, "long": 2}
    d["dist_order"] = d["distance"].map(dist_order).fillna(9)
    d = d.sort_values(["dist_order", "達成期限"]).reset_index(drop=True)

    # 累計入れ物
    d["allocated_total"] = 0.0

    # Save log
    if df_goals_save is None or df_goals_save.empty or not {"日付", "実績Goals積立額"}.issubset(set(df_goals_save.columns)):
        # 目標額だけ返す
        d["goal_amount"] = d["金額"].astype(float)
        d["remain"] = d["goal_amount"]
        d["achv_rate"] = 0.0
        return d

    s = df_goals_save.copy()
    s = s.dropna(subset=["日付"])
    s["month"] = s["日付"].dt.to_period("M").astype(str)
    s = s.groupby("month", as_index=False)["実績Goals積立額"].sum().sort_values("month")

    # 月次で配賦
    for _, row in s.iterrows():
        month = row["month"]
        amt = float(row["実績Goals積立額"])
        if amt <= 0:
            continue

        # 「その月時点で未達＆期限が未来」のものだけ対象
        # ※ deadline_month >= month を対象にする（今月締切も含める）
        active_idx = []
        for i in range(len(d)):
            if d.loc[i, "deadline_month"] >= month:
                active_idx.append(i)

        if not active_idx:
            continue

        for i in active_idx:
            if amt <= 0:
                break
            goal_amt = float(d.loc[i, "金額"])
            allocated = float(d.loc[i, "allocated_total"])
            remain = max(goal_amt - allocated, 0.0)
            if remain <= 0:
                continue
            add = min(remain, amt)
            d.loc[i, "allocated_total"] = allocated + add
            amt -= add

    d["goal_amount"] = d["金額"].astype(float)
    d["remain"] = (d["goal_amount"] - d["allocated_total"]).clip(lower=0.0)
    d["achv_rate"] = (d["allocated_total"] / d["goal_amount"]).clip(lower=0.0, upper=1.0)
    return d


def plot_goals_progress_pie(df_alloc):
    if df_alloc is None or df_alloc.empty:
        st.info("必須Goals（支出）の進捗を表示するデータがありません。")
        return

    # 残り内訳（残りが0のものは除外）
    d = df_alloc.copy()
    d = d[d["remain"] > 0].copy()
    if d.empty:
        st.success("🎉 必須Goals（支出）はすべて達成済みです！")
        return

    labels = d["目標名"].astype(str).tolist()
    values = d["remain"].astype(float).tolist()

    fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.45)])
    fig.update_layout(title="🟠 必須Goals（支出）残り金額の内訳（円グラフ）", height=420)
    st.plotly_chart(fig, use_container_width=True)


# ==================================================
# 今月サマリー（Goals積立を追加）
# ==================================================
def calculate_monthly_summary(df_params, df_fix, df_forms, df_balance, today, planned_goals_pmt):
    base_income = to_float_safe(get_latest_parameter(df_params, "月収", today), default=0.0)
    variable_income = calculate_monthly_variable_income(df_forms, today)
    monthly_income = base_income + variable_income

    fix_cost = calculate_monthly_fix_cost(df_fix, today)
    variable_cost = calculate_monthly_variable_cost(df_forms, today)

    # 余剰（赤字なら0）
    available_cash = max(monthly_income - fix_cost - variable_cost, 0.0)

    # Goals積立を優先控除（必須）
    goals_save = float(max(min(planned_goals_pmt, available_cash), 0.0))
    cash_after_goals = max(available_cash - goals_save, 0.0)

    current_asset = get_latest_total_asset(df_balance)

    # NISAは Goals控除後のキャッシュで計算
    nisa_amount, nisa_mode = calculate_nisa_amount(df_params, today, cash_after_goals, current_asset)
    bank_save = max(cash_after_goals - nisa_amount, 0.0)

    # 自由費：マイナスなら0で表示（ユーザー要望）
    free_cash = max(available_cash - goals_save - bank_save - nisa_amount, 0.0)

    return {
        "monthly_income": float(monthly_income),
        "base_income": float(base_income),
        "variable_income": float(variable_income),
        "fix_cost": float(fix_cost),
        "variable_cost": float(variable_cost),
        "available_cash": float(available_cash),

        "goals_save_plan": float(goals_save),
        "nisa_save": float(nisa_amount),
        "bank_save": float(bank_save),

        "free_cash": float(free_cash),
        "nisa_mode": nisa_mode,
        "current_asset": float(current_asset),
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
    df = df.dropna(subset=["日付"])
    df = df.sort_values("日付")

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


# ==================================================
# 直近6か月の平均積立推定（現実の月次積立ペース）
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
# 将来シミュレーション（FIターゲット版）
#  - 目標資産：FI必要資産（安全取り崩し率SWR）をインフレで名目カーブ化
# ==================================================
def simulate_future_fi_paths(
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
    fi_monthly_spend,
    swr,
):
    current_bank = float(current_bank)
    current_nisa = float(current_nisa)
    monthly_bank_save_plan = float(monthly_bank_save_plan)
    monthly_nisa_save_plan = float(monthly_nisa_save_plan)
    annual_return = float(annual_return)
    inflation_rate = float(inflation_rate)

    # 月利
    r = (1 + annual_return) ** (1 / 12) - 1 if annual_return > -1 else 0.0
    inf_m = (1 + inflation_rate) ** (1 / 12) - 1 if inflation_rate > -1 else 0.0

    months_left = int(max((float(end_age) - float(current_age)) * 12, 1))
    dates = pd.date_range(start=pd.to_datetime(today).normalize(), periods=months_left + 1, freq="MS")

    # FI必要資産（今日価値）
    # 年支出 = 月支出*12 → 必要資産 = 年支出 / SWR
    fi_required_today = (float(fi_monthly_spend) * 12.0) / max(float(swr), 1e-6)

    # 名目FIターゲット（インフレで増えるカーブ）
    fi_target_curve = [float(fi_required_today) * ((1 + inf_m) ** i) for i in range(len(dates))]

    bank = current_bank
    nisa = current_nisa

    rows = []
    for i, dt in enumerate(dates):
        total = bank + nisa
        target = fi_target_curve[i]
        rows.append({
            "date": dt,
            "bank": bank,
            "nisa": nisa,
            "total": total,
            "fi_target_nominal": target,
        })
        if i == len(dates) - 1:
            break

        # 次月
        bank = bank + monthly_bank_save_plan
        nisa = (nisa + monthly_nisa_save_plan) * (1 + r)

    df_sim = pd.DataFrame(rows)

    # FI達成月（最初に total >= target となる月）
    hit = df_sim[df_sim["total"] >= df_sim["fi_target_nominal"]]
    fi_month = None
    if not hit.empty:
        fi_month = pd.to_datetime(hit.iloc[0]["date"]).strftime("%Y-%m")

    return df_sim, fi_required_today, fi_month


def plot_future_fi_simulation(df_sim, chart_key="fi_sim"):
    if df_sim is None or df_sim.empty:
        st.info("FIシミュレーションに必要なデータが不足しています。")
        return

    df = df_sim.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["total"],
        mode="lines",
        name="💰 予測 合計資産（現実ペース）",
        hovertemplate="日付: %{x|%Y-%m}<br>合計: %{y:,.0f} 円<extra></extra>"
    ))

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["fi_target_nominal"],
        mode="lines",
        name="🎯 FI必要資産（名目・インフレ反映）",
        line=dict(dash="dash"),
        hovertemplate="日付: %{x|%Y-%m}<br>FI必要資産: %{y:,.0f} 円<extra></extra>"
    ))

    fig.update_layout(
        title="🔮 FIシミュレーション（合計資産 vs FI必要資産）",
        xaxis_title="日付",
        yaxis_title="金額（円）",
        hovermode="x unified",
        height=520
    )

    st.plotly_chart(fig, use_container_width=True, key=chart_key)


# ==================================================
# UI
# ==================================================
def main():
    st.title("💰 今月サマリー")

    # -------------------------
    # load & preprocess
    # -------------------------
    df_params, df_fix, df_forms, df_balance, df_goals, df_goals_save = load_data()
    df_params, df_fix, df_forms, df_balance, df_goals, df_goals_save = preprocess_data(
        df_params, df_fix, df_forms, df_balance, df_goals, df_goals_save
    )

    today = datetime.today()

    # -------------------------
    # 生活防衛費
    # -------------------------
    ef = estimate_emergency_fund(df_params, df_fix, df_forms, today)
    safe_cash = get_latest_bank_balance(df_balance)
    emg_stat = emergency_status(safe_cash, ef)

    # -------------------------
    # Goals 設計値（Parametersで変更可能）
    # -------------------------
    goals_horizon_years = to_int_safe(get_latest_parameter(df_params, "Goals積立対象（年）", today), default=5)

    # 距離定義（ユーザー合意：近<=2年 / 中<=5年 / 長>5年）
    near_years = 2
    mid_years = 5

    # 距離係数（ユーザー合意：近1.0 / 中0.5 / 長0.2）
    coef_near = 1.0
    coef_mid = 0.5
    coef_long = 0.2

    # planned goals pmt（必須だけ）
    planned_goals_pmt, df_goals_plan_detail = planned_goals_pmt_required(
        df_goals=df_goals,
        today=today,
        emg_status=emg_stat,
        horizon_years=goals_horizon_years,
        near_years=near_years,
        mid_years=mid_years,
        coef_near=coef_near,
        coef_mid=coef_mid,
        coef_long=coef_long,
    )

    # -------------------------
    # 今月サマリー（Goals積立を含む）
    # -------------------------
    summary = calculate_monthly_summary(df_params, df_fix, df_forms, df_balance, today, planned_goals_pmt)

    # NISA調整（生活防衛費ブレーキ）
    adjusted_nisa, nisa_reason = adjust_nisa_by_emergency_status(
        nisa_amount=summary["nisa_save"],
        safe_cash=safe_cash,
        ef=ef
    )

    # NISAが抑制された分は銀行側へ
    bank_save_adjusted = summary["bank_save"] + (summary["nisa_save"] - adjusted_nisa)

    # Goals積立は必須なので、NISA抑制の影響を受けない（設計方針）
    goals_save_plan = summary["goals_save_plan"]

    # 自由費は 0下限
    free_cash = summary["free_cash"]

    # -------------------------
    # Goals実績（今月）
    # -------------------------
    goals_actual_this_month = actual_goals_pmt_this_month(df_goals_save, today)
    goals_coverage = (goals_actual_this_month / goals_save_plan) if goals_save_plan > 0 else (1.0 if goals_actual_this_month > 0 else 0.0)
    goals_coverage = float(min(max(goals_coverage, 0.0), 2.0))  # 200%まで表示許容

    # -------------------------
    # FI設定（UIで35/40/45切替）
    # -------------------------
    st.subheader("🎯 FI設定")
    fi_choice = st.radio(
        "FI達成ライン（月支出）",
        options=[350000, 400000, 450000],
        index=1,  # デフォルト40万
        horizontal=True
    )
    swr = to_float_safe(get_latest_parameter(df_params, "安全取り崩し率（SWR）", today), default=0.035)  # 未設定なら3.5%

    fi_required_asset_today = (fi_choice * 12.0) / max(swr, 1e-6)

    # -------------------------
    # KPI（4 + 2：全表示）
    # 4: NISA / 銀行 / Goals / 自由費（0下限）
    # +2: FI達成月 / Goals積立達成率（今月）
    # -------------------------
    st.subheader("📌 KPI（4 + 2）")
    k1, k2, k3, k4, k5, k6 = st.columns(6)

    k1.metric("📈 NISA積立（調整後）", f"{int(adjusted_nisa):,} 円", help="生活防衛費ステータスで抑制される場合があります")
    k2.metric("🏦 銀行積立（調整後）", f"{int(bank_save_adjusted):,} 円", help="NISA抑制分は銀行へ回します")
    k3.metric("🎯 Goals積立（必須・計画）", f"{int(goals_save_plan):,} 円", help="必須Goals（支出）を期限に向けて積み立てる計画値")
    k4.metric("🎉 自由に使えるお金", f"{int(free_cash):,} 円", help="マイナスは0で表示")

    # -------------------------
    # FIシミュレーション（現実ペースでいつ達成するか）
    # -------------------------
    annual_return = to_float_safe(get_latest_parameter(df_params, "投資年利", today), default=0.05)
    inflation_rate = to_float_safe(get_latest_parameter(df_params, "インフレ率", today), default=0.02)
    end_age = to_float_safe(get_latest_parameter(df_params, "老後年齢", today), default=60.0)   # default60、Parametersで変更可
    current_age = to_float_safe(get_latest_parameter(df_params, "現在年齢", today), default=20.0)

    current_bank = get_latest_bank_balance(df_balance) or 0.0
    current_nisa = 0.0
    if not df_balance.empty and {"日付", "NISA評価額"}.issubset(df_balance.columns):
        dtmp = df_balance.dropna(subset=["日付"]).sort_values("日付")
        if not dtmp.empty:
            v = pd.to_numeric(dtmp.iloc[-1]["NISA評価額"], errors="coerce")
            current_nisa = 0.0 if pd.isna(v) else float(v)

    # 現実ペース（月次積立）は Balance_Log から推定
    real_total_pmt = estimate_realistic_monthly_contribution(df_balance, months=6)

    # 今月の「銀行:NISA比率」で按分（両方0なら50:50）
    den = float(bank_save_adjusted + adjusted_nisa)
    nisa_share = (adjusted_nisa / den) if den > 0 else 0.5

    monthly_nisa_save_plan = real_total_pmt * nisa_share
    monthly_bank_save_plan = real_total_pmt * (1 - nisa_share)

    df_fi_sim, fi_required_today, fi_month = simulate_future_fi_paths(
        today=today,
        current_bank=current_bank,
        current_nisa=current_nisa,
        monthly_bank_save_plan=monthly_bank_save_plan,
        monthly_nisa_save_plan=monthly_nisa_save_plan,
        annual_return=annual_return,
        inflation_rate=inflation_rate,
        current_age=current_age,
        end_age=end_age,
        fi_monthly_spend=float(fi_choice),
        swr=float(swr),
    )

    fi_month_text = fi_month if fi_month is not None else "未達（期間内）"
    k5.metric("🏁 FI達成月（予測）", fi_month_text, help="現実ペース（直近6か月平均）で到達する最初の月")
    k6.metric("✅ Goals積立達成率（今月）", f"{int(goals_coverage*100):,} %", help="実績Goals積立額 / 計画Goals積立額（今月）")

    # -------------------------
    # サマリー説明
    # -------------------------
    st.caption(f"生活防衛費ステータスによるNISA調整：{nisa_reason}")
    st.caption(
        f"月収：{int(summary['monthly_income']):,} 円 "
        f"(固定 {int(summary['base_income']):,} / 臨時 {int(summary['variable_income']):,})"
    )
    st.caption(f"固定費：{int(summary['fix_cost']):,} 円 / 変動費：{int(summary['variable_cost']):,} 円")
    st.caption(f"今月の余剰（赤字なら0）：{int(summary['available_cash']):,} 円")
    st.caption(f"※ 現在資産：{int(summary['current_asset']):,} 円")
    st.caption(f"FI必要資産（今日価値）：{int(fi_required_asset_today):,} 円（SWR={swr*100:.2f}% / 月{int(fi_choice):,}円）")

    # -------------------------
    # 赤字分析
    # -------------------------
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

    # -------------------------
    # メモ頻出分析
    # -------------------------
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

    # -------------------------
    # 生活防衛費
    # -------------------------
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

    with st.expander("生活防衛費：内訳（月次）を見る"):
        df_ef_view = pd.DataFrame({
            "固定費": ef["series_fix"],
            "変動費": ef["series_var"],
            "合計":  ef["series_total"],
        })
        df_ef_view = df_ef_view.apply(pd.to_numeric, errors="coerce").fillna(0)
        st.dataframe(df_ef_view, use_container_width=True)

    # -------------------------
    # 資産推移
    # -------------------------
    st.subheader("📊 資産推移")
    plot_asset_trend(df_balance, ef)

    # -------------------------
    # FIシミュレーション（期間スライダー）
    # -------------------------
    st.subheader("🔮 FIシミュレーション（合計資産 vs FI必要資産）")
    st.caption(
        f"前提：投資年利 {annual_return*100:.1f}% / インフレ率 {inflation_rate*100:.1f}% / "
        f"年齢 {current_age:.0f} → {end_age:.0f} 歳"
    )
    st.caption(
        f"現実（予測）に使う月次積立（直近平均）：{int(real_total_pmt):,} 円 / 月 "
        f"（銀行 {int(monthly_bank_save_plan):,} ・NISA {int(monthly_nisa_save_plan):,}）"
    )

    df_fi_sim["date"] = pd.to_datetime(df_fi_sim["date"], errors="coerce")
    df_fi_sim = df_fi_sim.dropna(subset=["date"])
    min_d = df_fi_sim["date"].min().date()
    max_d = df_fi_sim["date"].max().date()

    start_d, end_d = st.slider(
        "表示期間",
        min_value=min_d,
        max_value=max_d,
        value=(min_d, max_d),
        key="fi_sim_range",
    )
    mask = (df_fi_sim["date"].dt.date >= start_d) & (df_fi_sim["date"].dt.date <= end_d)
    df_fi_view = df_fi_sim.loc[mask].copy()
    plot_future_fi_simulation(df_fi_view, chart_key="fi_sim_chart")

    # -------------------------
    # Goals：計画詳細＆実績進捗（トグル）
    # -------------------------
    st.subheader("🎯 Goals（必須支出）積立の詳細")

    with st.expander("① 今月のGoals積立（計画）内訳を見る（距離×係数）"):
        if df_goals_plan_detail is None or df_goals_plan_detail.empty:
            st.info("今月の必須Goals（支出）計画がありません。")
        else:
            view = df_goals_plan_detail[[
                "目標名", "金額", "達成期限", "distance", "months_to_deadline", "base_pmt", "distance_coef", "state_coef", "planned_pmt"
            ]].copy()
            # 表示整形
            view["達成期限"] = pd.to_datetime(view["達成期限"]).dt.strftime("%Y-%m-%d")
            for col in ["金額", "base_pmt", "planned_pmt"]:
                view[col] = view[col].astype(float)
            st.dataframe(view, use_container_width=True)

            st.caption(
                f"距離定義：近<=2年 / 中<=5年 / 長>5年、距離係数：近1.0・中0.5・長0.2、"
                f"状態係数：生活防衛費未達のみ1.2（現在={emg_stat}）"
            )
            st.caption(f"積立対象期限：今日〜{goals_horizon_years}年以内（Goals積立対象（年）で変更可能）")

    with st.expander("② Goals積立の実績進捗（必須）を見る（円グラフ＋達成率テーブル）"):
        df_alloc = allocate_goals_savelog_to_required_goals(
            df_goals=df_goals,
            df_goals_save=df_goals_save,
            today=today,
            horizon_years=goals_horizon_years,
            near_years=near_years,
            mid_years=mid_years,
        )

        plot_goals_progress_pie(df_alloc)

        if df_alloc is not None and not df_alloc.empty:
            show = df_alloc[[
                "目標名", "金額", "allocated_total", "achv_rate", "remain", "達成期限", "distance"
            ]].copy()
            show["達成期限"] = pd.to_datetime(show["達成期限"]).dt.strftime("%Y-%m-%d")
            show["achv_rate"] = (show["achv_rate"] * 100.0).round(1)
            show = show.rename(columns={
                "金額": "目標額",
                "allocated_total": "累計積立",
                "achv_rate": "達成率(%)",
                "remain": "残り",
                "distance": "距離",
            })
            st.dataframe(show, use_container_width=True)

            st.caption("配賦順：近距離→中距離→長距離（同距離は期限が近い順）／月1回入力（Goals_Save_Log）で進捗が積み上がります。")

    # -------------------------
    # Goals_Save_Log 入力ガイド
    # -------------------------
    with st.expander("③ 今月のGoals積立 実績入力（Goals_Save_Log）のガイド"):
        st.markdown(
            """
- **Goals_Save_Log** に **月1回**、「日付」と「実績Goals積立額」を入力してください  
- 例：  
  - 日付：2025-12-01  
  - 実績Goals積立額：30000  
- その月の入力が複数ある場合は **合計**します
"""
        )


if __name__ == "__main__":
    main()

