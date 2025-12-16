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
st.set_page_config(
    page_title="💰 Financial Freedom Dashboard",
    layout="wide"
)

# ==================================================
# Google Sheets 設定
# ==================================================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1pb1IH1twG9XDIo6Ma88XKcndnnet-dlHxQPu9zjbJ5w/edit?gid=2102244245#gid=2102244245"

# ==================================================
# Google Sheets 接続
# ==================================================
def get_spreadsheet():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES
    )
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
        res = sheet.values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!{range_}"
        ).execute()
        values = res.get("values", [])
        if not values:
            return pd.DataFrame()
        return pd.DataFrame(values[1:], columns=values[0])

    df_params  = get_df("Parameters",  "A:D")
    df_fix     = get_df("Fix_Cost",    "A:G")
    df_forms   = get_df("Forms_Log",   "A:G")
    df_balance = get_df("Balance_Log", "A:C")

    return df_params, df_fix, df_forms, df_balance

# ==================================================
# Parameters 取得（履歴対応）
# ==================================================
def get_latest_parameter(df, item, target_date):
    if df.empty:
        return None

    df = df.copy()
    df["適用開始日"] = pd.to_datetime(df["適用開始日"], errors="coerce")
    df = df[df["項目"] == item]
    df = df[df["適用開始日"] <= target_date]

    if df.empty:
        return None

    return df.sort_values("適用開始日").iloc[-1]["値"]

# ==================================================
# 固定費
# ==================================================
def calculate_monthly_fix_cost(df_fix, today):
    if df_fix.empty:
        return 0

    df = df_fix.copy()
    df["開始日"] = pd.to_datetime(df["開始日"])
    df["終了日"] = pd.to_datetime(df["終了日"], errors="coerce")
    df["金額"] = pd.to_numeric(df["金額"], errors="coerce")

    active = df[
        (df["開始日"] <= today) &
        ((df["終了日"].isna()) | (df["終了日"] >= today))
    ]

    return active["金額"].sum()

# ==================================================
# 変動費
# ==================================================
def calculate_monthly_variable_cost(df_forms, today):
    if df_forms.empty:
        return 0

    df = df_forms.copy()
    df["日付"] = pd.to_datetime(df["日付"])
    df["金額"] = pd.to_numeric(df["金額"], errors="coerce")

    current_month = today.strftime("%Y-%m")
    df["month"] = df["日付"].dt.strftime("%Y-%m")

    expense_categories = [
        "食費（外食・交際）",
        "食費（日常）",
        "趣味・娯楽",
        "研究・書籍",
        "日用品",
        "交通費",
        "その他"
    ]

    return df[
        (df["month"] == current_month) &
        (df["費目"].isin(expense_categories))
    ]["金額"].sum()

# ==================================================
# 変動収入
# ==================================================
def calculate_monthly_variable_income(df_forms, today):
    if df_forms.empty:
        return 0

    df = df_forms.copy()
    df["日付"] = pd.to_datetime(df["日付"])
    df["金額"] = pd.to_numeric(df["金額"], errors="coerce")

    current_month = today.strftime("%Y-%m")
    df["month"] = df["日付"].dt.strftime("%Y-%m")

    income_categories = ["給与・バイト代", "臨時収入"]

    return df[
        (df["month"] == current_month) &
        (df["費目"].isin(income_categories))
    ]["金額"].sum()

# ==================================================
# NISA 積立計算
# ==================================================
def calculate_nisa_amount(df_params, today, available_cash, current_asset):
    mode = get_latest_parameter(df_params, "NISA積立モード", today)

    min_nisa = float(get_latest_parameter(df_params, "NISA最低積立額", today))
    max_nisa = float(get_latest_parameter(df_params, "NISA最大積立額", today))
    target_asset = float(get_latest_parameter(df_params, "目標資産額", today))
    retire_age = float(get_latest_parameter(df_params, "老後年齢", today))

    current_age = 20  # 仮（Profile 未導入）

    if mode == "A":
        nisa = min_nisa
    elif mode == "B":
        years_left = max(retire_age - current_age, 1)
        months_left = years_left * 12
        ideal = (target_asset - current_asset) / months_left
        nisa = max(min(ideal, max_nisa), min_nisa)
    else:
        nisa = max(min(available_cash, max_nisa), min_nisa)

    return max(min(nisa, available_cash), 0), mode

# ==================================================
# 赤字分析
# ==================================================
def analyze_deficit(monthly_income, fix_cost, variable_cost):
    deficit = monthly_income - fix_cost - variable_cost
    if deficit >= 0:
        return None

    variable_expected = monthly_income * 0.3

    return {
        "deficit_amount": abs(deficit),
        "fix_over": fix_cost - monthly_income,
        "variable_over": variable_cost - variable_expected,
        "variable_expected": variable_expected
    }

