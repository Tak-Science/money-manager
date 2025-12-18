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

    df_params      = get_df("Parameters",      "A:D")
    df_fix         = get_df("Fix_Cost",        "A:G")
    df_forms       = get_df("Forms_Log",       "A:G")
    df_balance     = get_df("Balance_Log",     "A:C")
    df_goals       = get_df("Goals",           "A:F")
    df_goals_save  = get_df("Goals_Save_Log",  "A:C")  # ★追加
    return df_params, df_fix, df_forms, df_balance, df_goals, df_goals_save

# ==================================================
# 前処理（最低限：型だけ整える）
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
    if not df_goals.empty and "達成期限" in df_goals.columns:
        df_goals["達成期限"] = pd.to_datetime(df_goals["達成期限"], errors="coerce")
        if "金額" in df_goals.columns:
            df_goals["金額"] = pd.to_numeric(df_goals["金額"], errors="coerce")
        if "通貨" in df_goals.columns:
            df_goals["通貨"] = df_goals["通貨"].fillna("JPY")

    # Goals_Save_Log
    if not df_goals_save.empty:
        # 想定列：日付 / 実績Goals積立額 / メモ
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
# 生活防衛費（シリーズ）
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
            lambda r: r["金額"] if "毎月" in str(r["サイクル"])
            else (r["金額"] / 12.0 if "毎年" in str(r["サイクル"]) else r["金額"]),
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
# NISA 積立（モード A/B/C）
# ==================================================
def calculate_nisa_amount(df_params, today, available_cash, current_asset):
    mode = get_latest_parameter(df_params, "NISA積立モード", today)
    mode = str(mode).strip() if mode is not None else "C"

    min_nisa = to_float_safe(get_latest_parameter(df_params, "NISA最低積立額", today), default=0.0)
    max_nisa = to_float_safe(get_latest_parameter(df_params, "NISA最大積立額", today), default=0.0)

    # 旧：資産目標（現段階では残しつつ、max未設定対策に使用）
    target_asset = to_float_safe(get_latest_parameter(df_params, "目標資産額", today), default=100_000_000.0)
    retire_age   = to_float_safe(get_latest_parameter(df_params, "老後年齢", today), default=60.0)
    current_age  = to_float_safe(get_latest_parameter(df_params, "現在年齢", today), default=20.0)

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
# Goals：距離分類 & 換算（今回はJPYのみ前提）
# ==================================================
def convert_to_jpy_stub(amount, currency, date=None):
    try:
        a = float(amount)
    except:
        return None
    c = str(currency).strip().upper() if currency is not None else "JPY"
    if c in ["JPY", ""]:
        return a
    # TODO: 為替対応
    return a

def classify_distance_years(years_to_deadline, near_years=2, mid_years=5):
    if years_to_deadline <= near_years:
        return "近距離"
    if years_to_deadline <= mid_years:
        return "中距離"
    return "長距離"

def get_distance_coeffs(df_params, today):
    # 既定（あなたが決めた値）
    near = to_float_safe(get_latest_parameter(df_params, "距離係数_近距離", today), default=1.0)
    mid  = to_float_safe(get_latest_parameter(df_params, "距離係数_中距離", today), default=0.5)
    long = to_float_safe(get_latest_parameter(df_params, "距離係数_長距離", today), default=0.2)

    near_y = to_int_safe(get_latest_parameter(df_params, "距離境界_近距離年数", today), default=2)
    mid_y  = to_int_safe(get_latest_parameter(df_params, "距離境界_中距離年数", today), default=5)

    return {
        "near_years": near_y,
        "mid_years": mid_y,
        "coeff": {"近距離": near, "中距離": mid, "長距離": long},
    }

def get_state_coeff_goals(df_params, today, emergency_unmet: bool):
    # 決定：生活防衛費未達だけ 1.2
    coeff_unmet = to_float_safe(get_latest_parameter(df_params, "状態係数_防衛費未達", today), default=1.2)
    return float(coeff_unmet) if emergency_unmet else 1.0

