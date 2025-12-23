import pandas as pd
import re
from datetime import datetime
from collections import defaultdict
import numpy as np

# 設定ファイルを読み込みます
import config

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
    return float(d[(d["month"] == current_month) & (d["費目"].isin(config.EXPENSE_CATEGORIES))]["金額"].sum())

def calculate_monthly_variable_income(df_forms, today):
    if df_forms is None or df_forms.empty:
        return 0.0
    if not {"日付", "金額", "費目"}.issubset(set(df_forms.columns)):
        return 0.0

    current_month = today.strftime("%Y-%m")
    d = df_forms.copy()
    d["month"] = d["日付"].dt.strftime("%Y-%m")
    return float(d[(d["month"] == current_month) & (d["費目"].isin(config.INCOME_CATEGORIES))]["金額"].sum())

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
# メモ頻出分析
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
# カテゴリトレンド分析
# ==================================================
def analyze_category_trend_3m(df_forms, today):
    if df_forms is None or df_forms.empty or not {"日付", "金額", "費目"}.issubset(set(df_forms.columns)):
        return []

    d = df_forms.copy()
    d = d[d["費目"].isin(config.EXPENSE_CATEGORIES)]
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
# 生活防衛費
# ==================================================
def build_month_list(today, months_back=12):
    end = pd.Period(today.strftime("%Y-%m"), freq="M")
    return list(pd.period_range(end=end, periods=months_back, freq="M").astype(str))

def monthly_variable_cost_series(df_forms, months):
    if df_forms is None or df_forms.empty or not {"日付", "金額", "費目"}.issubset(set(df_forms.columns)):
        return pd.Series(0.0, index=months, dtype=float)

    d = df_forms.copy()
    d = d[d["費目"].isin(config.EXPENSE_CATEGORIES)]
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
# Goals関連関数
# ==================================================
def convert_to_jpy_stub(amount, currency, date=None):
    try:
        a = float(amount)
    except Exception:
        return None

    c = str(currency).strip().upper() if currency is not None else "JPY"
    if c in ("JPY", ""):
        return a
    return a

def months_until(today, deadline):
    if pd.isna(deadline):
        return 1
    t = pd.Period(pd.to_datetime(today), freq="M")
    d = pd.Period(pd.to_datetime(deadline), freq="M")
    diff = (d - t).n
    return int(max(diff, 1))

def classify_distance_bucket(today, deadline):
    m = months_until(today, deadline)
    years = m / 12.0
    if years <= config.NEAR_YEARS:
        return "near"
    if years <= config.MID_YEARS:
        return "mid"
    return "long"

def prepare_goals_events(df_goals, today, only_required=True, horizon_years=5):
    if df_goals is None or df_goals.empty:
        return {}, {}, pd.DataFrame()

    required_cols = ["目標名", "金額", "通貨", "達成期限", "優先度", "タイプ"]
    for col in required_cols:
        if col not in df_goals.columns:
            return {}, {}, pd.DataFrame()

    df = df_goals.copy()
    
    if "支払済" in df.columns:
        df = df[~df["支払済"]]

    df["達成期限"] = pd.to_datetime(df["達成期限"], errors="coerce")
    df["金額"] = pd.to_numeric(df["金額"], errors="coerce")
    
    df = df.dropna(subset=["達成期限", "金額"])
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

        outflows_by_month.setdefault(m, []).append(item)
        
        if typ == "目標":
            targets_by_month.setdefault(m, []).append(item)

    df_norm = pd.DataFrame(rows_norm)
    return outflows_by_month, targets_by_month, df_norm

def goals_log_monthly_actual(df_goals_log, today):
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
    if df_goals_log is None or df_goals_log.empty:
        return 0.0
    if "積立額" not in df_goals_log.columns:
        return 0.0
    return float(pd.to_numeric(df_goals_log["積立額"], errors="coerce").fillna(0).sum())

def allocate_goals_progress(df_goals_norm, total_saved):
    if df_goals_norm is None or df_goals_norm.empty:
        return pd.DataFrame()

    d = df_goals_norm.copy()
    
    if d.empty:
        return pd.DataFrame()

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

