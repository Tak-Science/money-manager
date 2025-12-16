import streamlit as st
import pandas as pd
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import re
from collections import defaultdict

# ==================================================
# Streamlit 設定
# ==================================================
st.set_page_config(page_title="💰 Financial Freedom Dashboard", layout="wide")

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

    return df_params, df_fix, df_forms, df_balance


# ==================================================
# 前処理（最低限：型だけ整える）
# ==================================================
def preprocess_data(df_params, df_fix, df_forms, df_balance):
    # Parameters
    if not df_params.empty:
        if "適用開始日" in df_params.columns:
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

    return df_params, df_fix, df_forms, df_balance


# ==================================================
# Parameters 取得（履歴対応）
# ==================================================
def get_latest_parameter(df, item, target_date):
    if df.empty:
        return None
    if "項目" not in df.columns or "値" not in df.columns or "適用開始日" not in df.columns:
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

    return float(
        d[(d["month"] == current_month) & (d["費目"].isin(EXPENSE_CATEGORIES))]["金額"].sum()
    )


def calculate_monthly_variable_income(df_forms, today):
    if df_forms.empty:
        return 0.0
    if not {"日付", "金額", "費目"}.issubset(set(df_forms.columns)):
        return 0.0

    current_month = today.strftime("%Y-%m")
    d = df_forms.copy()
    d["month"] = d["日付"].dt.strftime("%Y-%m")

    return float(
        d[(d["month"] == current_month) & (d["費目"].isin(INCOME_CATEGORIES))]["金額"].sum()
    )


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

    # maxが未設定なら「available_cash まで」でOKにする
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
        # C: 余剰の範囲で、min〜maxにクリップ
        nisa = max(min(float(available_cash), max_nisa), min_nisa)

    # 余剰が無ければ強制0
    nisa = max(min(float(nisa), float(available_cash)), 0.0)
    return float(nisa), mode


# ==================================================
# 赤字分析（表示で使うキーを統一）
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

    # 3ライン
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
        # 互換（これまで表示で使っていたキー）
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

    # 余剰（赤字なら0）
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
# 資産推移グラフ関数
# ==================================================
import plotly.graph_objects as go

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

    # 銀行残高
    fig.add_trace(go.Scatter(
        x=df["日付"],
        y=df["銀行残高"],
        mode="lines+markers",
        name="🏦 銀行残高"
    ))

    # NISA
    fig.add_trace(go.Scatter(
        x=df["日付"],
        y=df["NISA評価額"],
        mode="lines+markers",
        name="📈 NISA評価額"
    ))

    # 合計資産
    fig.add_trace(go.Scatter(
        x=df["日付"],
        y=df["合計資産"],
        mode="lines+markers",
        name="💰 合計資産",
        line=dict(width=4)
    ))

    # 生活防衛費ライン（推奨）
    fig.add_hline(
        y=ef["fund_rec"],
        line_dash="dash",
        annotation_text="🛡️ 生活防衛費（推奨）",
        annotation_position="top left"
    )

    # 生活防衛費ライン（最低）
    fig.add_hline(
        y=ef["fund_min"],
        line_dash="dot",
        annotation_text="⚠️ 生活防衛費（最低）",
        annotation_position="bottom left"
    )

    fig.update_layout(
        title="📊 資産推移（銀行・NISA・合計）",
        xaxis_title="日付",
        yaxis_title="金額（円）",
        hovermode="x unified",
        height=500
    )

    st.plotly_chart(fig, use_container_width=True)