def compute_goals_planned_pmt_required(df_goals, df_params, today, emergency_unmet: bool, horizon_years=5):
    """
    必須Goals（支出）の月次積立（計画）を計算
      base = 金額 / 残り月数
      近/中/長 距離係数を掛ける
      状態係数（防衛費未達だけ1.2）を掛ける
    """
    if df_goals is None or df_goals.empty:
        return 0.0, pd.DataFrame()

    required_cols = {"目標名", "金額", "通貨", "達成期限", "優先度", "タイプ"}
    if not required_cols.issubset(set(df_goals.columns)):
        return 0.0, pd.DataFrame()

    d = df_goals.copy()
    d = d.dropna(subset=["達成期限", "金額"])
    d = d[d["優先度"].astype(str).str.strip() == "必須"]
    d = d[d["タイプ"].astype(str).str.strip() == "支出"]  # 必須の「支払い」だけ
    if d.empty:
        return 0.0, pd.DataFrame()

    # horizon: 例 5年以内まで積立対象
    horizon_years = to_int_safe(get_latest_parameter(df_params, "Goals積立対象年数", today), default=horizon_years)

    today_m = pd.to_datetime(today).to_period("M")
    d["deadline_m"] = d["達成期限"].dt.to_period("M")
    d = d[d["deadline_m"] >= today_m]

    # 期限が遠すぎるものは積立対象外（あなたの方針）
    horizon_m = (today_m + horizon_years * 12)
    d = d[d["deadline_m"] <= horizon_m]
    if d.empty:
        return 0.0, pd.DataFrame()

    cfg = get_distance_coeffs(df_params, today)
    near_y = cfg["near_years"]
    mid_y  = cfg["mid_years"]
    coeff_map = cfg["coeff"]

    # 残り月数（最低1）
    d["months_left"] = (d["deadline_m"].astype(int) - today_m.astype(int) + 1).clip(lower=1)

    # 年数換算
    d["years_left"] = d["months_left"] / 12.0
    d["distance"] = d["years_left"].apply(lambda y: classify_distance_years(y, near_years=near_y, mid_years=mid_y))
    d["distance_coeff"] = d["distance"].map(coeff_map).fillna(1.0)

    state_coeff = get_state_coeff_goals(df_params, today, emergency_unmet=emergency_unmet)

    # 金額JPY換算
    d["amount_jpy"] = d.apply(lambda r: convert_to_jpy_stub(r["金額"], r["通貨"], r["達成期限"]), axis=1)
    d = d.dropna(subset=["amount_jpy"])
    if d.empty:
        return 0.0, pd.DataFrame()

    d["base_pmt"] = d["amount_jpy"] / d["months_left"]
    d["planned_pmt"] = d["base_pmt"] * d["distance_coeff"] * state_coeff

    # 表示用
    view = d[["目標名", "amount_jpy", "達成期限", "months_left", "distance", "distance_coeff", "base_pmt", "planned_pmt"]].copy()
    total = float(view["planned_pmt"].sum())
    return total, view

# ==================================================
# Goals_Save_Log：今月実績 & 全期間実績
# ==================================================
def get_actual_goals_pmt_for_month(df_goals_save, today):
    if df_goals_save is None or df_goals_save.empty:
        return 0.0
    if not {"日付", "実績Goals積立額"}.issubset(set(df_goals_save.columns)):
        return 0.0

    d = df_goals_save.copy().dropna(subset=["日付"])
    if d.empty:
        return 0.0
    cur_m = today.strftime("%Y-%m")
    d["month"] = d["日付"].dt.strftime("%Y-%m")
    return float(d[d["month"] == cur_m]["実績Goals積立額"].sum())

