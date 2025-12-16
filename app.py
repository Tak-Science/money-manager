import streamlit as st
import pandas as pd
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ==============================
# 基本設定
# ==============================
st.set_page_config(page_title="💰 Financial Freedom Dashboard", layout="wide")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_URL = "ここにあなたのスプレッドシートURL"

# ==============================
# Google Sheets 接続
# ==============================
def get_spreadsheet():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES
    )
    service = build("sheets", "v4", credentials=creds)
    return service.spreadsheets()


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

    df_params = get_df("Parameters", "A:D")
    df_balance = get_df("Balance_Log", "A:C")

    return df_params, df_balance


# ==============================
# Parameters 取得
# ==============================
def get_latest_parameter(df, item, target_date):
    df = df.copy()
    df["適用開始日"] = pd.to_datetime(df["適用開始日"])
    df = df[df["項目"] == item]
    df = df[df["適用開始日"] <= target_date]

    if df.empty:
        return None

    return df.sort_values("適用開始日").iloc[-1]["値"]


# ==============================
# NISA 積立額計算
# ==============================
def calculate_nisa_amount(
    df_params,
    today,
    available_cash,
    current_asset
):
    mode = get_latest_parameter(df_params, "NISA積立モード", today)

    min_nisa = float(get_latest_parameter(df_params, "NISA最低積立額", today))
    max_nisa = float(get_latest_parameter(df_params, "NISA最大積立額", today))
    target_asset = float(get_latest_parameter(df_params, "目標資産額", today))
    retire_age = float(get_latest_parameter(df_params, "老後年齢", today))

    # 仮の現在年齢（Profile連携は後）
    current_age = 20

    if mode == "A":
        return min_nisa, "A"

    if mode == "B":
        years_left = max(retire_age - current_age, 1)
        months_left = years_left * 12
        ideal = (target_asset - current_asset) / months_left
        nisa = max(min(ideal, max_nisa), min_nisa)
        return nisa, "B"

    # モードC（余剰ベース）
    nisa = max(min(available_cash, max_nisa), min_nisa)
    return nisa, "C"


# ==============================
# 今月サマリー
# ==============================
def calculate_monthly_summary(df_params, df_balance, today):
    monthly_income = float(get_latest_parameter(df_params, "月収", today))

    # 固定費・変動費は今は 0（後で追加）
    fix_cost = 0
    variable_cost = 0

    available_cash = max(monthly_income - fix_cost - variable_cost, 0)

    # 資産
    df_balance = df_balance.copy()
    df_balance["日付"] = pd.to_datetime(df_balance["日付"])
    df_balance["銀行残高"] = df_balance["銀行残高"].astype(float)
    df_balance["NISA評価額"] = df_balance["NISA評価額"].astype(float)

    current_asset = (
        df_balance.sort_values("日付")
        .iloc[-1][["銀行残高", "NISA評価額"]]
        .sum()
    )

    nisa_amount, mode = calculate_nisa_amount(
        df_params,
        today,
        available_cash,
        current_asset
    )

    bank_save = max(available_cash - nisa_amount, 0)
    free_cash = max(available_cash - nisa_amount - bank_save, 0)

    return {
        "bank_save": bank_save,
        "nisa_save": nisa_amount,
        "free_cash": free_cash,
        "nisa_mode": mode,
        "current_asset": current_asset
    }


# ==============================
# Streamlit UI
# ==============================
def main():
    st.title("💰 今月サマリー")

    df_params, df_balance = load_data()
    today = datetime.today()

    summary = calculate_monthly_summary(df_params, df_balance, today)

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

    st.caption(f"※ 現在資産：{int(summary['current_asset']):,} 円")


if __name__ == "__main__":
    main()
