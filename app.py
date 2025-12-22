import streamlit as st
import pandas as pd
from datetime import datetime, date
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import re
from collections import defaultdict
import time
import plotly.graph_objects as go

# ==================================================
# Streamlit 設定
# ==================================================
st.set_page_config(page_title="💰 My Financial Pilot", layout="wide")

# ==================================================
# Google Sheets 設定
# ==================================================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1pb1IH1twG9XDIo6Ma88XKcndnnet-dlHxQPu9zjbJ5w/edit?gid=2102244245#gid=2102244245"

# ==================================================
# 戦略パラメータ
# ==================================================
NEAR_YEARS = 2
MID_YEARS = 5

# 距離係数（遠距離の負担を軽減）
DIST_COEF = {
    "near": 1.0,
    "mid": 0.3,
    "long": 0.05,
}

STATE_COEF_EMERGENCY_NOT_MET = 1.1

# NISA特別ルール（軍資金10万円期間）
NISA_FIXED_START = date(2025, 2, 7)
NISA_FIXED_END = date(2025, 12, 7)
NISA_FIXED_AMOUNT = 10000.0

EXPENSE_CATEGORIES = [
    "食費（外食・交際）", "食費（日常）", "趣味・娯楽", "研究・書籍",
    "日用品", "交通費", "衣料品", "特別費", "その他",
]
INCOME_CATEGORIES = ["給与・バイト代", "臨時収入"]

# ==================================================
# データ読み込み・前処理
# ==================================================
def get_spreadsheet():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
    service = build("sheets", "v4", credentials=creds)
    return service.spreadsheets()

@st.cache_data(ttl=60)
def load_data():
    sheet = get_spreadsheet()
    spreadsheet_id = SPREADSHEET_URL.split("/d/")[1].split("/")[0]

    def get_df(sheet_name, range_):
        try:
            res = sheet.values().get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!{range_}").execute()
            values = res.get("values", [])
            if not values: return pd.DataFrame()
            header = values[0]
            data = values[1:]
            n_cols = len(header)
            fixed_data = [row + [None] * (n_cols - len(row)) for row in data]
            return pd.DataFrame(fixed_data, columns=header)
        except Exception:
            return pd.DataFrame()

    df_params  = get_df("Parameters", "A:D")
    df_fix     = get_df("Fix_Cost",   "A:G")
    df_forms   = get_df("Forms_Log",  "A:G")
    df_balance = get_df("Balance_Log","A:C")
    df_goals   = get_df("Goals",      "A:Z") 
    df_goals_log = get_df("Goals_Save_Log","A:D")

    return df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log

