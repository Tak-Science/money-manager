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
# 仕様（確定）
# ==================================================
# Goals 距離分類
NEAR_YEARS = 2
MID_YEARS = 5

# 距離係数（確定）
DIST_COEF = {
    "near": 1.0,
    "mid": 0.5,
    "long": 0.2,
}

# 状態係数（確定：生活防衛費未達のみ 1.2）
STATE_COEF_EMERGENCY_NOT_MET = 1.2

# KPI / 表示向け
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

    df_params  = get_df("Parameters",      "A:D")
    df_fix     = get_df("Fix_Cost",        "A:G")
    df_forms   = get_df("Forms_Log",       "A:G")
    df_balance = get_df("Balance_Log",     "A:C")
    df_goals   = get_df("Goals",           "A:F")
    df_goals_log = get_df("Goals_Save_Log","A:D")  # ★追加：月1回の実績入力

    return df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log

# ==================================================
# 前処理（型整形）
# ==================================================
def preprocess_data(df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log):
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
    if df_goals is not None and (not df_goals.empty):
        if "達成期限" in df_goals.columns:
            df_goals["達成期限"] = pd.to_datetime(df_goals["達成期限"], errors="coerce")
        if "金額" in df_goals.columns:
            df_goals["金額"] = pd.to_numeric(df_goals["金額"], errors="coerce")

    # Goals_Save_Log（実績）
    if df_goals_log is not None and (not df_goals_log.empty):
        # 想定列：月 / 積立額 / メモ / 任意
        # "月" が YYYY-MM or 日付でもOKにする
        if "月" in df_goals_log.columns:
            # 月が "2025-01" のような場合は 1日付与
            def parse_month(x):
                s = str(x).strip()
                if re.match(r"^\d{4}-\d{2}$", s):
                    s = s + "-01"
                return pd.to_datetime(s, errors="coerce")
            df_goals_log["月_dt"] = df_goals_log["月"].apply(parse_month)
        elif "日付" in df_goals_log.columns:
            df_goals_log["月_dt"] = pd.to_datetime(df_goals_log["日付"], errors="coerce")
        else:
            df_goals_log["月_dt"] = pd.NaT

        if "積立額" in df_goals_log.columns:
            df_goals_log["積立額"] = pd.to_numeric(df_goals_log["積立額"], errors="coerce").fillna(0)
        else:
            df_goals_log["積立額"] = 0.0

    return df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log

# ==================================================
# Parameters 取得（履歴対応）
# ==================================================
def get_latest_parameter(df, item, target_date):
    if df is None or df.empty:
        return None
    if not {"項目", "値", "適用開始日"}.issubset(set(df.columns)):
        return None

    d = df.copy()
    d = d[d["項目"] == item].dropna(subset=["適用開始日"])
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
    if df_fix is None or df_fix.empty:
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
def calculate_monthly_variable_cost(df_forms, today):
    if df_forms is None or df_forms.empty:
        return 0.0
    if not {"日付", "金額", "費目"}.issubset(set(df_forms.columns)):
        return 0.0

    current_month = today.strftime("%Y-%m")
    d = df_forms.copy()
    d["month"] = d["日付"].dt.strftime("%Y-%m")
    return float(d[(d["month"] == current_month) & (d["費目"].isin(EXPENSE_CATEGORIES))]["金額"].sum())

def calculate_monthly_variable_income(df_forms, today):
    if df_forms is None or df_forms.empty:
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
    if df_balance is None or df_balance.empty:
        return None
    if not {"日付", "銀行残高"}.issubset(set(df_balance.columns)):
        return None

    d = df_balance.copy().dropna(subset=["日付", "銀行残高"]).sort_values("日付")
    if d.empty:
        return None
    return float(d.iloc[-1]["銀行残高"])

def get_latest_nisa_balance(df_balance):
    if df_balance is None or df_balance.empty:
        return 0.0
    if not {"日付", "NISA評価額"}.issubset(set(df_balance.columns)):
        return 0.0
    d = df_balance.copy().dropna(subset=["日付"]).sort_values("日付")
    if d.empty:
        return 0.0
    v = pd.to_numeric(d.iloc[-1]["NISA評価額"], errors="coerce")
    return 0.0 if pd.isna(v) else float(v)

def get_latest_total_asset(df_balance):
    bank = get_latest_bank_balance(df_balance)
    nisa = get_latest_nisa_balance(df_balance)
    return float((bank or 0.0) + (nisa or 0.0))

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

    if df_forms is None or df_forms.empty or not {"日付", "金額", "満足度", "メモ"}.issubset(set(df_forms.columns)):
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

    if df_forms is None or df_forms.empty or not {"日付", "金額", "満足度", "メモ", "費目"}.issubset(set(df_forms.columns)):
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
    if df_forms is None or df_forms.empty or not {"日付", "金額", "費目"}.issubset(set(df_forms.columns)):
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
    if df_forms is None or df_forms.empty or not {"日付", "金額", "費目"}.issubset(set(df_forms.columns)):
        return pd.Series(0.0, index=months, dtype=float)

    d = df_forms.copy()
    d = d[d["費目"].isin(EXPENSE_CATEGORIES)]
    d["month"] = d["日付"].dt.to_period("M").astype(str)

    s = d.groupby("month")["金額"].sum().reindex(months, fill_value=0.0).astype(float)
    return s

