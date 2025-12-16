import streamlit as st
import pandas as pd
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

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
SPREADSHEET_URL = "ここにあなたのGoogleスプレッドシートURL"

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

    try:
        spreadsheet_id = SPREADSHEET_URL.split("/d/")[1].split("/")[0]
    except IndexError:
        st.error("SPREADSHEET_URL が正しくありません")
        st.stop()

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
# 固定費（キャッシュアウト）
# ==================================================
def calculate_monthly_fix_cost(df_fix, today):
    if df_fix.empty:
        return 0

    df = df_fix.copy()
    df["開始日"] = pd.to_datetime(df["開始日"])
    df["終了日"] = pd.to_datetime(df["終了日"], errors="coerce")
    df["金額"] = df["金額"].astype(float)

    active = df[
        (df["開始日"] <= today) &
        ((df["終了日"].isna()) | (df["終了日"] >= today))
    ]

    return active["金額"].sum()

# ==================================================
# 変動費（支出）
# ==================================================
def calculate_monthly_variable_cost(df_forms, today):
    if df_forms.empty:
        return 0

    df = df_forms.copy()
    df["日付"] = pd.to_datetime(df["日付"])
    df["金額"] = df["金額"].astype(float)

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
# 変動収入（臨時収入・バイト代）
# ==================================================
def calculate_monthly_variable_income(df_forms, today):
    if df_forms.empty:
        return 0

    df = df_forms.copy()
    df["日付"] = pd.to_datetime(df["日付"])
    df["金額"] = df["金額"].astype(float)

    current_month = today.strftime("%Y-%m")
    df["month"] = df["日付"].dt.strftime("%Y-%m")

    income_categories = ["給与・バイト代", "臨時収入"]

    return df[
        (df["month"] == current_month) &
        (df["費目"].isin(income_categories))
    ]["金額"].sum()

# ==================================================
# NISA 積立計算（A / B / C）
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
    else:  # モード C
        nisa = max(min(available_cash, max_nisa), min_nisa)

    # ★ 余剰を超えない
    nisa = max(min(nisa, available_cash), 0)

    return nisa, mode

# ==================================================
# 赤字分析（詳細版）
# ==================================================
def analyze_deficit(monthly_income, fix_cost, variable_cost):
    deficit = monthly_income - fix_cost - variable_cost
    if deficit >= 0:
        return None

    deficit_amount = abs(deficit)

    fix_over = fix_cost - monthly_income
    variable_threshold = monthly_income * 0.3
    variable_over = variable_cost - variable_threshold

    if fix_over > 0 and variable_over <= 0:
        cause = "固定費"
    elif variable_over > 0 and fix_over <= 0:
        cause = "変動費"
    else:
        cause = "複合要因"

    return {
        "deficit_amount": deficit_amount,
        "cause": cause,
        "fix_over": fix_over,
        "variable_over": variable_over,
        "variable_threshold": variable_threshold
    }

# ==================================================
# 満足度が低い支出分析
# ==================================================
def analyze_low_satisfaction_expenses(df_forms, today):
    if df_forms.empty:
        return pd.DataFrame()

    df = df_forms.copy()
    df["日付"] = pd.to_datetime(df["日付"])
    df["金額"] = df["金額"].astype(float)
    df["満足度"] = pd.to_numeric(df["満足度"], errors="coerce")

    current_month = today.strftime("%Y-%m")
    df["month"] = df["日付"].dt.strftime("%Y-%m")

    low_df = df[
        (df["month"] == current_month) &
        (df["満足度"] <= 2)
    ]

    if low_df.empty:
        return pd.DataFrame()

    return (
        low_df
        .groupby("費目", as_index=False)
        .agg(
            合計金額=("金額", "sum"),
            回数=("金額", "count"),
            平均満足度=("満足度", "mean")
        )
        .sort_values("合計金額", ascending=False)
    )

# ==================================================
# 今月サマリー計算
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
    df_balance["銀行残高"] = df_balance["銀行残高"].astype(float)
    df_balance["NISA評価額"] = df_balance["NISA評価額"].astype(float)

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
# Streamlit UI
# ==================================================
def main():
    st.title("💰 今月サマリー")

    df_params, df_fix, df_forms, df_balance = load_data()
    today = datetime.today()

    summary = calculate_monthly_summary(
        df_params, df_fix, df_forms, df_balance, today
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("🏦 銀行への積立", f"{int(summary['bank_save']):,} 円")

    with col2:
        st.metric(
            f"📈 NISA積立（モード {summary['nisa_mode']}）",
            f"{int(summary['nisa_save']):,} 円"
        )

    with col3:
        st.metric("🎉 自由に使えるお金", f"{int(summary['free_cash']):,} 円")

    st.caption(
        f"月収：{int(summary['monthly_income']):,} 円 "
        f"(固定 {int(summary['base_income']):,} / 臨時 {int(summary['variable_income']):,})"
    )
    st.caption(
        f"固定費：{int(summary['fix_cost']):,} 円 / "
        f"変動費：{int(summary['variable_cost']):,} 円"
    )
    st.caption(
        f"※ 現在資産：{int(summary['current_asset']):,} 円"
    )

    # 赤字アラート（詳細表示）
    deficit = analyze_deficit(
        summary["monthly_income"],
        summary["fix_cost"],
        summary["variable_cost"]
    )

    if deficit:
        st.warning(
            f"⚠️ 今月は {int(deficit['deficit_amount']):,} 円の赤字です"
        )
        st.markdown("**主な要因：**")

        if deficit["cause"] == "固定費":
            st.markdown(
                f"- 固定費が月収を {int(deficit['fix_over']):,} 円 上回っています"
            )
            st.markdown(
                f"- 今月の変動費：{int(summary['variable_cost']):,} 円"
            )
        elif deficit["cause"] == "変動費":
            st.markdown(
                f"- 今月の変動費が多めです（目安より +{int(deficit['variable_over']):,} 円）"
            )
            st.markdown("- 固定費は想定内です")
        else:
            if deficit["fix_over"] > 0:
                st.markdown(
                    f"- 固定費がやや高めです（+{int(deficit['fix_over']):,} 円）"
                )
            if deficit["variable_over"] > 0:
                st.markdown(
                    f"- 変動費もやや多めです（+{int(deficit['variable_over']):,} 円）"
                )

    # 振り返り
    st.subheader("🧠 今月の振り返り（満足度が低めだった支出）")

    low_df = analyze_low_satisfaction_expenses(df_forms, today)

    if low_df.empty:
        st.success("🎉 今月は満足度の低い支出は特にありませんでした！")
    else:
        st.dataframe(
            low_df.style.format({
                "合計金額": "{:,.0f} 円",
                "平均満足度": "{:.1f}"
            }),
            use_container_width=True
        )

# ==================================================
# 実行
# ==================================================
if __name__ == "__main__":
    main()