def preprocess_data(df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log):
    if not df_params.empty and "適用開始日" in df_params.columns:
        df_params["適用開始日"] = pd.to_datetime(df_params["適用開始日"], errors="coerce")

    if not df_fix.empty:
        if "開始日" in df_fix.columns: df_fix["開始日"] = pd.to_datetime(df_fix["開始日"], errors="coerce")
        if "終了日" in df_fix.columns: df_fix["終了日"] = pd.to_datetime(df_fix["終了日"], errors="coerce")
        if "金額" in df_fix.columns: df_fix["金額"] = pd.to_numeric(df_fix["金額"], errors="coerce").fillna(0)
        if "サイクル" in df_fix.columns: df_fix["サイクル"] = df_fix["サイクル"].fillna("毎月")

    if not df_forms.empty:
        if "日付" in df_forms.columns: df_forms["日付"] = pd.to_datetime(df_forms["日付"], errors="coerce")
        if "金額" in df_forms.columns: df_forms["金額"] = pd.to_numeric(df_forms["金額"], errors="coerce").fillna(0)
        if "満足度" in df_forms.columns: df_forms["満足度"] = pd.to_numeric(df_forms["満足度"], errors="coerce")
        if "費目" in df_forms.columns: df_forms["費目"] = df_forms["費目"].astype(str).str.strip()

    if not df_balance.empty:
        if "日付" in df_balance.columns: df_balance["日付"] = pd.to_datetime(df_balance["日付"], errors="coerce")
        if "銀行残高" in df_balance.columns: df_balance["銀行残高"] = pd.to_numeric(df_balance["銀行残高"], errors="coerce")
        if "NISA評価額" in df_balance.columns: df_balance["NISA評価額"] = pd.to_numeric(df_balance["NISA評価額"], errors="coerce")

    if df_goals is not None and (not df_goals.empty):
        df_goals.columns = df_goals.columns.str.strip()
        if "達成期限" in df_goals.columns: df_goals["達成期限"] = pd.to_datetime(df_goals["達成期限"], errors="coerce")
        if "金額" in df_goals.columns:
            df_goals["金額"] = df_goals["金額"].astype(str).str.replace(",", "").str.replace("¥", "").str.replace("円", "")
            df_goals["金額"] = pd.to_numeric(df_goals["金額"], errors="coerce")
        if "支払済" in df_goals.columns:
            df_goals["支払済"] = df_goals["支払済"].astype(str).str.strip().str.upper() == "TRUE"
        else:
            df_goals["支払済"] = False

    if df_goals_log is not None and (not df_goals_log.empty):
        if "月" in df_goals_log.columns:
            def parse_month(x):
                s = str(x).strip()
                if re.match(r"^\d{4}-\d{2}$", s): s = s + "-01"
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
# 計算・ロジック
# ==================================================
def get_latest_parameter(df, item, target_date):
    if df is None or df.empty: return None
    if not {"項目", "値", "適用開始日"}.issubset(set(df.columns)): return None
    d = df.copy()
    d = d[d["項目"] == item].dropna(subset=["適用開始日"])
    d = d[d["適用開始日"] <= target_date]
    if d.empty: return None
    return d.sort_values("適用開始日").iloc[-1]["値"]

def to_float_safe(x, default=0.0):
    try: return float(x) if x is not None else default
    except: return default

def to_int_safe(x, default=0):
    try: return int(float(x)) if x is not None else default
    except: return default

def calculate_monthly_fix_cost(df_fix, today):
    if df_fix is None or df_fix.empty: return 0.0
    d = df_fix.copy()
    active = d[(d["開始日"].notna()) & (d["開始日"] <= today) & ((d["終了日"].isna()) | (d["終了日"] >= today))]
    return float(active["金額"].sum())

def calculate_monthly_variable_cost(df_forms, today):
    if df_forms is None or df_forms.empty: return 0.0
    current_month = today.strftime("%Y-%m")
    d = df_forms.copy()
    d["month"] = d["日付"].dt.strftime("%Y-%m")
    return float(d[(d["month"] == current_month) & (d["費目"].isin(EXPENSE_CATEGORIES))]["金額"].sum())

def calculate_monthly_variable_income(df_forms, today):
    if df_forms is None or df_forms.empty: return 0.0
    current_month = today.strftime("%Y-%m")
    d = df_forms.copy()
    d["month"] = d["日付"].dt.strftime("%Y-%m")
    return float(d[(d["month"] == current_month) & (d["費目"].isin(INCOME_CATEGORIES))]["金額"].sum())

def get_latest_bank_balance(df_balance):
    if df_balance is None or df_balance.empty: return None
    d = df_balance.copy().dropna(subset=["日付", "銀行残高"]).sort_values("日付")
    return float(d.iloc[-1]["銀行残高"]) if not d.empty else None

def get_latest_nisa_balance(df_balance):
    if df_balance is None or df_balance.empty: return 0.0
    d = df_balance.copy().dropna(subset=["日付"]).sort_values("日付")
    v = pd.to_numeric(d.iloc[-1]["NISA評価額"], errors="coerce") if not d.empty else 0.0
    return 0.0 if pd.isna(v) else float(v)

def get_latest_total_asset(df_balance):
    return float((get_latest_bank_balance(df_balance) or 0.0) + (get_latest_nisa_balance(df_balance) or 0.0))

# --- 生活防衛費 ---
def build_month_list(today, months_back=12):
    end = pd.Period(today.strftime("%Y-%m"), freq="M")
    return list(pd.period_range(end=end, periods=months_back, freq="M").astype(str))