def monthly_fix_cost_series(df_fix, months):
    if df_fix is None or df_fix.empty or not {"開始日", "終了日", "金額", "サイクル"}.issubset(set(df_fix.columns)):
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
        "fund_min": float(fund_min),
        "fund_rec": float(fund_rec),
        "fund_comfort": float(fund_comfort),
        "series_fix": fix_s,
        "series_var": var_s,
        "series_total": total_s,
    }

# ==================================================
# Goals：通貨変換（現状はJPYのみ）
# ==================================================
def convert_to_jpy_stub(amount, currency, date=None):
    try:
        a = float(amount)
    except Exception:
        return None

    c = str(currency).strip().upper() if currency is not None else "JPY"
    if c in ("JPY", ""):
        return a
    # TODO: 将来FX対応
    return a

# ==================================================
# Goals：距離分類
# ==================================================
def months_until(today, deadline):
    """deadline までの残り月数（最低1）。月単位（Period）で算出。"""
    if pd.isna(deadline):
        return 1
    t = pd.Period(pd.to_datetime(today), freq="M")
    d = pd.Period(pd.to_datetime(deadline), freq="M")
    diff = (d - t).n
    return int(max(diff, 1))

def classify_distance_bucket(today, deadline):
    m = months_until(today, deadline)
    years = m / 12.0
    if years <= NEAR_YEARS:
        return "near"
    if years <= MID_YEARS:
        return "mid"
    return "long"

# ==================================================
# Goals：イベント化（支出/目標）
# ==================================================
def prepare_goals_events(df_goals, today, only_required=True, horizon_years=5):
    """
    Goals シートから「月次イベント」を返す。
    - 支出: outflows_by_month[YYYY-MM] = list of {"name","amount","priority","deadline","bucket"}
    - 目標: targets_by_month[YYYY-MM]  = list of {"name","amount","priority","deadline","bucket"}
    """
    if df_goals is None or df_goals.empty:
        return {}, {}, pd.DataFrame()

    required_cols = ["目標名", "金額", "通貨", "達成期限", "優先度", "タイプ"]
    for col in required_cols:
        if col not in df_goals.columns:
            return {}, {}, pd.DataFrame()

    df = df_goals.copy()
    df["達成期限"] = pd.to_datetime(df["達成期限"], errors="coerce")
    df["金額"] = pd.to_numeric(df["金額"], errors="coerce")
    df = df.dropna(subset=["達成期限", "金額"])
    if df.empty:
        return {}, {}, pd.DataFrame()

    # horizon: 今日〜N年先までを対象（デフォルト 5年）
    horizon_dt = pd.to_datetime(today).normalize() + pd.DateOffset(years=int(max(horizon_years, 1)))
    df = df[(df["達成期限"] >= pd.to_datetime(today).normalize()) & (df["達成期限"] <= horizon_dt)]

    if only_required and "優先度" in df.columns:
        df = df[df["優先度"].astype(str).str.contains("必須", na=False)]

    if df.empty:
        return {}, {}, pd.DataFrame()

    df["month"] = df["達成期限"].dt.to_period("M").astype(str)
    df["bucket"] = df["達成期限"].apply(lambda x: classify_distance_bucket(today, x))

    outflows_by_month = {}
    targets_by_month = {}

    rows_norm = []
    for _, r in df.iterrows():
        name = str(r["目標名"])
        typ = str(r["タイプ"]).strip()
        prio = str(r["優先度"]).strip()
        m = str(r["month"])
        bucket = str(r["bucket"])

        amt = convert_to_jpy_stub(r["金額"], r["通貨"], r["達成期限"])
        if amt is None:
            continue

        item = {
            "name": name,
            "amount": float(amt),
            "priority": prio,
            "deadline": r["達成期限"],
            "bucket": bucket,
        }

        rows_norm.append(item | {"type": typ, "month": m})

        if typ == "支出":
            outflows_by_month.setdefault(m, []).append(item)
        else:
            targets_by_month.setdefault(m, []).append(item)

    df_norm = pd.DataFrame(rows_norm)
    return outflows_by_month, targets_by_month, df_norm

# ==================================================
# Goals：実績（Goals_Save_Log）集計
# ==================================================
def goals_log_monthly_actual(df_goals_log, today):
    """当月の実績（Goals_Save_Log）"""
    if df_goals_log is None or df_goals_log.empty:
        return 0.0

    if "月_dt" not in df_goals_log.columns:
        return 0.0

    cur = pd.to_datetime(today).to_period("M")
    d = df_goals_log.copy()
    d = d.dropna(subset=["月_dt"])
    d["month"] = d["月_dt"].dt.to_period("M")
    d = d[d["month"] == cur]
    if d.empty:
        return 0.0
    return float(d["積立額"].sum())

def goals_log_cumulative(df_goals_log):
    """累積実績（Goals_Save_Log）"""
    if df_goals_log is None or df_goals_log.empty:
        return 0.0
    if "積立額" not in df_goals_log.columns:
        return 0.0
    return float(pd.to_numeric(df_goals_log["積立額"], errors="coerce").fillna(0).sum())

