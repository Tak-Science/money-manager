#mainの設定（Streamlit側のUI設定）
def main():
    st.title("💰 今月サマリー")

    summary = calculate_monthly_summary(df_params, today)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("🏦 銀行への積立", f"{summary['bank_save']:,} 円")

    with col2:
        st.metric(
            f"📈 NISA積立（モード {summary['nisa_mode']}）",
            f"{summary['nisa_save']:,} 円"
        )

    with col3:
        st.metric("🎉 自由に使えるお金", f"{summary['free_money']:,} 円")

    if summary["ideal_nisa"] > 0:
        st.caption(
            f"※ 1億円ペースの理想NISA積立：{summary['ideal_nisa']:,} 円 / 月"
        )
        st.caption(
    f"※ 現在資産：{summary['current_asset']:,} 円 / "
    f"理想資産：{summary['ideal_asset_today']:,} 円 "
    f"（差分 {summary['asset_gap']:,} 円）"
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
    
def calculate_monthly_summary(df_params, today):
    # --- ダミー収支（後で差し替え） ---
    monthly_income = 300_000
    fix_cost = 150_000
    variable_cost = 60_000

    surplus = max(monthly_income - fix_cost - variable_cost, 0)

    # --- Parameters から取得 ---
    nisa_mode = get_latest_parameter(df_params, "NISA積立モード", today)
    nisa_min = int(get_latest_parameter(df_params, "NISA最低積立額", today))
    nisa_max = int(get_latest_parameter(df_params, "NISA最大積立額", today))

    # --- 理想NISA（仮） ---
    ideal_nisa = 90_000

    nisa_save, ideal_nisa_save = calculate_nisa_save(
        nisa_mode, surplus, nisa_min, nisa_max, ideal_nisa
    )
    surplus -= nisa_save

    # --- 銀行積立（仮） ---
    bank_save = min(20_000, surplus)
    surplus -= bank_save

    free_money = surplus

    # --- 資産（ダミー） ---
    current_asset = 3_000_000
    ideal_asset_today = 3_500_000
    asset_gap = current_asset - ideal_asset_today

    return {
        "bank_save": bank_save,
        "nisa_save": nisa_save,
        "ideal_nisa": ideal_nisa_save,
        "free_money": free_money,
        "nisa_mode": nisa_mode,
        "current_asset": current_asset,
        "ideal_asset_today": ideal_asset_today,
        "asset_gap": asset_gap
    }

#NISAの積立額を決める関数
def calculate_nisa_save(
    mode,
    surplus,
    min_save,
    max_save,
    ideal_save=None
):
    """
    mode: 'A', 'B', 'C'
    surplus: 今月の余剰資金
    min_save: NISA最低積立額
    max_save: NISA最大積立額
    ideal_save: 1億円逆算の理想積立額（B用）
    """

    if surplus <= 0:
        return 0, 0  # 実際, 理想

    # --- A：毎月固定 ---
    if mode == "A":
        actual = min(min_save, surplus)
        return actual, actual

    # --- C：余剰連動 ---
    if mode == "C":
        actual = min(max(min_save, surplus), max_save)
        return actual, actual

    # --- B：1億円逆算（表示用） ---
    if mode == "B":
        ideal = ideal_save if ideal_save else 0
        actual = min(max(min_save, surplus), max_save)
        return actual, ideal

    # フォールバック
    actual = min(min_save, surplus)
    return actual, actual

if __name__ == "__main__":
    main()