def monthly_variable_cost_series(df_forms, months):
    if df_forms is None or df_forms.empty: return pd.Series(0.0, index=months)
    d = df_forms.copy()
    d = d[d["費目"].isin(EXPENSE_CATEGORIES)]
    d["month"] = d["日付"].dt.to_period("M").astype(str)
    return d.groupby("month")["金額"].sum().reindex(months, fill_value=0.0).astype(float)

def monthly_fix_cost_series(df_fix, months):
    if df_fix is None or df_fix.empty: return pd.Series(0.0, index=months)
    d = df_fix.copy()
    out = pd.Series(0.0, index=months, dtype=float)
    for m in months:
        p = pd.Period(m, freq="M")
        active = d[(d["開始日"].notna()) & (d["開始日"] <= p.end_time) & ((d["終了日"].isna()) | (d["終了日"] >= p.start_time))].copy()
        if active.empty: continue
        active["monthly_amount"] = active.apply(lambda r: r["金額"] if "毎月" in str(r["サイクル"]) else (r["金額"]/12.0 if "毎年" in str(r["サイクル"]) else r["金額"]), axis=1)
        out[m] = float(active["monthly_amount"].sum())
    return out

def estimate_emergency_fund(df_params, df_fix, df_forms, today):
    n = get_latest_parameter(df_params, "生活防衛費係数（月のN数）", today)
    n_months = int(float(n)) if n else 6
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
        method = f"過去{len(nonzero)}か月（中央値・P75）"

    return {
        "months_factor": n_months,
        "method": method,
        "monthly_est_median": base,
        "fund_rec": float(base * n_months),
        "fund_min": float(base * 3),
        "series_fix": fix_s,
        "series_var": var_s,
        "series_total": total_s
    }

# --- Goals ---
def convert_to_jpy_stub(amount, currency, date=None):
    try: return float(amount)
    except: return None

def months_until(today, deadline):
    if pd.isna(deadline): return 1
    t = pd.Period(pd.to_datetime(today), freq="M")
    d = pd.Period(pd.to_datetime(deadline), freq="M")
    return int(max((d - t).n, 1))

def classify_distance_bucket(today, deadline):
    m = months_until(today, deadline)
    years = m / 12.0
    if years <= NEAR_YEARS: return "near"
    if years <= MID_YEARS: return "mid"
    return "long"

def prepare_goals_events(df_goals, today, only_required=True, horizon_years=5):
    if df_goals is None or df_goals.empty: return {}, {}, pd.DataFrame()
    df = df_goals.copy()
    if "支払済" in df.columns: df = df[~df["支払済"]]
    df["達成期限"] = pd.to_datetime(df["達成期限"], errors="coerce")
    df["金額"] = pd.to_numeric(df["金額"], errors="coerce")
    df = df.dropna(subset=["達成期限", "金額"])
    
    horizon_dt = pd.to_datetime(today).normalize() + pd.DateOffset(years=int(max(horizon_years, 1)))
    df = df[(df["達成期限"] >= pd.to_datetime(today).normalize()) & (df["達成期限"] <= horizon_dt)]
    
    if only_required and "優先度" in df.columns:
        df = df[df["優先度"].astype(str).str.contains("必須", na=False)]

    if df.empty: return {}, {}, pd.DataFrame()

    df["month"] = df["達成期限"].dt.to_period("M").astype(str)
    df["bucket"] = df["達成期限"].apply(lambda x: classify_distance_bucket(today, x))

    outflows, targets = {}, {}
    rows = []
    for _, r in df.iterrows():
        try: amt = float(r["金額"])
        except: continue
        item = {
            "name": str(r["目標名"]), "amount": amt, "priority": str(r["優先度"]),
            "deadline": r["達成期限"], "bucket": str(r["bucket"]), "type": str(r["タイプ"])
        }
        rows.append(item | {"month": str(r["month"])})
        outflows.setdefault(str(r["month"]), []).append(item)
        if str(r["タイプ"]) == "目標": targets.setdefault(str(r["month"]), []).append(item)

    return outflows, targets, pd.DataFrame(rows)