# ==================================================
# UI
# ==================================================
def main():
    st.title("💰 今月サマリー")

    # データ読み込み（返り値の順番は load_data と一致させる）
    df_params, df_fix, df_forms, df_balance = load_data()
    df_params, df_fix, df_forms, df_balance = preprocess_data(df_params, df_fix, df_forms, df_balance)

    today = datetime.today()

    # 生活防衛費（先に作っておく：NISA調整に使う）
    ef = estimate_emergency_fund(df_params, df_fix, df_forms, today)
    safe_cash = get_latest_bank_balance(df_balance)

    # 今月サマリー
    summary = calculate_monthly_summary(df_params, df_fix, df_forms, df_balance, today)

    # NISA調整（生活防衛費ステータスブレーキ）
    adjusted_nisa, nisa_reason = adjust_nisa_by_emergency_status(
        nisa_amount=summary["nisa_save"],
        safe_cash=safe_cash,
        ef=ef
    )

    bank_save_adjusted = summary["bank_save"] + (summary["nisa_save"] - adjusted_nisa)

    # -------------------------
    # 3つのKPI
    # -------------------------
    col1, col2, col3 = st.columns(3)
    col1.metric("🏦 銀行への積立", f"{int(bank_save_adjusted):,} 円")
    col2.metric(f"📈 NISA積立（モード {summary['nisa_mode']}）", f"{int(adjusted_nisa):,} 円")
    col3.metric("🎉 自由に使えるお金", f"{int(summary['free_cash']):,} 円")

    st.caption(f"生活防衛費ステータスによるNISA調整：{nisa_reason}")
    if summary["available_cash"] <= 0:
        st.caption("※ 今月は収支が赤字のため、積立原資がありません（NISAは 0 円になります）")
    else:
        st.caption(f"※ 今月の積立原資（余剰資金）：{int(summary['available_cash']):,} 円")

    
    st.caption(
        f"月収：{int(summary['monthly_income']):,} 円 "
        f"(固定 {int(summary['base_income']):,} / 臨時 {int(summary['variable_income']):,})"
    )
    st.caption(
        f"固定費：{int(summary['fix_cost']):,} 円 / 変動費：{int(summary['variable_cost']):,} 円"
    )
    st.caption(f"※ 現在資産：{int(summary['current_asset']):,} 円")

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
            st.write(
                f"変動費は想定範囲内です（想定：{int(deficit['var_expected']):,} 円 / 実際：{int(deficit['var_actual']):,} 円）"
            )

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
    # 生活防衛費（自動算出）
    # -------------------------
    st.subheader("🛡️ 生活防衛費（自動算出）")
    c1, c2, c3 = st.columns(3)
    c1.metric("推定 1か月生活費（中央値）", f"{int(ef['monthly_est_median']):,} 円")
    c2.metric("推定 1か月生活費（P75）", f"{int(ef['monthly_est_p75']):,} 円")
    c3.metric(f"係数（{ef['months_factor']}か月分）", f"{ef['months_factor']} か月")

    st.caption(f"算出方法：{ef['method']}")
    st.markdown("**推奨 生活防衛費**")
    st.markdown(f"- 中央値ベース：**{int(ef['fund_median']):,} 円**")
    st.markdown(f"- 保守的（P75）：**{int(ef['fund_p75']):,} 円**")

    # 達成状況
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

        # 参考（P75）
        need_p75 = float(ef["fund_p75"])
        gap_p75 = need_p75 - safe_cash
        if need_p75 > 0:
            if gap_p75 > 0:
                st.caption(f"参考（保守的/P75）：あと {int(gap_p75):,} 円")
            else:
                st.caption(f"参考（保守的/P75）：達成済み（+{int(abs(gap_p75)):,} 円）")

    with st.expander("内訳（月次）を見る"):
        df_view = pd.DataFrame({
            "固定費": ef["series_fix"],
            "変動費": ef["series_var"],
            "合計": ef["series_total"],
        })
        st.dataframe(df_view.style.format("{:,.0f}"), use_container_width=True)

    # ステータス（3段階 + 帯表示）
    st.subheader("🛡️ 生活防衛費ステータス")
    if safe_cash is None:
        st.info("銀行残高が未入力のため、ステータスを表示できません。")
    else:
        f_min = ef["fund_min"]
        f_rec = ef["fund_rec"]
        f_com = ef["fund_comfort"]

        if safe_cash < f_min:
            status, icon = "危険ゾーン", "❌"
        elif safe_cash < f_rec:
            status, icon = "最低限ゾーン", "⚠️"
        elif safe_cash < f_com:
            status, icon = "推奨ゾーン", "✅"
        else:
            status, icon = "安心ゾーン", "🟢"

        st.markdown(
            f"""
**最低**：{int(f_min):,} 円  
**推奨**：{int(f_rec):,} 円  
**安心**：{int(f_com):,} 円  

**現在の安全資金**：{int(safe_cash):,} 円  
**ステータス**：{icon} **{status}**
"""
        )

        max_scale = max(float(f_com), float(safe_cash))
        progress = min(float(safe_cash) / max_scale, 1.0) if max_scale > 0 else 0.0
        st.progress(progress)
        st.caption("帯表示：最低 → 推奨 → 安心 の順に安全度が高まります")
    # ==========================================
    # 資産推移グラフ
    # ==========================================
    st.subheader("📊 資産推移")
    plot_asset_trend(df_balance, ef)
# ==================================================
# 実行
# ==================================================
if __name__ == "__main__":
    main()
