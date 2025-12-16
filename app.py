#mainの設定（Streamlit側のUI設定）
def main():
    st.title("💰 今月サマリー")

    summary = calculate_monthly_summary_dummy()

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("🏦 銀行への積立", f"{summary['bank_save']:,} 円")

    with col2:
        st.metric(
            "📈 NISA積立",
            f"{summary['nisa_save']:,} 円",
            delta=f"{summary['diff_from_past']:,} 円（前年差）"
        )

    with col3:
        st.metric("🎉 自由に使えるお金", f"{summary['free_money']:,} 円")

    st.caption(
        f"※ 1億円ペースとの差：{summary['diff_from_ideal']:,} 円"
    )

#imports & ページ設定
import streamlit as st
import pandas as pd
from datetime import datetime
st.set_page_config(
    page_title="Financial Freedom Dashboard",
    layout="wide"
)
#前処理
def preprocess_data(df_params, df_fix, df_balance, df_forms):
    for df, col in [
        (df_params, "適用開始日"),
        (df_fix, "開始日"),
        (df_fix, "終了日"),
        (df_balance, "日付"),
        (df_forms, "日付"),
    ]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    for df, col in [
        (df_params, "値"),
        (df_fix, "金額"),
        (df_forms, "金額"),
        (df_balance, "銀行残高"),
        (df_balance, "NISA評価額"),
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    return df_params, df_fix, df_balance, df_forms
#Parameters 取得関数
def get_latest_parameter(df, item, target_date):
    df_item = df[df["項目"] == item]
    df_item = df_item[df_item["適用開始日"] <= target_date]

    if df_item.empty:
        return None

    return df_item.sort_values("適用開始日").iloc[-1]["値"]
#今月サマリー計算
def calculate_monthly_summary(df_params, df_fix, df_balance, df_forms, today):
    month = today.strftime("%Y-%m")

    # --- Parameters ---
    income = get_latest_parameter(df_params, "月収", today)
    current_age = get_latest_parameter(df_params, "現在年齢", today)
    retire_age = get_latest_parameter(df_params, "老後年齢", today)
    target_asset = get_latest_parameter(df_params, "目標資産額", today)
    bank_ratio = get_latest_parameter(df_params, "銀行積立割合", today)
    nisa_ratio = get_latest_parameter(df_params, "NISA積立割合", today)

    if None in [
        income, current_age, retire_age,
        target_asset, bank_ratio, nisa_ratio
    ]:
        return None

    # --- 固定費 ---
    active_fix = df_fix[
        (df_fix["開始日"] <= today) &
        ((df_fix["終了日"].isna()) | (df_fix["終了日"] >= today))
    ]
    fix_cost = active_fix["金額"].sum()

    # --- 変動費 ---
    df_forms["month"] = df_forms["日付"].dt.strftime("%Y-%m")
    variable_cost = df_forms[df_forms["month"] == month]["金額"].sum()

    # --- 余剰 ---
    surplus = max(income - fix_cost - variable_cost, 0)

    # --- 配分 ---
    bank_save = surplus * bank_ratio
    nisa_save = surplus * nisa_ratio
    free_money = surplus - bank_save - nisa_save

    # --- 資産 ---
    df_balance = df_balance.sort_values("日付")
    df_balance["total"] = df_balance["銀行残高"] + df_balance["NISA評価額"]
    current_asset = df_balance.iloc[-1]["total"]

    # --- 1億円ペース ---
    months_left = max((retire_age - current_age) * 12, 1)
    ideal_save = (target_asset - current_asset) / months_left
    diff_from_ideal = (bank_save + nisa_save) - ideal_save

    return {
        "bank_save": bank_save,
        "nisa_save": nisa_save,
        "free_money": free_money,
        "ideal_save": ideal_save,
        "diff_from_ideal": diff_from_ideal,
        "income": income,
        "fix_cost": fix_cost,
        "variable_cost": variable_cost,
    }
def calculate_monthly_summary_dummy():
    # --- ダミー値 ---
    monthly_income = 300_000
    fix_cost = 150_000
    variable_cost = 60_000

    nisa_target = 33_000
    bank_target = 20_000

    # --- 計算 ---
    surplus = monthly_income - fix_cost - variable_cost
    surplus = max(surplus, 0)

    nisa_save = min(nisa_target, surplus)
    surplus -= nisa_save

    bank_save = min(bank_target, surplus)
    surplus -= bank_save

    free_money = surplus

    # --- 差分（ダミー） ---
    diff_from_past = 5_000
    diff_from_ideal = -30_000

    return {
        "bank_save": bank_save,
        "nisa_save": nisa_save,
        "free_money": free_money,
        "diff_from_past": diff_from_past,
        "diff_from_ideal": diff_from_ideal
    }



if __name__ == "__main__":
    main()