# ==================================================
# メモ頻出分析（強化版）
# ==================================================
def analyze_memo_frequency_advanced(
    df_forms, today, is_deficit, variable_cost, monthly_income, top_n=5
):
    variable_expected = monthly_income * 0.3
    if not is_deficit and variable_cost <= variable_expected:
        return []

    df = df_forms.copy()
    df["日付"] = pd.to_datetime(df["日付"])
    df["金額"] = pd.to_numeric(df["金額"], errors="coerce")
    df["満足度"] = pd.to_numeric(df["満足度"], errors="coerce")

    current_month = today.strftime("%Y-%m")
    df["month"] = df["日付"].dt.strftime("%Y-%m")

    target = df[
        (df["month"] == current_month) &
        (df["満足度"] <= 2) &
        (df["メモ"].notna())
    ]

    if target.empty:
        return []

    memo_stats = defaultdict(lambda: {"count": 0, "amount": 0})

    for _, row in target.iterrows():
        words = re.findall(r"[一-龥ぁ-んァ-ンA-Za-z0-9]+", str(row["メモ"]))
        for w in words:
            memo_stats[w]["count"] += 1
            memo_stats[w]["amount"] += row["金額"]

    result = [
        (word, v["count"], v["amount"])
        for word, v in memo_stats.items()
    ]

    result.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return result[:top_n]
    
def analyze_memo_by_category(
    df_forms,
    today,
    is_deficit,
    variable_cost,
    monthly_income
):
    # 赤字 or 変動費想定超過でなければ表示しない
    variable_expected = monthly_income * 0.3
    if not is_deficit and variable_cost <= variable_expected:
        return {}

    df = df_forms.copy()
    df["日付"] = pd.to_datetime(df["日付"])
    df["金額"] = pd.to_numeric(df["金額"], errors="coerce")
    df["満足度"] = pd.to_numeric(df["満足度"], errors="coerce")

    current_month = today.strftime("%Y-%m")
    df["month"] = df["日付"].dt.strftime("%Y-%m")

    target = df[
        (df["month"] == current_month) &
        (df["満足度"] <= 2) &
        (df["メモ"].notna())
    ]

    if target.empty:
        return {}

    result = {}

    for _, row in target.iterrows():
        category = row["費目"]
        memo = row["メモ"]

        if category not in result:
            result[category] = {}

        if memo not in result[category]:
            result[category][memo] = {
                "count": 0,
                "amount": 0
            }

        result[category][memo]["count"] += 1
        result[category][memo]["amount"] += row["金額"]

    return result
    
def analyze_category_trend_3m(df_forms, today):
    if df_forms.empty:
        return []

    df = df_forms.copy()
    df["日付"] = pd.to_datetime(df["日付"])
    df["金額"] = pd.to_numeric(df["金額"], errors="coerce")

    expense_categories = [
        "食費（外食・交際）",
        "食費（日常）",
        "趣味・娯楽",
        "研究・書籍",
        "日用品",
        "交通費",
        "その他"
    ]

    df = df[df["費目"].isin(expense_categories)]

    df["month"] = df["日付"].dt.to_period("M").astype(str)
    current_month = today.strftime("%Y-%m")

    # 直近4か月（当月＋過去3）
    months = pd.period_range(
        end=pd.Period(current_month, freq="M"),
        periods=4,
        freq="M"
    ).astype(str)

    df = df[df["month"].isin(months)]

    if df.empty:
        return []

    pivot = (
        df.groupby(["month", "費目"], as_index=False)["金額"]
        .sum()
        .pivot(index="費目", columns="month", values="金額")
        .fillna(0)
    )

    if current_month not in pivot.columns:
        return []

    # ★ 実際に存在する過去月だけを使う
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
            "current": row[current_month],
            "past_avg": row["past_3m_avg"],
            "diff": row["diff"]
        })

    return result