# ==================================================
# Goals：累積実績を「近→中→長」順に割当して、各Goal達成率を出す
# ==================================================
def allocate_goals_progress(df_goals_norm, total_saved):
    """
    df_goals_norm: normalize済み（type, month, deadline, bucket, amount, name, priority）
    total_saved: Goals_Save_Log の累積
    """
    if df_goals_norm is None or df_goals_norm.empty:
        return pd.DataFrame()

    d = df_goals_norm.copy()
    # 「支出」は貯める対象ではなく支払いイベントなので、進捗は「目標」側だけで見る
    d = d[d["type"] != "支出"].copy()
    if d.empty:
        return pd.DataFrame()

    # 近→中→長、次に期限が近い順
    bucket_order = {"near": 0, "mid": 1, "long": 2}
    d["bucket_order"] = d["bucket"].map(lambda x: bucket_order.get(str(x), 9))
    d = d.sort_values(["bucket_order", "deadline", "name"])

    remain = float(max(total_saved, 0.0))
    achieved = []
    for _, r in d.iterrows():
        goal_amt = float(r["amount"])
        use = min(remain, goal_amt)
        remain -= use
        achieved.append(use)

    d["achieved_amount"] = achieved
    d["remaining_amount"] = (d["amount"] - d["achieved_amount"]).clip(lower=0.0)
    d["achieved_rate"] = d.apply(lambda r: 0.0 if r["amount"] <= 0 else float(r["achieved_amount"] / r["amount"]), axis=1)

    return d

# ==================================================
# Goals：今月の「必要積立（案A）」を算出
# ==================================================
def compute_goals_monthly_plan(df_goals_progress, today, emergency_not_met):
    """
    近/中/遠の距離係数 + 状態係数（防衛費未達のみ1.2）で、
    今月のGoals積立を計算する（必須のみが入っている前提）。

    設計：
    - まず各Goalの「残額/残月数」を最低ラインとする
    - 距離係数は “上乗せの効き方” にだけ使い、最低ラインは割らない
      plan = min_pmt * (1 + (state-1)*distance_coeff)
    """
    if df_goals_progress is None or df_goals_progress.empty:
        return 0.0, pd.DataFrame()

    state = STATE_COEF_EMERGENCY_NOT_MET if emergency_not_met else 1.0

    d = df_goals_progress.copy()
    d["months_left"] = d["deadline"].apply(lambda x: months_until(today, x))
    d["min_pmt"] = d.apply(lambda r: 0.0 if r["remaining_amount"] <= 0 else float(r["remaining_amount"] / max(int(r["months_left"]), 1)), axis=1)
    d["dist_coef"] = d["bucket"].apply(lambda b: float(DIST_COEF.get(str(b), 1.0)))

    d["plan_pmt"] = d.apply(
        lambda r: 0.0 if r["remaining_amount"] <= 0 else float(r["min_pmt"] * (1.0 + (state - 1.0) * r["dist_coef"])),
        axis=1
    )

    total = float(d["plan_pmt"].sum())
    return total, d

# ==================================================
# 今月サマリー（収支）
# ==================================================
def calculate_monthly_summary(df_params, df_fix, df_forms, df_balance, today):
    base_income = to_float_safe(get_latest_parameter(df_params, "月収", today), default=0.0)
    variable_income = calculate_monthly_variable_income(df_forms, today)
    monthly_income = base_income + variable_income

    fix_cost = calculate_monthly_fix_cost(df_fix, today)
    variable_cost = calculate_monthly_variable_cost(df_forms, today)

    available_cash = max(monthly_income - fix_cost - variable_cost, 0.0)

    current_total_asset = get_latest_total_asset(df_balance)
    current_bank = get_latest_bank_balance(df_balance) or 0.0
    current_nisa = get_latest_nisa_balance(df_balance) or 0.0

    return {
        "monthly_income": float(monthly_income),
        "base_income": float(base_income),
        "variable_income": float(variable_income),
        "fix_cost": float(fix_cost),
        "variable_cost": float(variable_cost),
        "available_cash": float(available_cash),
        "current_total_asset": float(current_total_asset),
        "current_bank": float(current_bank),
        "current_nisa": float(current_nisa),
    }

# ==================================================
# NISA係数（A/B/C廃止：ここだけで決まる）
# ==================================================
def compute_nisa_coefficient(
    *,
    available_cash_after_goals,
    emergency_not_met,
    emergency_is_danger,
    goals_shortfall,
):
    """
    2段階（オン/オフ）を基本に：
    - 赤字 or Goals積立を満たせないなら 0
    - 生活防衛費が危険ゾーンなら 0
    - 防衛費未達なら 0（オン/オフの2段階）
    - それ以外 1
    """
    if available_cash_after_goals <= 0:
        return 0.0, "赤字またはGoals後に余剰なし → NISA 0"
    if goals_shortfall:
        return 0.0, "Goals積立が不足 → NISA 0"
    if emergency_is_danger:
        return 0.0, "生活防衛費 危険ゾーン → NISA 0"
    if emergency_not_met:
        return 0.0, "生活防衛費 未達 → NISA 0（2段階）"
    return 1.0, "条件OK → NISA 100%"

