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
    
    # 列名のゆらぎ吸収（'費目' または 'カテゴリ'）
    col_cat = 'カテゴリ' if 'カテゴリ' in df_forms.columns else '費目'
    
    if not {"日付", "金額", col_cat}.issubset(set(df_forms.columns)):
        return 0.0

    current_month = today.strftime("%Y-%m")
    d = df_forms.copy()
    d["month"] = d["日付"].dt.strftime("%Y-%m")
    
    # 指定した支出カテゴリに含まれるものを集計
    return float(d[(d["month"] == current_month) & (d[col_cat].isin(config.EXPENSE_CATEGORIES))]["金額"].sum())

# ==================================================
# 変動収入（今月）
# ==================================================
def calculate_monthly_variable_income(df_forms, today):
    if df_forms is None or df_forms.empty:
        return 0.0
        
    # 列名のゆらぎ吸収
    col_cat = 'カテゴリ' if 'カテゴリ' in df_forms.columns else '費目'

    if not {"日付", "金額", col_cat}.issubset(set(df_forms.columns)):
        return 0.0

    current_month = today.strftime("%Y-%m")
    d = df_forms.copy()
    d["month"] = d["日付"].dt.strftime("%Y-%m")
    
    # 指定した収入カテゴリに含まれるものを集計
    return float(d[(d["month"] == current_month) & (d[col_cat].isin(config.INCOME_CATEGORIES))]["金額"].sum())
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
    今月の予算配分を計算（現金50%確保 & Goals優先版）
    """
    remaining_flow = float(available_cash)
    
    # 1. 聖域（ミニマム積立）の設定
    # 生活防衛費が足りない、または余剰資産が少ない場合は銀行積立を優先
    base_spend = monthly_spend_p75 if monthly_spend_p75 > 0 else 200000
    buffer_target = base_spend * config.BANK_GREEN_BUFFER_MONTHS
    
    # 必須の銀行積立額（防衛費不足なら全力、そうでなければ0）
    req_bank = config.MIN_BANK_AMOUNT if (emergency_not_met or stock_surplus < buffer_target) else 0.0
    
    # NISAは「少額固定」にする（余っても増やさない）
    req_nisa = config.MIN_NISA_AMOUNT  # config.pyで3000円などに設定されている前提
    
    bank_alloc = 0.0
    nisa_alloc = 0.0
    goals_alloc = 0.0

    # ----------------------------------------------------
    # Step 1: まず最低限の銀行積立（防衛費）を確保
    # ----------------------------------------------------
    if remaining_flow >= req_bank:
        bank_alloc = req_bank
        remaining_flow -= bank_alloc
    else:
        bank_alloc = remaining_flow
        remaining_flow = 0.0

    # ----------------------------------------------------
    # Step 2: 余剰金の「50%」を強制的に銀行に残す（現金確保）
    # ----------------------------------------------------
    if remaining_flow > 0:
        # ★ここがポイント：50%は自由資金として銀行へ
        keep_cash_rate = 0.5
        extra_cash = remaining_flow * keep_cash_rate
        
        bank_alloc += extra_cash
        remaining_flow -= extra_cash

    # ----------------------------------------------------
    # Step 3: NISA（少額固定）を確保
    # ----------------------------------------------------
    from_flow_nisa = min(remaining_flow, req_nisa)
    nisa_alloc += from_flow_nisa
    remaining_flow -= from_flow_nisa
    
    # もしフロー（収入）から足りなくても、資産（stock_surplus）があればそこから出す
    # （NISAは積立を止めないことが重要なので）
    needed_nisa_more = req_nisa - from_flow_nisa
    if needed_nisa_more > 0 and stock_surplus > 0:
        from_stock = min(stock_surplus, needed_nisa_more)
        nisa_alloc += from_stock
        stock_surplus -= from_stock

    # ----------------------------------------------------
    # Step 4: 残り全力を Goals に充てる
    # ----------------------------------------------------
    total_goals_alloc = 0.0
    
    if df_goals_plan_detail is not None and not df_goals_plan_detail.empty:
        # 期限が近い順・優先度高い順にソート
        if "bucket_order" not in df_goals_plan_detail.columns:
             bucket_map = {"near": 0, "mid": 1, "long": 2}
             df_goals_plan_detail["bucket_order"] = df_goals_plan_detail["bucket"].map(lambda x: bucket_map.get(str(x), 9))
        
        targets = df_goals_plan_detail.sort_values(["bucket_order", "deadline"])
        
        for _, row in targets.iterrows():
            ideal = float(row["plan_pmt"])
            if ideal <= 0:
                continue
            
            # 予算から払えるだけ払う
            pay_flow = min(remaining_flow, ideal)
            remaining_flow -= pay_flow
            
            total_goals_alloc += pay_flow
            
    # ----------------------------------------------------
    # Step 5: それでも余ったら？ ➔ 銀行へ（NISAには回さない）
    # ----------------------------------------------------
    if remaining_flow > 0:
        bank_alloc += remaining_flow
        remaining_flow = 0.0

    # 計算結果の整理
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

# ★復活させた関数（ここがエラーの原因でした！）
def estimate_realistic_monthly_contribution(df_balance, months=6):
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

# シミュレーション実行関数
def simulate_fi_paths(today, current_age, end_age, annual_return, 
                      current_emergency_cash, current_goals_fund, current_nisa,
                      monthly_emergency_save_real, monthly_goals_save_real, monthly_nisa_save_real,
                      fi_target_asset, outflows_by_month, ef_rec, green_threshold): # ★引数追加
    
    # (前半の初期化コードはそのまま...)
    months = int((end_age - current_age) * 12)
    dates = pd.date_range(start=today, periods=months, freq='MS')
    r_nisa_monthly = (1 + annual_return)**(1/12) - 1
    
    sim_bank_pure = float(current_emergency_cash) 
    sim_goals = float(current_goals_fund)
    sim_nisa = float(current_nisa)
    
    total_monthly_surplus_power = (
        float(monthly_emergency_save_real) + 
        float(monthly_goals_save_real) + 
        float(monthly_nisa_save_real)
    )

    rows = []
    for i, dt in enumerate(dates):
        month_key = pd.Period(dt, freq="M").strftime("%Y-%m")

        # --- 1. 支出イベント（変更なし） ---
        items = outflows_by_month.get(month_key, [])
        outflow = float(sum(x["amount"] for x in items)) if items else 0.0
        available_to_pay = max(sim_bank_pure + sim_goals, 0.0)
        actual_payment = min(outflow, available_to_pay)
        unpaid_amount = outflow - actual_payment
        
        pay_from_goals = min(sim_goals, actual_payment)
        sim_goals -= pay_from_goals
        pay_from_bank = actual_payment - pay_from_goals
        sim_bank_pure -= pay_from_bank

        # --- 2. 収入と積立（3段階ロジック） ---
        alloc_bank = 0.0
        alloc_goals = 0.0
        alloc_nisa = 0.0
        
        # NISA最低額
        min_nisa = 3000.0
        remain_power = max(total_monthly_surplus_power - min_nisa, 0.0)
        alloc_nisa += min(total_monthly_surplus_power, min_nisa)

        if sim_bank_pure < ef_rec:
            # 🚨【レッドゾーン】生活防衛費割れ
            # 緊急事態：全力を銀行へ
            alloc_bank += remain_power
            
        elif sim_bank_pure < green_threshold:
            # ⚠️【イエローゾーン】防衛費はあるが、バッファー構築中
            # 50:50 の法則発動
            half = remain_power * 0.5
            alloc_bank += half
            alloc_goals += half
            
        else:
            # ✅【グリーンゾーン】バッファーも十分！
            # もう現金はいらない。全力をGoals（またはNISA）へ。
            alloc_goals += remain_power

        # 積立実行
        sim_bank_pure += alloc_bank
        sim_goals += alloc_goals
        sim_nisa += alloc_nisa

        # --- 3. 運用益と記録（変更なし） ---
        sim_nisa *= (1 + r_nisa_monthly)
        investable_real = sim_nisa + max(sim_bank_pure - ef_rec, 0.0)

        rows.append({
            "date": dt,
            "investable_real": investable_real,
            "nisa_real": sim_nisa,
            "emergency_real": sim_bank_pure,
            "goals_fund_real": sim_goals,
            
            # ★この行を追加してください！
            "total_real": sim_nisa + sim_bank_pure + sim_goals,
            
            "outflow": outflow,
            "unpaid_real": unpaid_amount,
            "outflow_name": " / ".join([x["name"] for x in items]) if items else ""
        })

    df_sim = pd.DataFrame(rows)
    return df_sim
    
# logic.py の simulate_fi_paths 関数内を修正

    for i, dt in enumerate(dates):
        month_key = pd.Period(dt, freq="M").strftime("%Y-%m")

        # ----------------------------------------------------
        # 1. 支出イベント（Goals）修正版
        # ----------------------------------------------------
        items = outflows_by_month.get(month_key, [])
        outflow = float(sum(x["amount"] for x in items)) if items else 0.0
        
        # ★ここを修正: 支払能力の計算（防衛費を死守する！）
        
        # 使えるお金 = 「Goals積立金」 + 「銀行にある余剰金（防衛費を超えた分だけ）」
        # ※もし銀行残高が防衛費以下なら、銀行からは 1円 も出さない
        surplus_in_bank = max(sim_bank_pure - ef_rec, 0.0)
        available_to_pay = sim_goals + surplus_in_bank
        
        # 実際の支払い実行
        actual_payment = min(outflow, available_to_pay)
        
        # 足りない分は「不足額」として計上（銀行を0にするよりマシ！）
        unpaid_amount = outflow - actual_payment
        
        # 資産からの引き落とし処理
        # まずGoals積立金から払う
        pay_from_goals = min(sim_goals, actual_payment)
        sim_goals -= pay_from_goals
        
        # 足りなければ銀行の「余剰分」から払う
        pay_from_bank = actual_payment - pay_from_goals
        sim_bank_pure -= pay_from_bank
        
        # ※このロジックなら、sim_bank_pure が ef_rec を下回ることはありません
        # ----------------------------------------------------
        # 2. 収入と積立（ブレーキ機能付き）
        # ----------------------------------------------------
        # 防衛費が足りない場合は、NISAブーストを停止する
        current_surplus = max(sim_bank_pure - ef_rec, 0.0)
        stock_power = current_surplus / runway_months_setting if current_surplus > 0 else 0.0

        # 積立実行
        sim_bank_pure += float(monthly_emergency_save_real)
        sim_goals += float(monthly_goals_save_real)
        sim_nisa += (float(monthly_nisa_save_real) + stock_power)
        if stock_power > 0:
            sim_bank_pure -= stock_power

        # ----------------------------------------------------
        # 3. 運用益と記録
        # ----------------------------------------------------
        sim_nisa *= (1 + r_nisa_monthly)
        
        # 投資可能資産の定義（防衛費を引いた「緑のお金」）
        investable_real = sim_nisa + max(sim_bank_pure - ef_rec, 0.0)

        rows.append({
            "date": dt,
            "investable_real": investable_real,
            "nisa_real": sim_nisa,
            "emergency_real": sim_bank_pure,
            "goals_fund_real": sim_goals,
            "outflow": outflow,
            "unpaid_real": unpaid_amount,  # ★テーブルで表示
            "outflow_name": " / ".join([x["name"] for x in items]) if items else ""
        })

    df_sim = pd.DataFrame(rows)
    return df_sim
# ==================================================
# 「実質所得」の計算ロジック
# ==================================================
def calculate_tax_status(df_forms, params):
    """
    収入データを分類し、税金・扶養の進捗を計算する
    """
    if df_forms is None or df_forms.empty:
        return None

    # 今年（当年）のデータのみを抽出
    current_year = pd.Timestamp.now().year
    
    # 日付列を確実にdatetime型に変換
    df_forms = df_forms.copy()
    df_forms['日付'] = pd.to_datetime(df_forms['日付'])
    df_this_year = df_forms[df_forms['日付'].dt.year == current_year].copy()

    # 列名の特定（「カテゴリ」がなければ「費目」を使う）
    col_name = 'カテゴリ' if 'カテゴリ' in df_this_year.columns else '費目'

    # 1. 収入を3層に分類して集計
    salary_total = df_this_year[df_this_year[col_name] == '給与収入（バイト代・大学からの給与など）']['金額'].sum()
    side_total = df_this_year[df_this_year[col_name] == '副業・雑収入（note・案件・講演謝礼など）']['金額'].sum()
    tax_free_total = df_this_year[df_this_year[col_name] == '非課税収入（仕送り・奨学金・お祝いなど）']['金額'].sum()

    # 2. 所得への変換計算
    salary_deduction = float(params.get('SALARY_DEDUCTION_MIN', 550000))
    salary_income = max(salary_total - salary_deduction, 0.0)

    note_fee_rate = float(params.get('NOTE_FEE_RATE', 0.2))
    side_income = side_total * (1.0 - note_fee_rate)

    total_taxable_income = salary_income + side_income

    return {
        "salary_total": salary_total,
        "side_total": side_total,
        "side_net_profit": side_income,
        "total_taxable_income": total_taxable_income,
        "tax_free_total": tax_free_total
    }
