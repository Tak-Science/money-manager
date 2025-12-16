def get_latest_parameter(df, item, target_date):
    df_item = df[df["項目"] == item].copy()
    if df_item.empty:
        return None

    df_item = df_item.sort_values("適用開始日")
    df_item = df_item[df_item["適用開始日"] <= target_date]

    if df_item.empty:
        return None

    return df_item.iloc[-1]["値"]
#今月サマリー計算ロジック（関数化）
def calculate_monthly_summary(
    df_params, df_fix, df_balance, df_forms, today
):
    current_month = today.strftime("%Y-%m")

    # --- Parameters ---
    monthly_income = get_latest_parameter(df_params, "月収", today)
    target_asset = get_latest_parameter(df_params, "目標資産額", today)

    if monthly_income is None or target_asset is None:
        return None

    # --- 固定費 ---
    active_fix = df_fix[
        (df_fix["開始日"] <= today) &
        ((df_fix["終了日"].isna()) | (df_fix["終了日"] >= today))
    ]
    monthly_fix_cost = active_fix["金額"].sum()

    # --- 変動費 ---
    df_forms["month"] = df_forms["日付"].dt.strftime("%Y-%m")
    monthly_variable_cost = (
        df_forms[df_forms["month"] == current_month]["金額"].sum()
    )

    # --- 現実的積立額 ---
    realistic_save = (
        monthly_income - monthly_fix_cost - monthly_variable_cost
    )
    realistic_save = max(realistic_save, 0)

    # --- 資産履歴 ---
    df_balance = df_balance.sort_values("日付")
    df_balance["total_asset"] = (
        df_balance["銀行残高"] + df_balance["NISA評価額"]
    )

    current_asset = df_balance.iloc[-1]["total_asset"]

    # --- 過去平均との差 ---
    df_balance["monthly_diff"] = df_balance["total_asset"].diff()
    past_avg = df_balance["monthly_diff"].tail(12).mean()
    diff_from_past = realistic_save - past_avg

    # --- 1億円ペース ---
    years_left = 60 - today.year
    months_left = max(years_left * 12, 1)
    ideal_save = (target_asset - current_asset) / months_left
    diff_from_ideal = realistic_save - ideal_save

    return {
        "realistic_save": realistic_save,
        "monthly_income": monthly_income,
        "fix_cost": monthly_fix_cost,
        "variable_cost": monthly_variable_cost,
        "past_avg_diff": diff_from_past,
        "ideal_save": ideal_save,
        "diff_from_ideal": diff_from_ideal
    }
#main() に「今月サマリー」を統合
def main():
    st.title("💰 Financial Freedom Dashboard v5.3")

    df_params, df_fix, df_balance, df_forms, df_goals = load_data()
    df_params, df_fix, df_balance, df_forms, df_goals = preprocess_data(
        df_params, df_fix, df_balance, df_forms, df_goals
    )

    if df_params.empty:
        st.warning("スプレッドシートの読み込みに失敗しました。")
        st.stop()

    today = datetime.today()

    st.header("📊 今月サマリー")

    summary = calculate_monthly_summary(
        df_params, df_fix, df_balance, df_forms, today
    )

    if summary is None:
        st.warning("今月サマリーを計算できません（Parameters を確認してください）")
        return

    # --- UI ---
    st.metric(
        label="現実的な積立額",
        value=f"{int(summary['realistic_save']):,} 円",
        delta=f"{int(summary['past_avg_diff']):,} 円（前年差）"
    )

    st.caption(
        f"※ 1億円ペースとの差：{int(summary['diff_from_ideal']):,} 円"
    )

    with st.expander("内訳・参考情報"):
        st.write(f"月収：{int(summary['monthly_income']):,} 円")
        st.write(f"固定費：{int(summary['fix_cost']):,} 円")
        st.write(f"変動費：{int(summary['variable_cost']):,} 円")
        st.write(f"理想積立額（1億円）：{int(summary['ideal_save']):,} 円 / 月")
