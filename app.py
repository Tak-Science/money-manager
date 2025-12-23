import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go

# 作成したモジュールをインポート
import config
import data_loader as dl
import logic as lg

# ==================================================
# Streamlit 設定
# ==================================================
st.set_page_config(page_title="💰 Financial Freedom Dashboard", layout="wide")

# ==================================================
# グラフ描画関数
# ==================================================
def plot_asset_trend(df_balance, ef):
    if df_balance is None or df_balance.empty:
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

    fig.add_hline(y=float(ef["fund_rec"]), line_dash="dash", annotation_text="🛡️ 生活防衛費（推奨）", annotation_position="top left")
    fig.add_hline(y=float(ef["fund_min"]), line_dash="dot", annotation_text="⚠️ 生活防衛費（最低）", annotation_position="bottom left")

    fig.update_layout(
        title="📊 資産推移（銀行・NISA・合計）",
        xaxis_title="日付",
        yaxis_title="金額（円）",
        hovermode="x unified",
        height=480
    )
    st.plotly_chart(fig, use_container_width=True, key="asset_trend_chart")

def plot_goal_pie(title, achieved, total, key=None):
    achieved = float(max(achieved, 0.0))
    total = float(max(total, 0.0))
    remain = float(max(total - achieved, 0.0))

    fig = go.Figure(data=[go.Pie(
        labels=["達成", "未達"],
        values=[achieved, remain],
        hole=0.55,
        textinfo="percent"
    )])
    fig.update_layout(
        title=title,
        height=300,
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=True
    )
    st.plotly_chart(fig, use_container_width=True, key=key)

def plot_fi_simulation(df_sim, fi_target_asset, show_ideal, chart_key="fi_sim"):
    if df_sim is None or df_sim.empty:
        st.info("シミュレーションに必要なデータが不足しています。")
        return

    df = df_sim.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["investable_real"],
        mode="lines",
        name="💰 現実（予測）投資可能資産（銀行+NISA）",
        hovertemplate="日付: %{x|%Y-%m}<br>投資可能資産: %{y:,.0f} 円<extra></extra>"
    ))

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["total_real"],
        mode="lines",
        name="📦 現実（予測）合計（Goals含む）",
        line=dict(dash="dot"),
        visible="legendonly",
        hovertemplate="日付: %{x|%Y-%m}<br>合計: %{y:,.0f} 円<extra></extra>"
    ))

    fig.add_hline(
        y=float(fi_target_asset),
        line_dash="dash",
        annotation_text="🏁 FI必要資産",
        annotation_position="top left",
    )

    if show_ideal and "investable_ideal" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["investable_ideal"],
            mode="lines",
            name="🎯 理想（FI到達ペース）投資可能資産",
            line=dict(dash="dash"),
            hovertemplate="日付: %{x|%Y-%m}<br>理想 投資可能: %{y:,.0f} 円<extra></extra>"
        ))

    ok = df[df["fi_ok_real"] == True].copy()
    if not ok.empty:
        first = ok.iloc[0]
        fig.add_trace(go.Scatter(
            x=[first["date"]], y=[first["investable_real"]],
            mode="markers",
            name="✅ FI達成（現実）",
            marker=dict(size=9),
            hovertemplate="FI達成: %{x|%Y-%m}<br>%{y:,.0f} 円<extra></extra>"
        ))

    fig.update_layout(
        title="🔮 FIシミュレーション（支出イベント反映 / FI必要資産ベース）",
        xaxis_title="日付",
        yaxis_title="金額（円）",
        hovermode="x unified",
        height=560,
    )

    st.plotly_chart(fig, use_container_width=True, key=chart_key)