def allocate_goals_progress(df_goals_norm, total_saved):
    if df_goals_norm is None or df_goals_norm.empty: return pd.DataFrame()
    d = df_goals_norm.copy()
    bucket_order = {"near": 0, "mid": 1, "long": 2}
    d["bucket_order"] = d["bucket"].map(lambda x: bucket_order.get(str(x), 9))
    d = d.sort_values(["bucket_order", "deadline", "name"])

    remain = float(max(total_saved, 0.0))
    achieved = []
    for _, r in d.iterrows():
        use = min(remain, float(r["amount"]))
        remain -= use
        achieved.append(use)

    d["achieved_amount"] = achieved
    d["remaining_amount"] = (d["amount"] - d["achieved_amount"]).clip(lower=0.0)
    d["achieved_rate"] = d.apply(lambda r: 0.0 if r["amount"]<=0 else r["achieved_amount"]/r["amount"], axis=1)
    return d

def compute_goals_monthly_plan(df_goals_progress, today, emergency_not_met):
    if df_goals_progress is None or df_goals_progress.empty: return 0.0, pd.DataFrame()
    state = STATE_COEF_EMERGENCY_NOT_MET if emergency_not_met else 1.0
    d = df_goals_progress.copy()
    d["months_left"] = d["deadline"].apply(lambda x: months_until(today, x))
    d["min_pmt"] = d.apply(lambda r: 0.0 if r["remaining_amount"]<=0 else r["remaining_amount"]/max(int(r["months_left"]), 1), axis=1)
    d["dist_coef"] = d["bucket"].apply(lambda b: float(DIST_COEF.get(str(b), 1.0)))
    d["plan_pmt"] = d.apply(lambda r: 0.0 if r["remaining_amount"]<=0 else r["min_pmt"] * (1.0 + (state-1.0)*r["dist_coef"]) * r["dist_coef"], axis=1)
    return float(d["plan_pmt"].sum()), d

def goals_log_monthly_actual(df_log, today):
    if df_log is None or df_log.empty: return 0.0
    cur = pd.to_datetime(today).to_period("M")
    d = df_log.dropna(subset=["月_dt"])
    return float(d[d["月_dt"].dt.to_period("M") == cur]["積立額"].sum())

def goals_log_cumulative(df_log):
    if df_log is None or df_log.empty: return 0.0
    return float(pd.to_numeric(df_log["積立額"], errors="coerce").fillna(0).sum())

# ==================================================
# FI / NISA
# ==================================================
def compute_nisa_coefficient(*, available_cash_after_goals, emergency_not_met, emergency_is_danger, goals_shortfall):
    if available_cash_after_goals <= 0: return 0.0, "赤字またはGoals後に余剰なし → NISA 0"
    if goals_shortfall: return 0.0, "Goals積立が不足 → NISA 0"
    if emergency_is_danger: return 0.0, "生活防衛費 危険ゾーン → NISA 0"
    if emergency_not_met: return 0.0, "生活防衛費 未達 → NISA 0（2段階）"
    return 1.0, "条件OK → NISA 100%"

def compute_fi_required_asset(monthly_spend, swr_assumption):
    return float(monthly_spend * 12.0 / swr_assumption) if swr_assumption > 0 else float("inf")

def compute_current_swr(monthly_spend, investable_asset):
    return float(monthly_spend * 12.0 / investable_asset) if investable_asset > 0 else None

def solve_required_monthly_pmt(pv, fv_target, r_month, n_months):
    if r_month <= 0: return max((fv_target - pv) / max(n_months,1), 0.0)
    a = (1 + r_month) ** n_months
    return max((fv_target - pv * a) / ((a - 1) / r_month), 0.0)

def apply_outflow_three_pockets(goals_fund, emergency_cash, nisa, outflow):
    used_goals = min(goals_fund, outflow)
    goals_fund -= used_goals
    remain = outflow - used_goals
    used_em = min(emergency_cash, remain)
    emergency_cash -= used_em
    remain2 = remain - used_em
    used_nisa = min(nisa, remain2)
    nisa -= used_nisa
    return goals_fund, emergency_cash, nisa, used_goals, used_em, used_nisa, remain2 - used_nisa

