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
# 統合グラフ（実績＋シミュレーション）描画関数
# ==================================================
def plot_integrated_sim_chart(df_balance, df_sim, fi_target_asset, chart_key="integrated_chart"):
    """
    過去の実績（Balance_Log）と未来の予測（df_sim）を一つのグラフに統合して表示する。
    """
    fig = go.Figure()

    # 1. 過去の実績プロット
    if df_balance is not None and not df_balance.empty:
        df_hist = df_balance.copy().dropna(subset=["日付"]).sort_values("日付")
        df_hist["投資可能資産"] = pd.to_numeric(df_hist["銀行残高"], errors="coerce").fillna(0) + \
                               pd.to_numeric(df_hist["NISA評価額"], errors="coerce").fillna(0)
        
        fig.add_trace(go.Scatter(
            x=df_hist["日付"], y=df_hist["投資可能資産"],
            mode="lines+markers", name="📈 実績（投資可能資産）",
            line=dict(color="royalblue", width=3)
        ))

    # 2. 未来の予測プロット
    if df_sim is not None and not df_sim.empty:
        # 予測開始点を実績の最後と繋げるために処理
        fig.add_trace(go.Scatter(
            x=df_sim["date"], y=df_sim["investable_real"],
            mode="lines", name="🔮 予測（投資可能資産）",
            line=dict(color="royalblue", width=3, dash="dash"),
            hovertemplate="日付: %{x|%Y-%m}<br>金額: %{y:,.0f} 円<extra></extra>"
        ))
        
        # 合計資産（Goals含む）
        fig.add_trace(go.Scatter(
            x=df_sim["date"], y=df_sim["total_real"],
            mode="lines", name="📦 予測合計（Goals含む）",
            line=dict(color="gray", width=1, dash="dot"),
            visible="legendonly"
        ))

    # 3. 目標ライン
    fig.add_hline(
        y=float(fi_target_asset),
        line_dash="dash", line_color="red",
        annotation_text="🏁 FI必要資産",
        annotation_position="top left",
    )

    fig.update_layout(
        title="🔮 資産推移（過去実績 ➔ 未来予測）",
        xaxis_title="年月",
        yaxis_title="金額（円）",
        hovermode="x unified",
        height=560,
        xaxis=dict(rangeslider=dict(visible=True), type="date") # レンジスライダー追加
    )

    st.plotly_chart(fig, use_container_width=True, key=chart_key)

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

    emergency_not_met = bank_balance < float(ef["fund_rec"])
    deficit = lg.analyze_deficit(summary["monthly_income"], summary["fix_cost"], summary["variable_cost"])

    # 4. Goals計算
    outflows_by_month, _, df_goals_norm = lg.prepare_goals_events(
        df_goals, today, only_required=True, horizon_years=goals_horizon_years
    )

    actual_goals_cum = lg.goals_log_cumulative(df_goals_log)
    df_goals_progress = lg.allocate_goals_progress(df_goals_norm, actual_goals_cum)
    goals_save_recorded = lg.goals_log_monthly_actual(df_goals_log, today)

    # 理想額の計算
    goals_ideal_total, df_goals_plan_detail = lg.compute_goals_monthly_plan(
        df_goals_progress, today, emergency_not_met=emergency_not_met
    )

    # 緑色の余剰計算
    saved_goals_total = lg.goals_log_cumulative(df_goals_log)
    emergency_target = float(ef["fund_rec"])
    stock_surplus = max(bank_balance - saved_goals_total - emergency_target, 0.0)
    monthly_p75 = float(ef["monthly_est_p75"])

    # 現実的な配分計算
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
    goals_save_plan_calc = allocation["goals_save"]

    # ==================================================
    # KPI表示
    # ==================================================
    st.subheader("📌 KPI（今月）")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("🏦 銀行積立", f"{bank_save:,} 円")
    k2.metric("📈 NISA積立", f"{nisa_save:,} 円")
    
    # Goals可能枠
    buffer_target_val = monthly_p75 * config.BANK_GREEN_BUFFER_MONTHS
    adj_stock_surplus = stock_surplus + goals_save_recorded
    ex_wealth = max(adj_stock_surplus - buffer_target_val, 0.0)
    m_div = config.STOCK_TRANSFER_DURATION_MONTHS if hasattr(config, "STOCK_TRANSFER_DURATION_MONTHS") else 18
    real_goals_capacity = max(available_cash - nisa_save - bank_save, 0.0) + (ex_wealth / m_div)

    k3.metric("💪 Goals積立可能枠", f"{int(real_goals_capacity):,} 円")
    
    # 実績
    delta_str = "目標達成！ 🎉" if goals_save_recorded >= real_goals_capacity * 0.99 else f"未達（あと {int(real_goals_capacity - goals_save_recorded):,} 円）"
    k4.metric("🎯 Goals積立（実績）", f"{int(goals_save_recorded):,} 円", delta=delta_str)

    st.divider()

    # ==================================================
    # 👛 予算モニター & 🏦 仮想内訳
    # ==================================================
    col_left, col_right = st.columns([1, 1])
    
    with col_left:
        st.subheader("👛 あといくら使える？")
        limit = max(summary["monthly_income"] - summary["fix_cost"] - nisa_save - bank_save, 0.0)
        spent = summary["variable_cost"]
        rem = limit - spent
        st.metric("🥗 残り予算", f"{int(max(rem, 0)):,} 円", delta=f"超過: {int(rem):,} 円" if rem < 0 else None, delta_color="inverse")
        st.progress(min(spent/limit, 1.0) if limit > 0 else 1.0)

    with col_right:
        st.subheader("🏦 銀行口座の内訳")
        # 簡易的なBarチャート表示
        val_goals = min(bank_balance, saved_goals_total)
        val_em = min(max(bank_balance - val_goals, 0), emergency_target)
        val_free = max(bank_balance - val_goals - val_em, 0)
        
        fig_bd = go.Figure(data=[
            go.Bar(name="Goals", x=["内訳"], y=[val_goals], marker_color="#FF6B6B"),
            go.Bar(name="防衛費", x=["内訳"], y=[val_em], marker_color="#FFD93D"),
            go.Bar(name="フリー", x=["内訳"], y=[val_free], marker_color="#6BCB77")
        ])
        fig_bd.update_layout(barmode='stack', height=200, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_bd, use_container_width=True)

    st.divider()

    # ==================================================
    # 🔮 FIシミュレーション（統合版）
    # ==================================================
    st.subheader("🔮 FIシミュレーション（過去実績 ➔ 未来予測）")

    # シミュレーション用パラメータ
    real_total_pmt = lg.estimate_realistic_monthly_contribution(df_balance, months=6)
    
    # 銀行：Bank - Goals, Goals：Goals, NISA：NISA
    df_fi_sim = lg.simulate_fi_paths(
        today=today, current_age=current_age, end_age=end_age, annual_return=annual_return,
        current_emergency_cash=bank_balance - saved_goals_total,
        current_goals_fund=saved_goals_total,
        current_nisa=nisa_balance,
        monthly_emergency_save_real=bank_save, # 簡易的にKPI値を採用
        monthly_goals_save_real=goals_save_plan_calc,
        monthly_nisa_save_real=nisa_save,
        fi_target_asset=lg.compute_fi_required_asset(400000, swr_assumption), # 40万仮定
        outflows_by_month=outflows_by_month,
        ef_rec=emergency_target
    )

    # 統合グラフの表示
    plot_integrated_sim_chart(df_balance, df_fi_sim, lg.compute_fi_required_asset(400000, swr_assumption))

    # 詳細タブ
    tab1, tab2 = st.tabs(["💸 未来の支出予定", "📦 シミュレーション詳細データ"])
    with tab1:
        out = df_fi_sim[df_fi_sim["outflow"] > 0].copy()
        if not out.empty:
            out["月"] = out["date"].dt.strftime("%Y-%m")
            st.dataframe(out[["月", "outflow_name", "outflow", "unpaid_real"]].rename(columns={"outflow":"支出額", "unpaid_real":"不足額"}), use_container_width=True)
    with tab2:
        st.dataframe(df_fi_sim[["date", "investable_real", "nisa_real", "emergency_real", "goals_fund_real"]].style.format("{:,.0f}"), use_container_width=True)

    # ==================================================
    # その他詳細（既存機能）
    # ==================================================
    with st.expander("📝 今月の支出分析・防衛費詳細"):
        st.write(f"赤字要因分析: {deficit}")
        st.write(f"生活防衛費 算出根拠: {ef['method']}")

    with st.expander("🎯 Goals個別進捗"):
        if not df_goals_progress.empty:
            for i, r in df_goals_progress.iterrows():
                st.write(f"**{r['name']}** ({int(r['achieved_rate']*100)}%)")
                st.progress(r["achieved_rate"])

if __name__ == "__main__":
    main()