def compute_goals_monthly_plan(df_goals_progress, today, emergency_not_met):
    if df_goals_progress is None or df_goals_progress.empty:
        return 0.0, pd.DataFrame()

    state = config.STATE_COEF_EMERGENCY_NOT_MET if emergency_not_met else 1.0

    d = df_goals_progress.copy()
    d["months_left"] = d["deadline"].apply(lambda x: months_until(today, x))
    d["min_pmt"] = d.apply(lambda r: 0.0 if r["remaining_amount"] <= 0 else float(r["remaining_amount"] / max(int(r["months_left"]), 1)), axis=1)
    
    d["dist_coef"] = d["bucket"].apply(lambda b: float(config.DIST_COEF.get(str(b), 1.0)))

    d["plan_pmt"] = d.apply(
        lambda r: 0.0 if r["remaining_amount"] <= 0 else float(r["min_pmt"] * (1.0 + (state - 1.0) * r["dist_coef"])),
        axis=1
    )

    total = float(d["plan_pmt"].sum())
    return total, d

# ==================================================
# 今月サマリー & 配分ロジック
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

def allocate_monthly_budget(available_cash, df_goals_plan_detail, emergency_not_met, stock_surplus, monthly_spend_p75):
    """
    今月の予算配分を計算（KPI表示用）
    """
    remaining_flow = float(available_cash)
    
    base_spend = monthly_spend_p75 if monthly_spend_p75 > 0 else 200000
    buffer_target = base_spend * config.BANK_GREEN_BUFFER_MONTHS
    
    # 真の余剰 (Stock Surplus - Buffer)
    excess_wealth = max(stock_surplus - buffer_target, 0.0)
    
    # ランウェイ計算 (余剰 ÷ 月数)
    months_div = config.STOCK_TRANSFER_DURATION_MONTHS if hasattr(config, "STOCK_TRANSFER_DURATION_MONTHS") else 12
    if months_div <= 0: months_div = 1
    stock_transfer_capacity = excess_wealth / months_div

    # 聖域（ミニマム積立）
    req_bank = 0.0
    if emergency_not_met or (stock_surplus < buffer_target):
        req_bank = config.MIN_BANK_AMOUNT
    
    req_nisa = config.MIN_NISA_AMOUNT
    
    bank_alloc = 0.0
    nisa_alloc = 0.0
    
    # 1. 銀行積立
    if remaining_flow >= req_bank:
        bank_alloc = req_bank
        remaining_flow -= bank_alloc
    else:
        bank_alloc = remaining_flow
        remaining_flow = 0.0
        
    # 2. NISA (最低額)
    needed_for_nisa = req_nisa
    from_flow = min(remaining_flow, needed_for_nisa)
    nisa_alloc += from_flow
    remaining_flow -= from_flow
    needed_for_nisa -= from_flow
    
    if needed_for_nisa > 0 and excess_wealth > 0:
        from_stock = min(excess_wealth, needed_for_nisa)
        nisa_alloc += from_stock
        excess_wealth -= from_stock

    # 3. Goals
    total_goals_alloc = 0.0
    
    if df_goals_plan_detail is not None and not df_goals_plan_detail.empty:
        if "bucket_order" not in df_goals_plan_detail.columns:
             bucket_map = {"near": 0, "mid": 1, "long": 2}
             df_goals_plan_detail["bucket_order"] = df_goals_plan_detail["bucket"].map(lambda x: bucket_map.get(str(x), 9))
        
        targets = df_goals_plan_detail.sort_values(["bucket_order", "deadline"])
        
        for _, row in targets.iterrows():
            ideal = float(row["plan_pmt"])
            if ideal <= 0:
                continue
            
            pay_flow = min(remaining_flow, ideal)
            remaining_flow -= pay_flow
            ideal -= pay_flow
            
            pay_stock = 0.0
            if ideal > 0 and excess_wealth > 0 and stock_transfer_capacity > 0:
                pay_stock = min(ideal, excess_wealth, stock_transfer_capacity)
                excess_wealth -= pay_stock
                stock_transfer_capacity -= pay_stock
            
            total_goals_alloc += (pay_flow + pay_stock)
            
    else:
        total_goals_alloc = 0.0

    goals_plan_ideal = df_goals_plan_detail["plan_pmt"].sum() if (df_goals_plan_detail is not None and not df_goals_plan_detail.empty) else 0.0
    goals_shortfall = float(goals_plan_ideal) - total_goals_alloc
    
    return {
        "nisa_save": int(nisa_alloc),
        "bank_save": int(bank_alloc),
        "goals_save": int(total_goals_alloc),
        "goals_shortfall": int(goals_shortfall),
        "ideal_goals_total": int(goals_plan_ideal)
    }

# ==================================================
# FI / SWR 計算
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
# シミュレーション関連（ロジック厳格化版）
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

# logic.py の simulate_fi_paths 関数を修正