# ==================================================
# UI（メイン）
# ==================================================
def main():
    st.title("💰 今月サマリー")
    
    # 1. データ読み込み
    df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log = dl.load_data()
    df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log = dl.preprocess_data(
        df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log
    )
    today = datetime.today()

    # 2. パラメータ取得
    goals_horizon_years = lg.to_int_safe(lg.get_latest_parameter(df_params, "Goals積立対象年数", today), default=5)
    swr_assumption = lg.to_float_safe(lg.get_latest_parameter(df_params, "SWR", today), default=0.035)
    end_age = lg.to_float_safe(lg.get_latest_parameter(df_params, "老後年齢", today), default=60.0)
    current_age = lg.to_float_safe(lg.get_latest_parameter(df_params, "現在年齢", today), default=20.0)
    annual_return = lg.to_float_safe(lg.get_latest_parameter(df_params, "投資年利", today), default=0.05)

    # 3. 計算実行
    summary = lg.calculate_monthly_summary(df_params, df_fix, df_forms, df_balance, today)
    ef = lg.estimate_emergency_fund(df_params, df_fix, df_forms, today)
    
    bank_balance = float(summary["current_bank"])
    nisa_balance = float(summary["current_nisa"])

    emergency_is_danger = bank_balance < float(ef["fund_min"])
    emergency_not_met = bank_balance < float(ef["fund_rec"])
    
    deficit = lg.analyze_deficit(summary["monthly_income"], summary["fix_cost"], summary["variable_cost"])

    # 4. Goals計算
    outflows_by_month, targets_by_month, df_goals_norm = lg.prepare_goals_events(
        df_goals, today,
        only_required=True,
        horizon_years=goals_horizon_years
    )

    actual_goals_pmt_month = lg.goals_log_monthly_actual(df_goals_log, today)
    actual_goals_cum = lg.goals_log_cumulative(df_goals_log)

    df_goals_progress = lg.allocate_goals_progress(df_goals_norm, actual_goals_cum)

    # 理想額の計算
    goals_save_plan_ideal, df_goals_plan_detail = lg.compute_goals_monthly_plan(
        df_goals_progress, today,
        emergency_not_met=emergency_not_met
    )

    # 緑色の余剰計算
    saved_goals_total = lg.goals_log_cumulative(df_goals_log)
    emergency_target = float(ef["fund_rec"])
    stock_surplus = max(bank_balance - saved_goals_total - emergency_target, 0.0)
    
    # 生活費P75の取得
    monthly_p75 = float(ef["monthly_est_p75"])

    # 現実的な配分計算（Logic V4: Auto-Buffer + Runway）
    available_cash = float(summary["available_cash"])
    
    allocation = lg.allocate_monthly_budget(
        available_cash=available_cash,
        df_goals_plan_detail=df_goals_plan_detail, 
        emergency_not_met=emergency_not_met,
        stock_surplus=stock_surplus,
        monthly_spend_p75=monthly_p75 
    )

    nisa_save = allocation["nisa_save"]
    bank_save = allocation["bank_save"]
    # シミュレーション用には、今回の「計画値」を使う
    goals_save_plan_calc = allocation["goals_save"]
    
    goals_shortfall = allocation["goals_shortfall"]
    goals_ideal_total = allocation["ideal_goals_total"]
    
    free_cash = max(available_cash - nisa_save - bank_save - goals_save_plan_calc, 0.0)

    # ==================================================
    # KPI表示
    # ==================================================
    st.subheader("📌 KPI（今月）")
    k1, k2, k3, k4 = st.columns(4)
    
    k1.metric(
        "🏦 銀行積立", 
        f"{bank_save:,} 円",
        help=f"最低確保額（{config.MIN_BANK_AMOUNT:,}円）を含みます。"
    )
    
    nisa_help = f"最低確保額（{config.MIN_NISA_AMOUNT:,}円）。"
    if available_cash <= 0 and nisa_save > 0:
        nisa_help += "\n\n★今月は赤字ですが、銀行の余剰資金を活用して積み立てます（ナイス判断！）。"

    k2.metric(
        "📈 NISA積立", 
        f"{nisa_save:,} 円",
        help=nisa_help
    )

    # ----------------------------------------------------
    # ★修正ポイント：Goals実績を「先に」取得し、計算に組み込む
    # ----------------------------------------------------
    goals_save_recorded = lg.goals_log_monthly_actual(df_goals_log, today)

    # 3. Goals積立可能枠（計算：Plan）
    # ----------------------------------------------------
    buffer_target_val = monthly_p75 * config.BANK_GREEN_BUFFER_MONTHS
    
    # ★重要：今月のGoals実績（記録済み）を余剰に戻して、「もし払ってなかったら」の状態を再現する
    # これにより、支払い後も「今月の可能枠（目標）」が減らない
    current_stock_surplus_adjusted = stock_surplus + goals_save_recorded
    
    excess_wealth_for_goals = max(current_stock_surplus_adjusted - buffer_target_val, 0.0)
    
    months_div = config.STOCK_TRANSFER_DURATION_MONTHS if hasattr(config, "STOCK_TRANSFER_DURATION_MONTHS") else 12
    capped_stock_surplus = excess_wealth_for_goals / months_div if months_div > 0 else 0
    
    current_flow_surplus = max(available_cash - nisa_save - bank_save, 0.0)
    
    # これが「今月積立すべき金額（Plan）」
    real_goals_capacity = current_flow_surplus + capped_stock_surplus
    
    # Help情報の計算
    total_power = excess_wealth_for_goals + current_flow_surplus
    gap_to_buffer = max(buffer_target_val - current_stock_surplus_adjusted, 0.0)

    if gap_to_buffer > 0:
        help_text = f"""
        【積立枠 0円 の理由】
        安全バッファの構築を最優先しています。（あと {int(gap_to_buffer):,} 円）
        """
    else:
        help_text = f"""
        【内訳（ランウェイ方式）】
        バッファ目標（{int(buffer_target_val):,}円）は確保済みです。
        
        ・収入から：{int(current_flow_surplus):,} 円
        ・銀行余剰から：{int(capped_stock_surplus):,} 円
        
        ※ 今月の入金済額を含めた余剰 {int(excess_wealth_for_goals):,} 円 を、
        向こう {months_div} ヶ月で配分するペースで算出しています。
        """

    k3.metric(
        "💪 Goals積立可能枠", 
        f"{int(real_goals_capacity):,} 円",
        help=help_text
    )
    
    # 4. Goals積立（実績：Record）
    if real_goals_capacity > 0:
        # 目標（可能枠）に対する達成度を表示
        # ほぼ達成（99%以上）ならOK
        if goals_save_recorded >= real_goals_capacity * 0.99:
            delta_str = "目標達成！ 🎉"
            delta_color = "normal"
        else:
            # 未達
            remaining_to_save = real_goals_capacity - goals_save_recorded
            delta_str = f"未達（あと {int(remaining_to_save):,} 円）"
            delta_color = "off" # 赤字にはせずグレー表示
    else:
        # 枠がない場合
        if goals_save_recorded > 0:
             delta_str = "バッファ優先期間中" 
             delta_color = "off"
        else:
             delta_str = "-"
             delta_color = "off"

    k4.metric(
        "🎯 Goals積立（実績）", 
        f"{int(goals_save_recorded):,} 円",
        delta=delta_str,
        delta_color=delta_color,
        help="【実績値】\nGoogleスプレッドシート（Goals_Save_Log）に記録された、今月の入金合計です。\n左の「可能枠」と同額になるよう入金してください。"
    )
    
    # 稼ぐ目標額の目安
    target_income_ideal = float(summary["fix_cost"]) + float(summary["variable_cost"]) + float(config.MIN_NISA_AMOUNT + config.MIN_BANK_AMOUNT) + float(goals_ideal_total)
    shortage_for_ideal = max(target_income_ideal - float(summary["monthly_income"]), 0)

    if shortage_for_ideal > 0:
        st.caption(f"💭 あと {int(shortage_for_ideal):,} 円稼げば、全てのGoalsを理想通りに進められます（目安月収：{int(target_income_ideal):,} 円）")
    else:
        st.caption("✨ 今月の収入で、理想的な積立ペースをクリアできています！")

    s1, s2 = st.columns(2)

    ef_rec_val = float(ef["fund_rec"])
    ef_min_val = float(ef["fund_min"])
    
    if bank_balance >= ef_rec_val:
        ef_status_str = "✅ 推奨額 達成済"
    elif bank_balance >= ef_min_val:
        ef_status_str = "⚠️ 最低額はクリア（推奨額まであと少し）"
    else:
        ef_status_str = "🚨 危険水域（最低額未満）"

    ef_help_text = f"""
    【現在のステータス】
    {ef_status_str}
    
    ・現在地: {int(bank_balance):,} 円
    ・目標額: {int(ef_rec_val):,} 円
    
    【判定ロジック】
    過去の支出データから算出した「生活費の{ef['months_factor']}ヶ月分」を推奨額としています。
    まずはここを100%にすることを目指しましょう。
    """

    ef_ratio = 0.0 if ef_rec_val <= 0 else min(bank_balance / ef_rec_val, 1.0)
    s1.metric(
        "🛡️ 生活防衛費達成率（推奨）", 
        f"{int(ef_ratio*100)} %",
        help=ef_help_text
    )
    s1.progress(ef_ratio)

    if goals_ideal_total <= 0:
        s2.metric("🎯 Goals積立達成率（当月）", "—")
        s2.caption("今月、積立対象の必須Goalsがありません。")
    else:
        # ※ここも 実績(recorded) / 理想(ideal) で計算
        goals_month_ratio = min(float(goals_save_recorded) / float(goals_ideal_total), 1.0)
        s2.metric("🎯 Goals積立達成率（当月）", f"{int(goals_month_ratio*100)} %")
        s2.progress(goals_month_ratio)
        s2.caption(f"現実：{int(goals_save_recorded):,} 円 / 理想：{int(goals_ideal_total):,} 円")

    st.caption(
        f"月収：{int(summary['monthly_income']):,} 円 "
        f"(固定 {int(summary['base_income']):,} / 臨時 {int(summary['variable_income']):,})"
    )
    st.caption(f"固定費：{int(summary['fix_cost']):,} 円 / 変動費：{int(summary['variable_cost']):,} 円")
    st.caption(f"※ 現在資産：{int(summary['current_total_asset']):,} 円（銀行 {int(bank_balance):,} / NISA {int(nisa_balance):,}）")

    st.divider()

    # ==================================================
    # 👛 今月の生活費・ゆとり費（予算管理）
    # ==================================================
    st.subheader("👛 今月の生活費・ゆとり費（あといくら使える？）")

    spending_limit_from_income = max(summary["monthly_income"] - summary["fix_cost"] - nisa_save - bank_save, 0.0)
    current_spent = summary["variable_cost"]
    remaining_budget = spending_limit_from_income - current_spent

    b1, b2, b3 = st.columns([1, 1, 2])

    b1.metric(
        "💰 生活費の上限目安",
        f"{int(spending_limit_from_income):,} 円",
        help="収入 - (固定費 + NISA + 銀行積立)。\nこれ以上使うと、資産の取り崩し（赤字）になります。"
    )

    b2.metric(
        "💸 すでに使った額",
        f"{int(current_spent):,} 円",
        help="食費、日用品、娯楽費などの合計です。"
    )

    if remaining_budget >= 0:
        b3.metric(
            "🥗 残り予算（外食・娯楽OK）",
            f"{int(remaining_budget):,} 円",
            delta="予算内です ✅",
            delta_color="normal",
            help="この金額の範囲内なら、外食してもバッファ（貯金）は減りません！"
        )
        if spending_limit_from_income > 0:
            pct = min(current_spent / spending_limit_from_income, 1.0)
            st.progress(pct, text=f"予算消化率: {int(pct*100)}%")
        
    else:
        over_amount = abs(remaining_budget)
        b3.metric(
            "🥗 残り予算",
            "0 円",
            delta=f"予算超過: -{int(over_amount):,} 円 ⚠️",
            delta_color="inverse",
            help="収入の範囲を超えています！これ以上の出費は「銀行のバッファ」を削ることになります。"
        )
        st.progress(1.0, text="🚨 予算オーバー！節約モード推奨")

    st.caption("※ この「残り予算」を使い切らずに残すと、その分が自動的に「Goals積立」や「バッファ補充」に回ります。")

    st.divider()

    # ==================================================
    # 🏦 銀行口座の「仮想内訳」見える化
    # ==================================================
    st.subheader("🏦 銀行口座の中身（仮想内訳）")

    # 変数は上で計算済み (stock_surplusなど)
    current_bank_real = bank_balance
    
    # 3層構造の計算
    val_goals = min(current_bank_real, saved_goals_total)
    remaining_1 = current_bank_real - val_goals

    val_emergency = min(remaining_1, emergency_target)
    remaining_2 = remaining_1 - val_emergency

    val_surplus = remaining_2

    # グラフ表示
    fig_bd = go.Figure()

    # レイヤー1: Goals
    fig_bd.add_trace(go.Bar(
        y=["口座内訳"], x=[val_goals], name="🔴 Goals預かり金", orientation='h',
        marker=dict(color='#FF6B6B'), # 赤
        hovertemplate="<b>Goals預かり金</b><br>%{x:,.0f} 円<br>（将来の支払い用・使用厳禁）<extra></extra>"
    ))

    # レイヤー2: 生活防衛費
    fig_bd.add_trace(go.Bar(
        y=["口座内訳"], x=[val_emergency], name="🟡 生活防衛費", orientation='h',
        marker=dict(color='#FFD93D'), # 黄色
        hovertemplate="<b>生活防衛費</b><br>%{x:,.0f} 円<br>（緊急時のバッファ）<extra></extra>"
    ))

    # レイヤー3: フリー余剰
    if val_surplus > 0:
        fig_bd.add_trace(go.Bar(
            y=["口座内訳"], x=[val_surplus], name="🟢 フリー余剰", orientation='h',
            marker=dict(color='#6BCB77'), # 緑
            hovertemplate="<b>フリー余剰資金</b><br>%{x:,.0f} 円<br>（自由に使ってOK）<extra></extra>"
        ))

    fig_bd.update_layout(
        barmode='stack', height=180, title="", xaxis_title="金額（円）",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=20, b=20)
    )

    col_bd1, col_bd2 = st.columns([2, 1])

    with col_bd1:
        st.plotly_chart(fig_bd, use_container_width=True, key="bank_breakdown_v2")

    with col_bd2:
        if current_bank_real < saved_goals_total:
            st.error("🚨 警告：Goals浸食")
            st.caption(f"Goals資金を {int(saved_goals_total - current_bank_real):,} 円 使い込んでいます。至急補填が必要です。")
        elif val_surplus > 0:
            st.success("✨ 余裕あり")
            st.caption(f"防衛費まで満タンです。\n{int(val_surplus):,} 円は自由に使えます。")
        else:
            pct = int((val_emergency / emergency_target) * 100) if emergency_target > 0 else 0
            st.info(f"🛡️ 防衛費構築中 ({pct}%)")
            st.caption(f"Goalsは確保済。\n防衛費満タンまであと {int(emergency_target - val_emergency):,} 円")

        if deficit is not None:
            st.warning(f"⚠️ 今月は取り崩し中")
            st.caption(f"残高はありますが、今月は資産が {int(deficit['total_deficit']):,} 円 減っています。")

    st.divider()

    # ==================================================
    # 赤字分析
    # ==================================================
    if deficit is not None:
        st.warning(f"⚠️ 今月は {int(deficit['total_deficit']):,} 円の赤字です")
        st.markdown("**主な要因：**")
        if deficit["fix_over"] > 0:
            st.write(f"固定費が月収を {int(deficit['fix_over']):,} 円 上回っています")
        if deficit["var_over"] > 0:
            st.write(f"変動費が想定を {int(deficit['var_over']):,} 円 上回っています")
        else:
            st.write(f"変動費は想定範囲内です（想定：{int(deficit['var_expected']):,} 円 / 実際：{int(deficit['var_actual']):,} 円）")

    # ==================================================
    # メモ分析
    # ==================================================
    st.subheader("🧠 今月の振り返り（メモ分析）")
    memo = lg.analyze_memo_frequency_advanced(
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

    st.subheader("📂 控え候補の内訳（カテゴリ別）")
    category_analysis = lg.analyze_memo_by_category(
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

    st.subheader("📈 最近増えている費目（直近月 vs 過去3か月平均）")
    trend = lg.analyze_category_trend_3m(df_forms, today)
    if not trend:
        st.info("最近増えている費目は特にありませんでした")
    else:
        for item in trend:
            st.markdown(
                f"- **{item['category']}**：今月 {int(item['current']):,} 円 / "
                f"過去平均 {int(item['past_avg']):,} 円（**+{int(item['diff']):,} 円**）"
            )

    # ==================================================
    # 生活防衛費（自動算出）
    # ==================================================
    st.subheader("🛡️ 生活防衛費（自動算出）")
    c1, c2, c3 = st.columns(3)
    c1.metric("推定 1か月生活費（中央値）", f"{int(ef['monthly_est_median']):,} 円")
    c2.metric("推定 1か月生活費（P75）", f"{int(ef['monthly_est_p75']):,} 円")
    c3.metric(f"係数（{ef['months_factor']}か月分）", f"{ef['months_factor']} か月")
    st.caption(f"算出方法：{ef['method']}")

    with st.expander("内訳（月次）を見る"):
        df_ef_view = pd.DataFrame({
            "固定費": ef["series_fix"],
            "変動費": ef["series_var"],
            "合計":  ef["series_total"],
        })
        df_ef_view = df_ef_view.apply(pd.to_numeric, errors="coerce").fillna(0)
        st.dataframe(df_ef_view.style.format("{:,.0f}"), use_container_width=True)

    # ==================================================
    # Goals（積立詳細 + 円グラフ）
    # ==================================================
    st.subheader("🎯 Goals（必須）積立の進捗", help=f"対象：必須のみ / 今日から {goals_horizon_years} 年先まで")

    if df_goals_progress is None or df_goals_progress.empty:
        st.info("対象期間内に必須Goalsがありません。")
    else:
        with st.expander("今月のGoals積立（内訳・近→中→長）を見る"):
            if df_goals_plan_detail is None or df_goals_plan_detail.empty:
                st.info("今月、積立が必要な必須Goalsがありません。")
            else:
                view = df_goals_plan_detail.copy()
                view["bucket"] = view["bucket"].map({"near": "近距離", "mid": "中距離", "long": "遠距離"}).fillna(view["bucket"])
                view["達成期限"] = pd.to_datetime(view["deadline"]).dt.strftime("%Y-%m")
                view["残額"] = view["remaining_amount"].astype(float)
                view["最低積立"] = view["min_pmt"].astype(float)
                view["今月計画"] = view["plan_pmt"].astype(float)
                show = view[["bucket", "name", "達成期限", "残額", "最低積立", "今月計画"]].rename(columns={"name":"目標名"})
                st.dataframe(show.style.format({"残額":"{:,.0f}","最低積立":"{:,.0f}","今月計画":"{:,.0f}"}), use_container_width=True)

        with st.expander("累積の達成率（項目別 + 円グラフ）を見る"):
            d = df_goals_progress.copy()
            d["bucket_name"] = d["bucket"].map({"near":"近距離","mid":"中距離","long":"遠距離"}).fillna(d["bucket"])
            d["deadline_ym"] = pd.to_datetime(d["deadline"]).dt.strftime("%Y-%m")
            d["達成率"] = d["achieved_rate"].apply(lambda x: f"{int(x*100)} %")

            st.caption(f"Goals累積実績（Goals_Save_Log）：{int(actual_goals_cum):,} 円")

            for i, r in d.iterrows():
                title = f"{r['bucket_name']}｜{r['name']}（期限 {r['deadline_ym']}）｜達成 {int(r['achieved_rate']*100)}%"
                cols = st.columns([1.2, 1.0])
                with cols[0]:
                    st.markdown(f"**{title}**")
                    st.write(f"- 目標額：{int(r['amount']):,} 円")
                    st.write(f"- 達成額：{int(r['achieved_amount']):,} 円")
                    st.write(f"- 残額：{int(r['remaining_amount']):,} 円")
                with cols[1]:
                    plot_goal_pie(
                        title="", 
                        achieved=float(r["achieved_amount"]), 
                        total=float(r["amount"]),
                        key=f"pie_{i}"
                    )
                st.divider()

    # ==================================================
    # 資産推移（現状）
    # ==================================================
    st.subheader("📊 資産推移（現状）")
    plot_asset_trend(df_balance, ef)

    # ==================================================
    # FI設計
    # ==================================================
    st.subheader("🏁 FI（Financial Independence）")

    spend_choice = st.radio(
        "老後の月額支出（FIライン）",
        options=["35万円", "40万円", "45万円"],
        horizontal=True,
        index=1
    )
    monthly_spend = 350_000 if spend_choice == "35万円" else 400_000 if spend_choice == "40万円" else 450_000

    fi_required_asset = lg.compute_fi_required_asset(monthly_spend, swr_assumption)
    investable_now = bank_balance + nisa_balance
    current_swr = lg.compute_current_swr(monthly_spend, investable_now)

    f1, f2, f3 = st.columns(3)
    f1.metric("🏁 FI必要資産", f"{int(fi_required_asset):,} 円")
    
    swr_help = "SWR（安全取り崩し率）の直感：小さいほど余裕が大きい（同じ支出でも、資産が大きいほどSWRは下がる）"
    
    if current_swr is None:
        f2.metric("📉 現在SWR（年）", "—", help=swr_help)
    else:
        f2.metric("📉 現在SWR（年）", f"{current_swr*100:.2f} %", help=swr_help)
        
    f3.metric("🧷 採用SWR（仮定）", f"{swr_assumption*100:.2f} %")

    # ==================================================
    # FIシミュレーション
    # ==================================================
    real_total_pmt = lg.estimate_realistic_monthly_contribution(df_balance, months=6)

    plan_total = float(bank_save + nisa_save + goals_save_plan_calc)
    if plan_total > 0:
        share_bank = bank_save / plan_total
        share_nisa = nisa_save / plan_total
        share_goals = goals_save_plan_calc / plan_total
    else:
        share_bank = share_nisa = share_goals = 1.0 / 3.0

    monthly_emergency_save_real = float(real_total_pmt * share_bank)
    monthly_nisa_save_real = float(real_total_pmt * share_nisa)
    monthly_goals_save_real = float(real_total_pmt * share_goals)

    fi_sim_help_text = (
        f"現実（予測）に使う月次積立（直近平均）：{int(real_total_pmt):,} 円 / 月\n"
        f"（防衛費 {int(monthly_emergency_save_real):,} ・NISA {int(monthly_nisa_save_real):,} ・Goals {int(monthly_goals_save_real):,}）"
    )

    st.subheader("🔮 FIシミュレーション（支出イベント反映）", help=fi_sim_help_text)

    current_goals_fund_est = float(max(actual_goals_cum, 0.0))
    current_emergency_cash_est = float(max(bank_balance - current_goals_fund_est, 0.0))

    show_ideal = st.checkbox("🎯 理想ラインも表示する", value=False)

    df_fi_sim = lg.simulate_fi_paths(
        today=today,
        current_age=current_age,
        end_age=end_age,
        annual_return=annual_return,
        current_emergency_cash=current_emergency_cash_est,
        current_goals_fund=current_goals_fund_est,
        current_nisa=nisa_balance,
        monthly_emergency_save_real=monthly_emergency_save_real,
        monthly_goals_save_real=monthly_goals_save_real,
        monthly_nisa_save_real=monthly_nisa_save_real,
        fi_target_asset=fi_required_asset,
        outflows_by_month=outflows_by_month,
        ef_rec=float(ef["fund_rec"]),
    )

    fi_ok = df_fi_sim[df_fi_sim["fi_ok_real"] == True].copy()
    if fi_ok.empty:
        st.info("現実（予測）では、指定の年齢までに FI達成が見つかりませんでした。")
        fi_month_str = "未達"
    else:
        first = fi_ok.iloc[0]
        fi_month_str = pd.to_datetime(first["date"]).strftime("%Y-%m")

    card1, card2, card3 = st.columns(3)
    card1.metric("✅ FI達成月（現実予測）", fi_month_str)
    card2.metric("🏦 推奨防衛費", f"{int(ef['fund_rec']):,} 円")
    card3.metric("📌 現在の投資可能資産（銀行+NISA）", f"{int(investable_now):,} 円")

    plot_fi_simulation(df_fi_sim, fi_required_asset, show_ideal=show_ideal, chart_key="fi_sim_main")

    # ==================================================
    # シミュレーション詳細
    # ==================================================
    st.markdown("### 🧾 シミュレーション詳細（支出イベント）")
    tab1, tab2 = st.tabs(["💸 支出（必須）", "📦 内訳（現実）"])

    with tab1:
        out = df_fi_sim[df_fi_sim["outflow"].fillna(0) > 0].copy()
        if out.empty:
            st.info("支出イベントはありません。")
        else:
            out["月"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m")
            view = out[["月", "outflow_name", "outflow", "unpaid_real", "unpaid_ideal"]].copy()
            view = view.rename(columns={
                "outflow_name": "支出名",
                "outflow": "支出額",
                "unpaid_real": "未払い（現実）",
                "unpaid_ideal": "未払い（理想）",
            })
            st.dataframe(
                view.style.format({"支出額":"{:,.0f}","未払い（現実）":"{:,.0f}","未払い（理想）":"{:,.0f}"}),
                use_container_width=True
            )

    with tab2:
        view = df_fi_sim.copy()
        view["月"] = pd.to_datetime(view["date"]).dt.strftime("%Y-%m")
        show = view[["月", "emergency_real", "goals_fund_real", "nisa_real", "investable_real", "total_real"]].copy()
        show = show.rename(columns={
            "emergency_real":"防衛費（推定）",
            "goals_fund_real":"Goals口座（推定）",
            "nisa_real":"NISA",
            "investable_real":"投資可能（銀行+NISA）",
            "total_real":"合計（Goals含む）",
        })

        num_cols = ["防衛費（推定）","Goals口座（推定）","NISA","投資可能（銀行+NISA）","合計（Goals含む）"]
        show[num_cols] = show[num_cols].apply(pd.to_numeric, errors="coerce").fillna(0)

        st.dataframe(
            show.style.format({c: "{:,.0f}" for c in num_cols}),
            use_container_width=True
        )

if __name__ == "__main__":
    main()