# ==================================================
# 資産推移グラフ（現状）
# ==================================================
def plot_asset_trend(df_balance, ef):
    if df_balance is None or df_balance.empty:
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

    fig.add_hline(y=float(ef["fund_rec"]), line_dash="dash", annotation_text="🛡️ 生活防衛費（推奨）", annotation_position="top left")
    fig.add_hline(y=float(ef["fund_min"]), line_dash="dot", annotation_text="⚠️ 生活防衛費（最低）", annotation_position="bottom left")

    fig.update_layout(
        title="📊 資産推移（銀行・NISA・合計）",
        xaxis_title="日付",
        yaxis_title="金額（円）",
        hovermode="x unified",
        height=480
    )
    st.plotly_chart(fig, use_container_width=True)

# ==================================================
# FI / SWR
# ==================================================
def compute_fi_required_asset(monthly_spend, swr_assumption):
    annual = float(monthly_spend) * 12.0
    swr = float(swr_assumption)
    if swr <= 0:
        return float("inf")
    return float(annual / swr)

def compute_current_swr(monthly_spend, investable_asset):
    annual = float(monthly_spend) * 12.0
    a = float(investable_asset)
    if a <= 0:
        return None
    return float(annual / a)

# ==================================================
# シミュレーション補助
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

def apply_outflow_three_pockets(goals_fund, emergency_cash, nisa, outflow):
    """
    支出を Goals_fund → emergency_cash → NISA の順で支払う
    戻り値：goals_fund, emergency_cash, nisa, used_goals, used_emergency, used_nisa, unpaid
    """
    goals_fund = float(goals_fund)
    emergency_cash = float(emergency_cash)
    nisa = float(nisa)
    outflow = float(outflow)

    used_goals = min(goals_fund, outflow)
    goals_fund -= used_goals
    remain = outflow - used_goals

    used_em = min(emergency_cash, remain)
    emergency_cash -= used_em
    remain2 = remain - used_em

    used_nisa = min(nisa, remain2)
    nisa -= used_nisa

    unpaid = remain2 - used_nisa
    return goals_fund, emergency_cash, nisa, used_goals, used_em, used_nisa, unpaid

def estimate_realistic_monthly_contribution(df_balance, months=6):
    """合計資産（銀行+NISA）の月次増分平均（プラスのみ）"""
    if df_balance is None or df_balance.empty:
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
# FIシミュレーション（現実/理想）
# ==================================================
def simulate_fi_paths(
    *,
    today,
    current_age,
    end_age,
    annual_return,
    # 現在の3ポケット
    current_emergency_cash,
    current_goals_fund,
    current_nisa,
    # 現実：月次積立（3つ）
    monthly_emergency_save_real,
    monthly_goals_save_real,
    monthly_nisa_save_real,
    # 理想：FI達成へ必要な月次積立（investableのみ）
    fi_target_asset,
    # Goals outflows
    outflows_by_month,
    # 生活防衛費の推奨
    ef_rec,
):
    # 月利
    r = (1 + float(annual_return)) ** (1 / 12) - 1 if float(annual_return) > -1 else 0.0

    months_left = int(max((float(end_age) - float(current_age)) * 12, 1))
    dates = pd.date_range(start=pd.to_datetime(today).normalize(), periods=months_left + 1, freq="MS")

    # 理想：investable（emergency + nisa）で FI target 到達のためのPMT逆算
    pv_investable = float(current_emergency_cash) + float(current_nisa)
    ideal_pmt_investable = solve_required_monthly_pmt(
        pv=pv_investable,
        fv_target=float(fi_target_asset),
        r_month=r,
        n_months=months_left
    )

    # 理想の配分：基本は NISA 80% へ（ただし安全資金も意識）
    # ※ここは将来 Parameters で可変にしてもOK
    ideal_nisa_ratio = 0.8

    # 初期
    em = float(current_emergency_cash)
    gf = float(current_goals_fund)
    ni = float(current_nisa)

    em_i = float(current_emergency_cash)
    gf_i = float(current_goals_fund)
    ni_i = float(current_nisa)

    rows = []
    for i, dt in enumerate(dates):
        month_key = pd.Period(dt, freq="M").strftime("%Y-%m")

        # --- 今月の支出イベント（必須支出）
        items = outflows_by_month.get(month_key, [])
        outflow = float(sum(x["amount"] for x in items)) if items else 0.0
        outflow_name = ""
        if items:
            names = [x["name"] for x in items]
            outflow_name = " / ".join(names[:3]) + (" …" if len(names) > 3 else "")

        # 支出を適用（現実）
        unpaid_real = 0.0
        if outflow > 0:
            gf, em, ni, used_g, used_e, used_n, unpaid_real = apply_outflow_three_pockets(gf, em, ni, outflow)

        # 支出を適用（理想）
        unpaid_ideal = 0.0
        if outflow > 0:
            gf_i, em_i, ni_i, used_g2, used_e2, used_n2, unpaid_ideal = apply_outflow_three_pockets(gf_i, em_i, ni_i, outflow)

        # 資産
        total_real = gf + em + ni
        investable_real = em + ni

        total_ideal = gf_i + em_i + ni_i
        investable_ideal = em_i + ni_i

        # FI達成判定（安全条件：推奨防衛費を満たしつつ investable が到達）
        fi_ok_real = (investable_real >= float(fi_target_asset)) and (em >= float(ef_rec))
        fi_ok_ideal = (investable_ideal >= float(fi_target_asset)) and (em_i >= float(ef_rec))

        rows.append({
            "date": dt,
            "total_real": total_real,
            "investable_real": investable_real,
            "emergency_real": em,
            "goals_fund_real": gf,
            "nisa_real": ni,

            "total_ideal": total_ideal,
            "investable_ideal": investable_ideal,
            "emergency_ideal": em_i,
            "goals_fund_ideal": gf_i,
            "nisa_ideal": ni_i,

            "outflow": outflow,
            "outflow_name": outflow_name,
            "unpaid_real": unpaid_real,
            "unpaid_ideal": unpaid_ideal,

            "fi_ok_real": fi_ok_real,
            "fi_ok_ideal": fi_ok_ideal,

            "ideal_pmt_investable": ideal_pmt_investable,
        })

        if i == len(dates) - 1:
            break

        # --- 次月へ（現実）
        em = em + float(monthly_emergency_save_real)
        gf = gf + float(monthly_goals_save_real)
        ni = (ni + float(monthly_nisa_save_real)) * (1 + r)

        # --- 次月へ（理想）
        # Goalsは「現実と同じだけは積む」前提（必須支払いの安定性優先）
        gf_i = gf_i + float(monthly_goals_save_real)

        # investable の理想PMT
        add_nisa = float(ideal_pmt_investable) * float(ideal_nisa_ratio)
        add_em = float(ideal_pmt_investable) * (1.0 - float(ideal_nisa_ratio))

        em_i = em_i + add_em
        ni_i = (ni_i + add_nisa) * (1 + r)

    df_sim = pd.DataFrame(rows)
    return df_sim