def estimate_realistic_monthly_contribution(df_balance, months=6):
    if df_balance is None or df_balance.empty: return 0.0
    df = df_balance.copy()
    df["日付"] = pd.to_datetime(df["日付"], errors="coerce")
    df["銀行残高"] = pd.to_numeric(df["銀行残高"], errors="coerce")
    df["NISA評価額"] = pd.to_numeric(df["NISA評価額"], errors="coerce")
    df = df.dropna(subset=["日付"]).sort_values("日付")
    if df.empty or len(df) < 2: return 0.0
    df["total"] = df["銀行残高"].fillna(0) + df["NISA評価額"].fillna(0)
    df["month"] = df["日付"].dt.to_period("M").astype(str)
    monthly_last = df.groupby("month", as_index=False)["total"].last()
    monthly_last["diff"] = monthly_last["total"].diff()
    diffs = monthly_last["diff"].dropna().tail(months)
    if diffs.empty: return 0.0
    return float(diffs[diffs > 0].mean()) if (diffs > 0).any() else 0.0

def simulate_fi_paths(today, current_age, end_age, annual_return, cur_em, cur_gf, cur_ni, monthly_em_real, monthly_gf_real, monthly_ni_real, fi_target, outflows, ef_rec):
    r = (1 + float(annual_return)) ** (1 / 12) - 1 if float(annual_return) > -1 else 0.0
    months_left = int(max((float(end_age) - float(current_age)) * 12, 1))
    dates = pd.date_range(start=pd.to_datetime(today).normalize(), periods=months_left + 1, freq="MS")
    
    # 理想ライン（参考）
    pv_inv = cur_em + cur_ni
    ideal_pmt = solve_required_monthly_pmt(pv_inv, fi_target, r, months_left)
    
    em, gf, ni = cur_em, cur_gf, cur_ni
    em_i, gf_i, ni_i = cur_em, cur_gf, cur_ni

    rows = []
    for i, dt in enumerate(dates):
        month_key = pd.Period(dt, freq="M").strftime("%Y-%m")
        items = outflows.get(month_key, [])
        outflow = sum(x["amount"] for x in items) if items else 0.0
        
        # 支出イベント
        gf, em, ni, _, _, _, _ = apply_outflow_three_pockets(gf, em, ni, outflow)
        gf_i, em_i, ni_i, _, _, _, _ = apply_outflow_three_pockets(gf_i, em_i, ni_i, outflow)

        # 記録
        fi_ok_real = (em + ni >= fi_target) and (em >= ef_rec)
        rows.append({
            "date": dt,
            "investable_real": em + ni,
            "total_real": gf + em + ni,
            "investable_ideal": em_i + ni_i,
            "fi_ok_real": fi_ok_real,
            "outflow": outflow
        })

        if i == len(dates) - 1: break

        # NISA特別ルール適用
        dt_date = dt.date()
        if NISA_FIXED_START <= dt_date <= NISA_FIXED_END:
            ni_add = NISA_FIXED_AMOUNT
            em += monthly_em_real
            gf += monthly_gf_real
        else:
            ni_add = monthly_ni_real
            em += monthly_em_real
            gf += monthly_gf_real

        ni = (ni + ni_add) * (1 + r)
        ni_i = (ni_i + ideal_pmt * 0.8) * (1 + r)
        em_i += ideal_pmt * 0.2
        gf_i += monthly_gf_real

    return pd.DataFrame(rows)

# ==================================================
# UI Component Functions (Graph Integrated)
# ==================================================
def ui_kpi_cards(bank_save, nisa_save, goals_save, free_cash, nisa_reason, ef_status, ef_ratio):
    st.markdown("### 🗓️ 今月のミッション")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("🏦 銀行へ", f"{int(bank_save):,} 円", help="【生活防衛費向け】不測の事態や、直近の大きな出費に備えるための現金貯蓄です。生活防衛費が推奨額に達するまではここが優先されます。")
    with col2:
        st.metric("📈 NISAへ", f"{int(nisa_save):,} 円", help=f"【老後・超長期向け】生活防衛費とGoals積立を満たした後の「余剰資金」のみがここに回ります。\n現在の判定理由: {nisa_reason}")
    with col3:
        st.metric("🎯 Goals口座へ", f"{int(goals_save):,} 円", help="【将来の必須支出】iPhone買い替えや学費など、期限が決まっている支出のために取り分けておくお金です。")
    with col4:
        st.metric("🎉 自由費", f"{int(free_cash):,} 円", help="【趣味・娯楽】上記の積立を全て終えた後に残ったお金です。この金額の範囲内なら、何に使っても将来に影響しません。")

    if ef_ratio < 1.0:
        st.warning(f"🛡️ 生活防衛費：あと {int((1.0-ef_ratio)*100)}% で安心ラインです")
    else:
        st.success("🛡️ 生活防衛費：達成済み！素晴らしいです")