def simulate_fi_paths(
    *,
    today,
    current_age,
    end_age,
    annual_return,
    current_emergency_cash, 
    current_goals_fund,     
    current_nisa,           
    monthly_emergency_save_real,
    monthly_goals_save_real,
    monthly_nisa_save_real,
    fi_target_asset,
    outflows_by_month,
    ef_rec,
):
    # 年利換算
    r_nisa_monthly = (1 + float(annual_return)) ** (1 / 12) - 1 if float(annual_return) > -1 else 0.0
    
    months_left = int(max((float(end_age) - float(current_age)) * 12, 1))
    dates = pd.date_range(start=pd.to_datetime(today).normalize(), periods=months_left + 1, freq="MS")

    # 初期状態
    sim_goals = float(current_goals_fund) 
    sim_bank_pure = float(current_emergency_cash)
    sim_nisa = float(current_nisa)

    # ランウェイ計算用設定
    # バッファ目標額
    base_monthly = ef_rec / 6 if ef_rec > 0 else 200000 
    buffer_target_val = base_monthly * config.BANK_GREEN_BUFFER_MONTHS
    
    # 期間（分母）
    runway_months_setting = config.STOCK_TRANSFER_DURATION_MONTHS if hasattr(config, "STOCK_TRANSFER_DURATION_MONTHS") else 18
    if runway_months_setting <= 0: runway_months_setting = 1

    # 理想計算用の変数
    pv_investable = float(current_emergency_cash) + float(current_nisa)
    ideal_pmt_investable = solve_required_monthly_pmt(
        pv=pv_investable,
        fv_target=float(fi_target_asset),
        r_month=r_nisa_monthly,
        n_months=months_left
    )
    
    rows = []

    for i, dt in enumerate(dates):
        month_key = pd.Period(dt, freq="M").strftime("%Y-%m")

        # ----------------------------------------------------
        # 1. 支出イベント
        # ----------------------------------------------------
        items = outflows_by_month.get(month_key, [])
        outflow = float(sum(x["amount"] for x in items)) if items else 0.0
        outflow_name = ""
        if items:
            names = [x["name"] for x in items]
            outflow_name = " / ".join(names[:3]) + (" …" if len(names) > 3 else "")

        pay_from_goals = min(sim_goals, outflow)
        sim_goals -= pay_from_goals
        remain_outflow = outflow - pay_from_goals
        
        pay_from_bank = min(sim_bank_pure, remain_outflow)
        sim_bank_pure -= pay_from_bank
        
        unpaid = remain_outflow - pay_from_bank

        # ----------------------------------------------------
        # 2. 収入と積立（Monthly Cashflow）
        # ----------------------------------------------------
        flow_to_goals = float(monthly_goals_save_real) 
        flow_to_nisa = float(monthly_nisa_save_real)
        flow_to_bank = float(monthly_emergency_save_real)

        # ★修正：動的ランウェイ計算 (Dynamic Runway)
        # 「その月の時点での」真の余剰を計算
        current_surplus = max(sim_bank_pure - buffer_target_val, 0.0)
        
        # 余剰を期間(18)で割った額を、今月のNISAブースト枠とする
        stock_power = current_surplus / runway_months_setting
        
        # 銀行から切り出し
        if stock_power > 0:
            sim_bank_pure -= stock_power

        # ----------------------------------------------------
        # 3. 配分と運用
        # ----------------------------------------------------
        sim_bank_pure += flow_to_bank
        sim_goals += flow_to_goals
        
        # NISA = フロー積立 + ストックからのブースト
        sim_nisa += (flow_to_nisa + stock_power)

        # 運用益
        sim_nisa = sim_nisa * (1 + r_nisa_monthly)

        # ----------------------------------------------------
        # 4. 判定と記録
        # ----------------------------------------------------
        investable_real = sim_nisa + max(sim_bank_pure - buffer_target_val, 0.0)
        total_real = sim_nisa + sim_bank_pure + sim_goals
        fi_ok_real = (investable_real >= float(fi_target_asset))

        rows.append({
            "date": dt,
            "total_real": total_real,
            "investable_real": investable_real,
            "emergency_real": sim_bank_pure,
            "goals_fund_real": sim_goals,
            "nisa_real": sim_nisa,
            "outflow": outflow,
            "outflow_name": outflow_name,
            "unpaid_real": unpaid,
            "fi_ok_real": fi_ok_real,
            "investable_ideal": (pv_investable + ideal_pmt_investable * (i+1)) * ((1+r_nisa_monthly)**(i+1)), 
        })

    df_sim = pd.DataFrame(rows)
    return df_sim