def plot_fi_simulation(df_sim, fi_target_asset, show_ideal, chart_key="fi_sim"):
    if df_sim is None or df_sim.empty:
        st.info("シミュレーションに必要なデータが不足しています。")
        return

    df = df_sim.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")

    fig = go.Figure()

    # 現実：investable
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["investable_real"],
        mode="lines",
        name="💰 現実（予測）投資可能資産（銀行+NISA）",
        hovertemplate="日付: %{x|%Y-%m}<br>投資可能資産: %{y:,.0f} 円<extra></extra>"
    ))

    # 現実：合計（参考）
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["total_real"],
        mode="lines",
        name="📦 現実（予測）合計（Goals含む）",
        line=dict(dash="dot"),
        visible="legendonly",
        hovertemplate="日付: %{x|%Y-%m}<br>合計: %{y:,.0f} 円<extra></extra>"
    ))

    # FI必要資産ライン
    fig.add_hline(
        y=float(fi_target_asset),
        line_dash="dash",
        annotation_text="🏁 FI必要資産",
        annotation_position="top left",
    )

    # 理想ライン（トグル表示）
    if show_ideal and "investable_ideal" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["investable_ideal"],
            mode="lines",
            name="🎯 理想（FI到達ペース）投資可能資産",
            line=dict(dash="dash"),
            hovertemplate="日付: %{x|%Y-%m}<br>理想 投資可能: %{y:,.0f} 円<extra></extra>"
        ))

    # FI達成点（最初の1回だけ小さくマーク）
    ok = df[df["fi_ok_real"] == True].copy()
    if not ok.empty:
        first = ok.iloc[0]
        fig.add_trace(go.Scatter(
            x=[first["date"]], y=[first["investable_real"]],
            mode="markers",
            name="✅ FI達成（現実）",
            marker=dict(size=9),
            hovertemplate="FI達成: %{x|%Y-%m}<br>%{y:,.0f} 円<extra></extra>"
        ))

    fig.update_layout(
        title="🔮 FIシミュレーション（支出イベント反映 / FI必要資産ベース）",
        xaxis_title="日付",
        yaxis_title="金額（円）",
        hovermode="x unified",
        height=560,
    )

    st.plotly_chart(fig, use_container_width=True, key=chart_key)

# ==================================================
# 円グラフ（Goals達成）
# ==================================================
def plot_goal_pie(title, achieved, total, key=None):
    achieved = float(max(achieved, 0.0))
    total = float(max(total, 0.0))
    remain = float(max(total - achieved, 0.0))

    fig = go.Figure(data=[go.Pie(
        labels=["達成", "未達"],
        values=[achieved, remain],
        hole=0.55,
        textinfo="percent"
    )])
    fig.update_layout(
        title=title,
        height=300,
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=True
    )
    st.plotly_chart(fig, use_container_width=True, key=key)