def plot_combined_timeline(df_balance, df_fi_sim, fi_req):
    # データを結合するための準備
    fig = go.Figure()

    # --- 1. 過去（実績） ---
    if df_balance is not None and not df_balance.empty:
        df_hist = df_balance.copy().sort_values("日付")
        df_hist["total"] = df_hist["銀行残高"] + df_hist["NISA評価額"]
        
        fig.add_trace(go.Scatter(x=df_hist["日付"], y=df_hist["銀行残高"], name="🏦 実績：銀行", stackgroup='one', line=dict(width=0), fillcolor='rgba(0, 104, 201, 0.5)'))
        fig.add_trace(go.Scatter(x=df_hist["日付"], y=df_hist["NISA評価額"], name="📈 実績：NISA", stackgroup='one', line=dict(width=0), fillcolor='rgba(255, 140, 0, 0.5)'))
        fig.add_trace(go.Scatter(x=df_hist["日付"], y=df_hist["total"], name="💰 実績：合計", mode='lines', line=dict(color='blue', width=2)))

    # --- 2. 未来（予測） ---
    if df_fi_sim is not None and not df_fi_sim.empty:
        # 予測線の色設定
        fig.add_trace(go.Scatter(x=df_fi_sim["date"], y=df_fi_sim["total_real"], name="🔮 予測：総資産", line=dict(color='green', dash='dash')))
        fig.add_trace(go.Scatter(x=df_fi_sim["date"], y=df_fi_sim["investable_real"], name="🛡️ 予測：投資可能資産", line=dict(color='orange', dash='dot')))
        
        # FIライン
        fig.add_hline(y=fi_req, line_dash="dash", line_color="red", annotation_text="🏁 FI目標")

    # --- 3. 現在地（縦線） ---
    today = datetime.today()
    fig.add_vline(x=today, line_width=2, line_dash="dash", line_color="gray", annotation_text="現在")

    fig.update_layout(
        title="📈 資産の過去と未来（統合タイムライン）",
        xaxis_title="日付",
        yaxis_title="金額（円）",
        hovermode="x unified",
        height=500,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig, use_container_width=True)

def ui_main_tabs(df_balance, ef, df_goals_progress, df_fi_sim, fi_req, show_ideal, goals_data, summary):
    # ★統合グラフをタブの外（メイン）に配置
    plot_combined_timeline(df_balance, df_fi_sim, fi_req)

    tab1, tab2, tab3 = st.tabs(["🎯 Goals詳細", "🔮 FI詳細", "📝 データ内訳"])
    
    with tab1:
        st.subheader("Goals（必須）積立の進捗", help="対象：必須のみ / 今日から 5 年先まで")
        # caption削除済み
        if df_goals_progress.empty:
            st.info("直近の必須Goalsはありません")
        else:
            for i, r in df_goals_progress.iterrows():
                rate = r['achieved_rate']
                st.write(f"**{r['name']}** (あと {int(r['remaining_amount']):,} 円)")
                st.progress(min(rate, 1.0))

    with tab2:
        st.subheader("FIシミュレーション詳細")
        fi_ok = df_fi_sim[df_fi_sim["fi_ok_real"] == True]
        fi_date = fi_ok.iloc[0]["date"].strftime("%Y-%m") if not fi_ok.empty else "未達"
        st.metric("🏁 FI達成予測", fi_date)
        # 詳細なFIチャートが見たい場合はここにも残しておく（オプション）
        plot_fi_simulation(df_fi_sim, fi_req, show_ideal, "fi_chart_detail")

    with tab3:
        st.write("#### 収支内訳")
        st.json(summary)
        st.write("#### Goals積立詳細")
        if goals_data is not None:
            st.dataframe(goals_data)