def build_goals_actual_allocation(
    df_goals,
    df_goals_save,
    df_params,
    today,
    horizon_years=5,
):
    """
    Goals_Save_Logの実績を、必須(支出)Goalsへ「近→中→長」順で配賦し、
    Goal別の累計達成率を作る（案A）。
    """
    if df_goals is None or df_goals.empty:
        return pd.DataFrame()

    required_cols = {"目標名", "金額", "通貨", "達成期限", "優先度", "タイプ"}
    if not required_cols.issubset(set(df_goals.columns)):
        return pd.DataFrame()

    if df_goals_save is None or df_goals_save.empty:
        # 実績がない場合でも、対象Goalsだけは一覧で出せるようにする
        df_goals_save = pd.DataFrame(columns=["日付", "実績Goals積立額"])

    cfg = get_distance_coeffs(df_params, today)
    near_y = cfg["near_years"]
    mid_y  = cfg["mid_years"]

    horizon_years = to_int_safe(get_latest_parameter(df_params, "Goals積立対象年数", today), default=horizon_years)

    # 対象Goals（必須・支出・期限が未来・horizon内）
    g = df_goals.copy()
    g = g.dropna(subset=["達成期限", "金額"])
    g = g[g["優先度"].astype(str).str.strip() == "必須"]
    g = g[g["タイプ"].astype(str).str.strip() == "支出"]
    if g.empty:
        return pd.DataFrame()

    g["amount_jpy"] = g.apply(lambda r: convert_to_jpy_stub(r["金額"], r["通貨"], r["達成期限"]), axis=1)
    g = g.dropna(subset=["amount_jpy"])
    if g.empty:
        return pd.DataFrame()

    today_m = pd.to_datetime(today).to_period("M")
    g["deadline_m"] = g["達成期限"].dt.to_period("M")
    g = g[g["deadline_m"] >= today_m]
    horizon_m = (today_m + horizon_years * 12)
    g = g[g["deadline_m"] <= horizon_m]
    if g.empty:
        return pd.DataFrame()

    # 距離
    g["months_left"] = (g["deadline_m"].astype(int) - today_m.astype(int) + 1).clip(lower=1)
    g["years_left"] = g["months_left"] / 12.0
    g["distance"] = g["years_left"].apply(lambda y: classify_distance_years(y, near_years=near_y, mid_years=mid_y))

    # 配賦優先順：近→中→長、その中で期限が早い順
    dist_order = {"近距離": 0, "中距離": 1, "長距離": 2}
    g["dist_order"] = g["distance"].map(dist_order).fillna(9)
    g = g.sort_values(["dist_order", "達成期限", "目標名"]).reset_index(drop=True)

    # 実績ログ（月順）
    s = df_goals_save.copy()
    if s.empty or not {"日付", "実績Goals積立額"}.issubset(set(s.columns)):
        s = pd.DataFrame(columns=["日付", "実績Goals積立額"])

    s = s.dropna(subset=["日付"]).sort_values("日付")
    if s.empty:
        # 実績がない → 累計0
        out = g[["目標名", "amount_jpy", "達成期限", "distance"]].copy()
        out["allocated_to_date"] = 0.0
        out["achievement_rate"] = 0.0
        out["remaining"] = out["amount_jpy"]
        return out

    # Goalごとの累計配賦
    allocated = {name: 0.0 for name in g["目標名"].tolist()}
    target = {row["目標名"]: float(row["amount_jpy"]) for _, row in g.iterrows()}

    for _, r in s.iterrows():
        amt = float(r.get("実績Goals積立額", 0.0))
        if amt <= 0:
            continue

        remaining_amt = amt
        for _, gr in g.iterrows():
            name = gr["目標名"]
            need = max(target[name] - allocated[name], 0.0)
            if need <= 0:
                continue
            use = min(need, remaining_amt)
            allocated[name] += use
            remaining_amt -= use
            if remaining_amt <= 1e-9:
                break
        # 余った分は「必須以外」へ行ってる想定だが、ここでは追わない（要件通り）

    out = g[["目標名", "amount_jpy", "達成期限", "distance"]].copy()
    out["allocated_to_date"] = out["目標名"].map(lambda x: float(allocated.get(x, 0.0)))
    out["achievement_rate"] = out.apply(lambda r: 0.0 if r["amount_jpy"] <= 0 else min(r["allocated_to_date"] / r["amount_jpy"], 1.0), axis=1)
    out["remaining"] = (out["amount_jpy"] - out["allocated_to_date"]).clip(lower=0.0)
    return out

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
# 直近6か月の平均積立推定（既存）
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
# 今月サマリー（★Goals積立を優先で組み込み）
# ==================================================
def calculate_monthly_summary_with_goals(
    df_params, df_fix, df_forms, df_balance, df_goals, df_goals_save,
    today, ef, safe_cash
):
    base_income = to_float_safe(get_latest_parameter(df_params, "月収", today), default=0.0)
    variable_income = calculate_monthly_variable_income(df_forms, today)
    monthly_income = base_income + variable_income

    fix_cost = calculate_monthly_fix_cost(df_fix, today)
    variable_cost = calculate_monthly_variable_cost(df_forms, today)

    # 余剰（赤字なら0）
    available_cash = max(monthly_income - fix_cost - variable_cost, 0.0)

    # --- Goals（計画）
    emergency_unmet = (safe_cash is not None) and (safe_cash < ef["fund_rec"])
    goals_plan, goals_plan_view = compute_goals_planned_pmt_required(
        df_goals=df_goals,
        df_params=df_params,
        today=today,
        emergency_unmet=emergency_unmet,
        horizon_years=5
    )
    goals_plan = max(float(goals_plan), 0.0)

    # Goalsは余剰の範囲で優先（不足したらその月はそこまで）
    goals_save = min(goals_plan, available_cash)
    remaining_after_goals = max(available_cash - goals_save, 0.0)

    current_asset = get_latest_total_asset(df_balance)

    # --- NISAは「Goals後の残り」から計算
    nisa_amount_raw, nisa_mode = calculate_nisa_amount(df_params, today, remaining_after_goals, current_asset)

    # --- 防衛費ブレーキでNISA調整
    adjusted_nisa, nisa_reason = adjust_nisa_by_emergency_status(
        nisa_amount=nisa_amount_raw,
        safe_cash=safe_cash,
        ef=ef
    )

    # --- 銀行積立は残り全部（NISAの差分も銀行へ）
    bank_save = max(remaining_after_goals - adjusted_nisa, 0.0)

    # 自由資金（マイナスなら0表示）
    free_cash = max(available_cash - goals_save - bank_save - adjusted_nisa, 0.0)

    # Goals実績（今月入力）
    actual_goals_pmt = get_actual_goals_pmt_for_month(df_goals_save, today)

    return {
        "monthly_income": float(monthly_income),
        "base_income": float(base_income),
        "variable_income": float(variable_income),
        "fix_cost": float(fix_cost),
        "variable_cost": float(variable_cost),

        "available_cash": float(available_cash),

        "goals_plan": float(goals_plan),
        "goals_save": float(goals_save),
        "goals_plan_view": goals_plan_view,
        "actual_goals_pmt": float(actual_goals_pmt),

        "nisa_save": float(adjusted_nisa),
        "nisa_mode": str(nisa_mode),
        "nisa_reason": str(nisa_reason),

        "bank_save": float(bank_save),
        "free_cash": float(free_cash),

        "current_asset": float(current_asset),
        "emergency_unmet": bool(emergency_unmet),
    }