# ==================================================
# UI（メイン）
# ==================================================
def main():
    st.title("💰 今月サマリー")

    # --- データ
    df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log = load_data()
    df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log = preprocess_data(
        df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log
    )
    today = datetime.today()

    # --- Parameters（追加分）
    # Goals積立の対象年数（デフォルト5）
    goals_horizon_years = to_int_safe(get_latest_parameter(df_params, "Goals積立対象年数", today), default=5)
    # SWR（デフォルト3.5%）
    swr_assumption = to_float_safe(get_latest_parameter(df_params, "SWR", today), default=0.035)
    # 年齢（retire=「何歳まで働くか」）
    end_age = to_float_safe(get_latest_parameter(df_params, "老後年齢", today), default=60.0)
    current_age = to_float_safe(get_latest_parameter(df_params, "現在年齢", today), default=20.0)
    annual_return = to_float_safe(get_latest_parameter(df_params, "投資年利", today), default=0.05)

    # --- 今月収支
    summary = calculate_monthly_summary(df_params, df_fix, df_forms, df_balance, today)

    # --- 生活防衛費
    ef = estimate_emergency_fund(df_params, df_fix, df_forms, today)
    bank_balance = float(summary["current_bank"])
    nisa_balance = float(summary["current_nisa"])

    emergency_is_danger = bank_balance < float(ef["fund_min"])
    emergency_not_met = bank_balance < float(ef["fund_rec"])

    # --- Goals（必須のみ・対象年数内）
    outflows_by_month, targets_by_month, df_goals_norm = prepare_goals_events(
        df_goals, today,
        only_required=True,
        horizon_years=goals_horizon_years
    )

    # --- Goals 実績（当月 / 累積）
    actual_goals_pmt_month = goals_log_monthly_actual(df_goals_log, today)
    actual_goals_cum = goals_log_cumulative(df_goals_log)

    # --- Goals 進捗（累積を 近→中→長に割当）
    df_goals_progress = allocate_goals_progress(df_goals_norm, actual_goals_cum)

    # --- 今月Goals積立（案A）
    goals_save_plan, df_goals_plan_detail = compute_goals_monthly_plan(
        df_goals_progress, today,
        emergency_not_met=emergency_not_met
    )

    # --- 今月の余剰
    available_cash = float(summary["available_cash"])
    available_after_goals = max(available_cash - float(goals_save_plan), 0.0)
    goals_shortfall = available_cash < float(goals_save_plan)

    # --- NISA係数（A/B/C完全廃止）
    nisa_coef, nisa_reason = compute_nisa_coefficient(
        available_cash_after_goals=available_after_goals,
        emergency_not_met=emergency_not_met,
        emergency_is_danger=emergency_is_danger,
        goals_shortfall=goals_shortfall,
    )

    # --- 銀行積立 / NISA積立（Goalsを最優先に差し引いた後）
    nisa_save = float(available_after_goals * nisa_coef)
    bank_save = float(max(available_after_goals - nisa_save, 0.0))

    # --- 自由に使えるお金（マイナスなら0表示）
    free_cash = float(max(available_cash - goals_save_plan - bank_save - nisa_save, 0.0))

    # ==================================================
    # KPI（4 + 2）
    # ==================================================
    st.subheader("📌 KPI（今月）")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("🏦 銀行積立（防衛費向け）", f"{int(bank_save):,} 円")
    k2.metric("📈 NISA積立（係数適用）", f"{int(nisa_save):,} 円")
    k3.metric("🎯 Goals積立（第3積立・必須）", f"{int(goals_save_plan):,} 円")
    k4.metric("🎉 自由に使えるお金", f"{int(free_cash):,} 円")

    s1, s2 = st.columns(2)

    # 生活防衛費達成率（推奨ライン）
    ef_ratio = 0.0 if float(ef["fund_rec"]) <= 0 else min(bank_balance / float(ef["fund_rec"]), 1.0)
    s1.metric("🛡️ 生活防衛費達成率（推奨）", f"{int(ef_ratio*100)} %")
    s1.progress(ef_ratio)

    # Goals積立達成率（当月：実績 / 計画）
    if goals_save_plan <= 0:
        goals_month_ratio = None
        s2.metric("🎯 Goals積立達成率（当月）", "—")
        s2.caption("今月、積立対象の必須Goalsがありません。")
    else:
        goals_month_ratio = min(float(actual_goals_pmt_month) / float(goals_save_plan), 1.0) if goals_save_plan > 0 else 0.0
        s2.metric("🎯 Goals積立達成率（当月）", f"{int(goals_month_ratio*100)} %")
        s2.progress(goals_month_ratio)
        s2.caption(f"当月実績：{int(actual_goals_pmt_month):,} 円 / 計画：{int(goals_save_plan):,} 円")

    st.caption(f"NISA判定：{nisa_reason}")

    # ==================================================
    # 収支情報
    # ==================================================
    st.caption(
        f"月収：{int(summary['monthly_income']):,} 円 "
        f"(固定 {int(summary['base_income']):,} / 臨時 {int(summary['variable_income']):,})"
    )
    st.caption(f"固定費：{int(summary['fix_cost']):,} 円 / 変動費：{int(summary['variable_cost']):,} 円")
    st.caption(f"※ 現在資産：{int(summary['current_total_asset']):,} 円（銀行 {int(bank_balance):,} / NISA {int(nisa_balance):,}）")

    # ==================================================
    # 赤字分析
    # ==================================================
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

    # ==================================================
    # メモ分析
    # ==================================================
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

    # ==================================================
    # 生活防衛費（自動算出）
    # ==================================================
    st.subheader("🛡️ 生活防衛費（自動算出）")
    c1, c2, c3 = st.columns(3)
    c1.metric("推定 1か月生活費（中央値）", f"{int(ef['monthly_est_median']):,} 円")
    c2.metric("推定 1か月生活費（P75）", f"{int(ef['monthly_est_p75']):,} 円")
    c3.metric(f"係数（{ef['months_factor']}か月分）", f"{ef['months_factor']} か月")
    st.caption(f"算出方法：{ef['method']}")

    st.subheader("✅ 生活防衛費の達成状況")
    need_rec = float(ef["fund_rec"])
    if need_rec <= 0:
        st.info("生活防衛費の必要額が計算できませんでした（データ不足）。")
    else:
        ratio = min(bank_balance / need_rec, 1.0)
        gap = need_rec - bank_balance
        d1, d2, d3 = st.columns(3)
        d1.metric("現在の安全資金（銀行残高）", f"{int(bank_balance):,} 円")
        d2.metric("必要額（推奨）", f"{int(need_rec):,} 円")
        d3.metric("達成率（推奨）", f"{int(ratio*100)} %")
        st.progress(ratio)
        if gap > 0:
            st.warning(f"推奨ベースで **あと {int(gap):,} 円** 不足しています。")
        else:
            st.success(f"推奨ベースは達成済みです（**+{int(abs(gap)):,} 円** 余裕）。")

    with st.expander("内訳（月次）を見る"):
        df_ef_view = pd.DataFrame({
            "固定費": ef["series_fix"],
            "変動費": ef["series_var"],
            "合計":  ef["series_total"],
        })
        df_ef_view = df_ef_view.apply(pd.to_numeric, errors="coerce").fillna(0)
        st.dataframe(df_ef_view.style.format("{:,.0f}"), use_container_width=True)

    # ==================================================
    # Goals（積立詳細 + 円グラフ）
    # ==================================================
    st.subheader("🎯 Goals（必須）積立の進捗")
    st.caption(f"対象：必須のみ / 今日から {goals_horizon_years} 年先まで")

    if df_goals_progress is None or df_goals_progress.empty:
        st.info("対象期間内に必須Goalsがありません。")
    else:
        # 計画詳細（今月）
        with st.expander("今月のGoals積立（内訳・近→中→長）を見る"):
            if df_goals_plan_detail is None or df_goals_plan_detail.empty:
                st.info("今月、積立が必要な必須Goalsがありません。")
            else:
                view = df_goals_plan_detail.copy()
                view["bucket"] = view["bucket"].map({"near": "近距離", "mid": "中距離", "long": "遠距離"}).fillna(view["bucket"])
                view["達成期限"] = pd.to_datetime(view["deadline"]).dt.strftime("%Y-%m")
                view["残額"] = view["remaining_amount"].astype(float)
                view["最低積立"] = view["min_pmt"].astype(float)
                view["今月計画"] = view["plan_pmt"].astype(float)
                show = view[["bucket", "name", "達成期限", "残額", "最低積立", "今月計画"]].rename(columns={"name":"目標名"})
                st.dataframe(show.style.format({"残額":"{:,.0f}","最低積立":"{:,.0f}","今月計画":"{:,.0f}"}), use_container_width=True)

        # 進捗（累積）
        with st.expander("累積の達成率（項目別 + 円グラフ）を見る"):
            # 近→中→長 の順で表示
            d = df_goals_progress.copy()
            d["bucket_name"] = d["bucket"].map({"near":"近距離","mid":"中距離","long":"遠距離"}).fillna(d["bucket"])
            d["deadline_ym"] = pd.to_datetime(d["deadline"]).dt.strftime("%Y-%m")
            d["達成率"] = d["achieved_rate"].apply(lambda x: f"{int(x*100)} %")

            st.caption(f"Goals累積実績（Goals_Save_Log）：{int(actual_goals_cum):,} 円")

            for i, r in d.iterrows():
                title = f"{r['bucket_name']}｜{r['name']}（期限 {r['deadline_ym']}）｜達成 {int(r['achieved_rate']*100)}%"
                cols = st.columns([1.2, 1.0])
                with cols[0]:
                    st.markdown(f"**{title}**")
                    st.write(f"- 目標額：{int(r['amount']):,} 円")
                    st.write(f"- 達成額：{int(r['achieved_amount']):,} 円")
                    st.write(f"- 残額：{int(r['remaining_amount']):,} 円")
                with cols[1]:
                    plot_goal_pie(
                        title="",
                        achieved=float(r["achieved_amount"]),
                        total=float(r["amount"]),
                        key=f"pie_{i}"
                    )
                st.divider()

    # ==================================================
    # 資産推移（現状）
    # ==================================================
    st.subheader("📊 資産推移（現状）")
    plot_asset_trend(df_balance, ef)

    # ==================================================
    # FI設計（UIで 35/40/45 切替 + FI達成月カード）
    # ==================================================
    st.subheader("🏁 FI（Financial Independence）")

    # UI切替
    spend_choice = st.radio(
        "老後の月額支出（FIライン）",
        options=["35万円", "40万円", "45万円"],
        horizontal=True,
        index=1
    )
    monthly_spend = 350_000 if spend_choice == "35万円" else 400_000 if spend_choice == "40万円" else 450_000

    fi_required_asset = compute_fi_required_asset(monthly_spend, swr_assumption)
    investable_now = bank_balance + nisa_balance
    current_swr = compute_current_swr(monthly_spend, investable_now)

    f1, f2, f3 = st.columns(3)
    f1.metric("🏁 FI必要資産", f"{int(fi_required_asset):,} 円")
    if current_swr is None:
        f2.metric("📉 現在SWR（年）", "—")
    else:
        f2.metric("📉 現在SWR（年）", f"{current_swr*100:.2f} %")
    f3.metric("🧷 採用SWR（仮定）", f"{swr_assumption*100:.2f} %")

    st.caption("SWR（安全取り崩し率）の直感：**小さいほど余裕が大きい**（同じ支出でも、資産が大きいほどSWRは下がる）")

    # ==================================================
    # FIシミュレーション（支出イベント反映 / FI必要資産ベース）
    # ==================================================
    st.subheader("🔮 FIシミュレーション（支出イベント反映）")

    # 現実：直近平均積立（合計）を推定して、今月の配分比で3分割
    real_total_pmt = estimate_realistic_monthly_contribution(df_balance, months=6)

    plan_total = float(bank_save + nisa_save + goals_save_plan)
    if plan_total > 0:
        share_bank = bank_save / plan_total
        share_nisa = nisa_save / plan_total
        share_goals = goals_save_plan / plan_total
    else:
        share_bank = share_nisa = share_goals = 1.0 / 3.0

    monthly_emergency_save_real = float(real_total_pmt * share_bank)
    monthly_nisa_save_real = float(real_total_pmt * share_nisa)
    monthly_goals_save_real = float(real_total_pmt * share_goals)

    st.caption(
        f"現実（予測）に使う月次積立（直近平均）：{int(real_total_pmt):,} 円 / 月 "
        f"（防衛費 {int(monthly_emergency_save_real):,} ・NISA {int(monthly_nisa_save_real):,} ・Goals {int(monthly_goals_save_real):,}）"
    )

    # 現在の Goals fund 推定：累積実績をそのまま「Goals口座残高」とみなす（単純モデル）
    current_goals_fund_est = float(max(actual_goals_cum, 0.0))
    current_emergency_cash_est = float(max(bank_balance - current_goals_fund_est, 0.0))

    show_ideal = st.checkbox("🎯 理想ラインも表示する", value=False)

    df_fi_sim = simulate_fi_paths(
        today=today,
        current_age=current_age,
        end_age=end_age,
        annual_return=annual_return,

        current_emergency_cash=current_emergency_cash_est,
        current_goals_fund=current_goals_fund_est,
        current_nisa=nisa_balance,

        monthly_emergency_save_real=monthly_emergency_save_real,
        monthly_goals_save_real=monthly_goals_save_real,
        monthly_nisa_save_real=monthly_nisa_save_real,

        fi_target_asset=fi_required_asset,
        outflows_by_month=outflows_by_month,
        ef_rec=float(ef["fund_rec"]),
    )

    # FI達成月（カード表示）
    fi_ok = df_fi_sim[df_fi_sim["fi_ok_real"] == True].copy()
    if fi_ok.empty:
        st.info("現実（予測）では、指定の年齢までに FI達成が見つかりませんでした。")
        fi_month_str = "未達"
    else:
        first = fi_ok.iloc[0]
        fi_month_str = pd.to_datetime(first["date"]).strftime("%Y-%m")

    card1, card2, card3 = st.columns(3)
    card1.metric("✅ FI達成月（現実予測）", fi_month_str)
    card2.metric("🏦 推奨防衛費", f"{int(ef['fund_rec']):,} 円")
    card3.metric("📌 現在の投資可能資産（銀行+NISA）", f"{int(investable_now):,} 円")

    plot_fi_simulation(df_fi_sim, fi_required_asset, show_ideal=show_ideal, chart_key="fi_sim_main")

    # ==================================================
    # シミュレーション詳細（支出イベント）
    # ==================================================
    st.markdown("### 🧾 シミュレーション詳細（支出イベント）")
    tab1, tab2 = st.tabs(["💸 支出（必須）", "📦 内訳（現実）"])

    with tab1:
        out = df_fi_sim[df_fi_sim["outflow"].fillna(0) > 0].copy()
        if out.empty:
            st.info("支出イベントはありません。")
        else:
            out["月"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m")
            view = out[["月", "outflow_name", "outflow", "unpaid_real", "unpaid_ideal"]].copy()
            view = view.rename(columns={
                "outflow_name": "支出名",
                "outflow": "支出額",
                "unpaid_real": "未払い（現実）",
                "unpaid_ideal": "未払い（理想）",
            })
            st.dataframe(view.style.format({"支出額":"{:,.0f}","未払い（現実）":"{:,.0f}","未払い（理想）":"{:,.0f}"}), use_container_width=True)

    with tab2:
        view = df_fi_sim.copy()
        view["月"] = pd.to_datetime(view["date"]).dt.strftime("%Y-%m")
        show = view[["月", "emergency_real", "goals_fund_real", "nisa_real", "investable_real", "total_real"]].copy()
        show = show.rename(columns={
            "emergency_real":"防衛費（推定）",
            "goals_fund_real":"Goals口座（推定）",
            "nisa_real":"NISA",
            "investable_real":"投資可能（銀行+NISA）",
            "total_real":"合計（Goals含む）",
        })
        st.dataframe(show.style.format("{:,.0f}"), use_container_width=True)

# ==================================================
# 実行
# ==================================================
if __name__ == "__main__":
    main()