# ==================================================
# Main Logic
# ==================================================
def main():
    st.title("💰 My Financial Pilot")
    
    df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log = load_data()
    df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log = preprocess_data(
        df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log
    )
    today = datetime.today()

    goals_horizon = to_int_safe(get_latest_parameter(df_params, "Goals積立対象年数", today), default=5)
    swr = to_float_safe(get_latest_parameter(df_params, "SWR", today), default=0.035)
    end_age = to_float_safe(get_latest_parameter(df_params, "老後年齢", today), default=60.0)
    cur_age = to_float_safe(get_latest_parameter(df_params, "現在年齢", today), default=21.0)
    roi = to_float_safe(get_latest_parameter(df_params, "投資年利", today), default=0.05)

    summary = calculate_monthly_summary(df_params, df_fix, df_forms, df_balance, today)
    ef = estimate_emergency_fund(df_params, df_fix, df_forms, today)
    
    bank_bal = float(summary["current_bank"])
    ef_not_met = bank_bal < float(ef["fund_rec"])
    
    outflows, targets, df_goals_norm = prepare_goals_events(df_goals, today, True, goals_horizon)
    goals_cum = goals_log_cumulative(df_goals_log)
    df_goals_prog = allocate_goals_progress(df_goals_norm, goals_cum)
    goals_plan, df_goals_detail = compute_goals_monthly_plan(df_goals_prog, today, ef_not_met)

    avail_cash = float(summary["available_cash"])
    avail_after_goals = max(avail_cash - goals_plan, 0.0)
    
    is_nisa_fixed_period = NISA_FIXED_START <= today.date() <= NISA_FIXED_END
    
    if is_nisa_fixed_period:
        nisa_plan = min(NISA_FIXED_AMOUNT, avail_after_goals)
        nisa_reason = "軍資金活用期間（月1万円定額）"
    else:
        nisa_coef, nisa_reason = compute_nisa_coefficient(
            available_cash_after_goals=avail_after_goals,
            emergency_not_met=ef_not_met,
            emergency_is_danger=(bank_bal < float(ef["fund_min"])),
            goals_shortfall=(avail_cash < goals_plan)
        )
        nisa_plan = float(avail_after_goals * nisa_coef)

    bank_plan = max(avail_after_goals - nisa_plan, 0.0)
    free_cash = max(avail_cash - goals_plan - bank_plan - nisa_plan, 0.0)

    fi_req = compute_fi_required_asset(350000, swr)
    real_pmt = max(estimate_realistic_monthly_contribution(df_balance), bank_plan + nisa_plan + goals_plan)
    
    total_plan = bank_plan + nisa_plan + goals_plan
    if total_plan > 0:
        share_bk = bank_plan / total_plan
        share_ni = nisa_plan / total_plan
        share_gl = goals_plan / total_plan
    else:
        share_bk = 1.0; share_ni = 0.0; share_gl = 0.0

    df_fi = simulate_fi_paths(
        today=today, current_age=cur_age, end_age=end_age, annual_return=roi,
        current_emergency_cash=max(bank_bal - goals_cum, 0),
        current_goals_fund=goals_cum,
        current_nisa=float(summary["current_nisa"]),
        monthly_emergency_save_real=real_pmt * share_bk,
        monthly_goals_save_real=real_pmt * share_gl,
        monthly_nisa_save_real=real_pmt * share_ni,
        fi_target_asset=fi_req,
        outflows_by_month=outflows,
        ef_rec=float(ef["fund_rec"])
    )

    # UI Rendering
    ef_rec_val = float(ef["fund_rec"])
    ef_min_val = float(ef["fund_min"])
    if bank_bal >= ef_rec_val: ef_status = "✅"
    elif bank_bal >= ef_min_val: ef_status = "⚠️"
    else: ef_status = "🚨"
    
    ef_ratio = 0.0 if ef_rec_val <= 0 else min(bank_bal / ef_rec_val, 1.0)

    ui_kpi_cards(bank_plan, nisa_plan, goals_plan, free_cash, nisa_reason, ef_status, ef_ratio)
    ui_main_tabs(df_balance, ef, df_goals_prog, df_fi, fi_req, False, df_goals_detail, summary)

if __name__ == "__main__":
    main()