# ==================================================
# 円グラフ（残り内訳）
# ==================================================
def plot_goals_remaining_pie(df_alloc):
    if df_alloc is None or df_alloc.empty:
        st.info("必須Goalsが無いか、データが不足しています。")
        return
    d = df_alloc.copy()
    d = d[d["remaining"] > 0]
    if d.empty:
        st.success("🎉 必須Goalsはすべて達成済みです！")
        return

    fig = go.Figure(
        data=[
            go.Pie(
                labels=d["目標名"],
                values=d["remaining"],
                hole=0.45
            )
        ]
    )
    fig.update_layout(
        title="🥧 必須Goals（支出）の残り金額内訳",
        height=420
    )
    st.plotly_chart(fig, use_container_width=True)

# ==================================================
# UI
# ==================================================
def main():
    st.title("💰 今月サマリー")

    df_params, df_fix, df_forms, df_balance, df_goals, df_goals_save = load_data()
    df_params, df_fix, df_forms, df_balance, df_goals, df_goals_save = preprocess_data(
        df_params, df_fix, df_forms, df_balance, df_goals, df_goals_save
    )

    today = datetime.today()

    # 生活防衛費（先）
    ef = estimate_emergency_fund(df_params, df_fix, df_forms, today)
    safe_cash = get_latest_bank_balance(df_balance)

    # サマリー（Goals込み）
    summary = calculate_monthly_summary_with_goals(
        df_params, df_fix, df_forms, df_balance, df_goals, df_goals_save,
        today, ef, safe_cash
    )

    # -------------------------
    # KPI（4+2：6枚）
    # -------------------------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🎯 Goals積立（計画・必須）", f"{int(summary['goals_save']):,} 円")
    c2.metric("🏦 銀行への積立", f"{int(summary['bank_save']):,} 円")
    c3.metric(f"📈 NISA積立（モード {summary['nisa_mode']}）", f"{int(summary['nisa_save']):,} 円")
    c4.metric("🎉 自由に使えるお金", f"{int(summary['free_cash']):,} 円")

    d1, d2 = st.columns(2)
    d1.metric("🧾 今月のGoals実績（入力値）", f"{int(summary['actual_goals_pmt']):,} 円")

    # 必須Goalsの全期間達成率（平均ではなく「総額ベース」で出す）
    df_alloc = build_goals_actual_allocation(df_goals, df_goals_save, df_params, today, horizon_years=5)
    if df_alloc is None or df_alloc.empty:
        overall_rate = 0.0
        overall_txt = "0%"
    else:
        total_target = float(df_alloc["amount_jpy"].sum())
        total_alloc  = float(df_alloc["allocated_to_date"].sum())
        overall_rate = 0.0 if total_target <= 0 else min(total_alloc / total_target, 1.0)
        overall_txt = f"{int(overall_rate*100)} %"
    d2.metric("✅ 必須Goals 達成率（総額ベース）", overall_txt)

    # -------------------------
    # キャプション類
    # -------------------------
    st.caption(f"生活防衛費ステータス連動：{summary['nisa_reason']}")
    st.caption(
        f"月収：{int(summary['monthly_income']):,} 円（固定 {int(summary['base_income']):,} / 臨時 {int(summary['variable_income']):,}）"
    )
    st.caption(f"固定費：{int(summary['fix_cost']):,} 円 / 変動費：{int(summary['variable_cost']):,} 円")
    st.caption(f"※ 今月の積立原資（余剰資金）：{int(summary['available_cash']):,} 円（赤字なら0）")
    st.caption(f"※ 現在資産：{int(summary['current_asset']):,} 円")

    if summary["goals_plan"] > 0:
        st.caption(
            f"Goals積立（計画・必須/5年以内）：{int(summary['goals_plan']):,} 円 / 月"
            + ("（生活防衛費未達のため状態係数が適用）" if summary["emergency_unmet"] else "")
        )

    # -------------------------
    # 赤字分析
    # -------------------------
    deficit = analyze_deficit(summary["monthly_income"], summary["fix_cost"], summary["variable_cost"])
    if deficit is not None:
        st.warning(f"⚠️ 今月は {int(deficit['total_deficit']):,} 円の赤字です（積立原資は0円扱い）")

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

    # -------------------------
    # メモ×カテゴリ×金額
    # -------------------------
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

    # -------------------------
    # 最近増えている費目
    # -------------------------
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

    with st.expander("内訳（月次）を見る"):
        df_ef_view = pd.DataFrame({
            "固定費": ef["series_fix"],
            "変動費": ef["series_var"],
            "合計":  ef["series_total"],
        }).apply(pd.to_numeric, errors="coerce").fillna(0)
        st.dataframe(df_ef_view.style.format("{:,.0f}"), use_container_width=True)

    # -------------------------
    # 資産推移
    # -------------------------
    st.subheader("📊 資産推移")
    plot_asset_trend(df_balance, ef)

    # -------------------------
    # Goals：計画内訳 & 実績達成（トグル）
    # -------------------------
    st.subheader("🎯 Goals積立（必須・支出）")

    with st.expander("📌 詳細（計画内訳 / 実績達成率 / 円グラフ）を見る"):
        # 計画内訳
        st.markdown("### 🧮 計画（今月の積立額の内訳）")
        if summary["goals_plan_view"] is None or summary["goals_plan_view"].empty:
            st.info("必須Goals（支出）が無いか、5年以内の対象がありません。")
        else:
            v = summary["goals_plan_view"].copy()
            v = v.rename(columns={
                "目標名": "目標名",
                "amount_jpy": "目標金額",
                "達成期限": "期限",
                "months_left": "残り月数",
                "distance": "距離",
                "distance_coeff": "距離係数",
                "base_pmt": "素の積立/月",
                "planned_pmt": "計画積立/月"
            })
            v["期限"] = pd.to_datetime(v["期限"]).dt.strftime("%Y-%m-%d")
            st.dataframe(
                v.style.format({
                    "目標金額": "{:,.0f}",
                    "素の積立/月": "{:,.0f}",
                    "計画積立/月": "{:,.0f}",
                    "距離係数": "{:.2f}",
                }),
                use_container_width=True
            )

        # 実績達成
        st.markdown("### ✅ 実績（累計達成率：案A=近→中→長で配賦）")
        if df_alloc is None or df_alloc.empty:
            st.info("必須Goalsが無いか、実績ログがまだありません。")
        else:
            df_show = df_alloc.copy()
            df_show["期限"] = pd.to_datetime(df_show["達成期限"]).dt.strftime("%Y-%m-%d")
            df_show["達成率(%)"] = (df_show["achievement_rate"] * 100).round(0).astype(int)
            df_show = df_show.rename(columns={
                "目標名": "目標名",
                "amount_jpy": "目標金額",
                "allocated_to_date": "累計積立",
                "remaining": "残り",
                "distance": "距離",
            })
            df_show = df_show[["距離", "期限", "目標名", "目標金額", "累計積立", "残り", "達成率(%)"]]
            st.dataframe(
                df_show.style.format({
                    "目標金額": "{:,.0f}",
                    "累計積立": "{:,.0f}",
                    "残り": "{:,.0f}",
                }),
                use_container_width=True
            )

            # 円グラフ：残り内訳
            st.markdown("### 🥧 円グラフ（残り金額の内訳）")
            plot_goals_remaining_pie(df_alloc)

    st.caption("※ Goals_Save_Log は月1回入力でOK。入力した実績を、必須Goalsへ自動で配賦して累計達成率を作ります。")

# ==================================================
# 実行
# ==================================================
if __name__ == "__main__":
    main()