# ==================================================
# 今月サマリー
# ==================================================
def calculate_monthly_summary(df_params, df_fix, df_forms, df_balance, today):
    base_income = float(get_latest_parameter(df_params, "月収", today))
    variable_income = calculate_monthly_variable_income(df_forms, today)
    monthly_income = base_income + variable_income

    fix_cost = calculate_monthly_fix_cost(df_fix, today)
    variable_cost = calculate_monthly_variable_cost(df_forms, today)

    available_cash = max(monthly_income - fix_cost - variable_cost, 0)

    df_balance = df_balance.copy()
    df_balance["日付"] = pd.to_datetime(df_balance["日付"])
    df_balance["銀行残高"] = pd.to_numeric(df_balance["銀行残高"])
    df_balance["NISA評価額"] = pd.to_numeric(df_balance["NISA評価額"])

    current_asset = (
        df_balance.sort_values("日付")
        .iloc[-1][["銀行残高", "NISA評価額"]]
        .sum()
    )

    nisa_amount, nisa_mode = calculate_nisa_amount(
        df_params, today, available_cash, current_asset
    )

    bank_save = max(available_cash - nisa_amount, 0)

    return {
        "monthly_income": monthly_income,
        "base_income": base_income,
        "variable_income": variable_income,
        "fix_cost": fix_cost,
        "variable_cost": variable_cost,
        "bank_save": bank_save,
        "nisa_save": nisa_amount,
        "free_cash": max(available_cash - bank_save - nisa_amount, 0),
        "nisa_mode": nisa_mode,
        "current_asset": current_asset
    }

# ==================================================
# UI
# ==================================================
def main():
    st.title("💰 今月サマリー")

    df_params, df_fix, df_forms, df_balance = load_data()
    today = datetime.today()

    summary = calculate_monthly_summary(
        df_params, df_fix, df_forms, df_balance, today
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("🏦 銀行への積立", f"{int(summary['bank_save']):,} 円")
    col2.metric(
        f"📈 NISA積立（モード {summary['nisa_mode']}）",
        f"{int(summary['nisa_save']):,} 円"
    )
    col3.metric("🎉 自由に使えるお金", f"{int(summary['free_cash']):,} 円")

    st.caption(
        f"月収：{int(summary['monthly_income']):,} 円 "
        f"(固定 {int(summary['base_income']):,} / 臨時 {int(summary['variable_income']):,})"
    )
    st.caption(
        f"固定費：{int(summary['fix_cost']):,} 円 / "
        f"変動費：{int(summary['variable_cost']):,} 円"
    )
    st.caption(f"※ 現在資産：{int(summary['current_asset']):,} 円")

    deficit = analyze_deficit(
        summary["monthly_income"],
        summary["fix_cost"],
        summary["variable_cost"]
    )

    if deficit:
        st.warning(f"⚠️ 今月は {int(deficit['deficit_amount']):,} 円の赤字です")
        st.markdown("**主な要因：**")

        if deficit["fix_over"] > 0:
            st.markdown(
                f"- 固定費が月収を {int(deficit['fix_over']):,} 円 上回っています"
            )

        st.markdown(
            f"- 変動費は想定範囲内です  \n"
            f"（想定：{int(deficit['variable_expected']):,} 円 / "
            f"実際：{int(summary['variable_cost']):,} 円）"
        )

    st.subheader("🧠 今月の振り返り（メモ分析）")

    memo = analyze_memo_frequency_advanced(
        df_forms,
        today,
        deficit is not None,
        summary["variable_cost"],
        summary["monthly_income"]
    )

    if not memo:
        st.success("🎉 気になる頻出メモは特にありませんでした！")
    else:
        st.markdown("**控え候補として気になるもの：**")
        for word, count, amount in memo:
            st.markdown(
                f"- **{word}**（{count} 回 / 合計 {int(amount):,} 円）"
            )
    # ==========================================
    # メモ × カテゴリ × 金額 分析
    # ==========================================
    st.subheader("📂 控え候補の内訳（カテゴリ別）")

    category_analysis = analyze_memo_by_category(
        df_forms,
        today,
        deficit is not None,
        summary["variable_cost"],
        summary["monthly_income"]
    )

    if not category_analysis:
        st.info("カテゴリ別に見直す必要のある支出は特にありませんでした")
    else:
        for category, memos in category_analysis.items():
            st.markdown(f"**費目：{category}**")

            for memo, stats in memos.items():
                st.markdown(
                    f"- {memo}：{stats['count']} 回 / "
                    f"合計 {int(stats['amount']):,} 円"
                )
    # ==========================================
    # 変動費の増加トレンド（直近3か月比較）
    # ==========================================
    st.subheader("📈 最近増えている費目（直近月 vs 過去3か月平均）")

    trend = analyze_category_trend_3m(df_forms, today)

    if not trend:
        st.info("最近増えている費目は特にありませんでした")
    else:
        for item in trend:
            st.markdown(
                f"- **{item['category']}**："
                f"今月 {int(item['current']):,} 円 / "
                f"過去平均 {int(item['past_avg']):,} 円 "
                f"（**+{int(item['diff']):,} 円**）"
            )
# ==================================================
# 実行
# ==================================================
if __name__ == "__main__":
    main()

