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
def plot_integrated_sim_chart(df_balance, df_sim, fi_target_asset, chart_key="fi_v3_final"):
    fig = go.Figure()

    # 1. 過去の実績
    if df_balance is not None and not df_balance.empty:
        df_hist = df_balance.copy().dropna(subset=["日付"]).sort_values("日付")
        df_hist["投資可能資産"] = pd.to_numeric(df_hist["銀行残高"], errors="coerce").fillna(0) + \
                               pd.to_numeric(df_hist["NISA評価額"], errors="coerce").fillna(0)
        fig.add_trace(go.Scatter(x=df_hist["日付"], y=df_hist["投資可能資産"], mode="lines+markers", name="📈 実績", line=dict(color="royalblue", width=3)))

    # 2. 未来の予測
    if df_sim is not None and not df_sim.empty:
        fig.add_trace(go.Scatter(
            x=df_sim["date"], y=df_sim["investable_real"],
            mode="lines", name="🔮 予測（真の投資可能資産）",
            line=dict(color="royalblue", width=3, dash="dash"),
            hovertemplate="日付: %{x|%Y-%m}<br>真の資産: %{y:,.0f} 円<extra></extra>"
        ))

        # 支出イベント
        events = df_sim[df_sim["outflow"] > 0]
        if not events.empty:
            fig.add_trace(go.Scatter(
                x=events["date"], y=events["investable_real"],
                mode="markers+text", name="💸 支出予定",
                marker=dict(symbol="triangle-down", size=12, color="orange"),
                text=events["outflow_name"], textposition="bottom center",
                hovertemplate="内容: %{text}<br>支出額: %{customdata:,.0f} 円<extra></extra>",
                customdata=events["outflow"]
            ))

    # 3. 目標ライン
    fig.add_hline(y=float(fi_target_asset), line_dash="dash", line_color="red")

    # ★レンジスライダーの追加
    fig.update_layout(
        title="🔮 未来予測：真の投資可能資産の推移",
        xaxis_title="年月", yaxis_title="金額（円）",
        hovermode="x unified", height=600,
        xaxis=dict(
            rangeslider=dict(visible=True), # これが期間選択バー
            type="date",
            rangeselector=dict(
                buttons=list([
                    dict(count=2, label="2年", step="year", stepmode="backward"),
                    dict(count=5, label="5年", step="year", stepmode="backward"),
                    dict(step="all", label="全期間")
                ])
            )
        )
    )
    st.plotly_chart(fig, use_container_width=True, key=f"{chart_key}_{datetime.now().microsecond}")
    
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

    # df_paramsを辞書形式に変換（params.get()を使えるようにする）
    params = dict(zip(df_params["項目"], df_params["値"]))

    # 税金・扶養監視ステータスの計算
    # 第1引数は df_forms (収入データが含まれるもの) を渡します
    tax_status = lg.calculate_tax_status(df_forms, params)
    
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
    
    # 税金監視KPI
    tax_status = lg.calculate_tax_status(df_forms, params) # df_forms を渡す
    
    if tax_status:
        st.subheader("🛡️ 税金・扶養監視アラート")
        # logic.py の戻り値には 'salary_total'（額面合計）も入っています
        total_revenue = float(tax_status['salary_total']) + float(tax_status['side_total'])
        
        # 額面を表示する行を追加
        st.caption(f"💰 今年の額面収入合計: {int(total_revenue):,} 円 (給与控除前の金額)")
        
        # 1. 扶養の壁（103万の壁 ＝ 所得48万）
        dep_limit = float(params.get('DEPENDENT_INCOME_LIMIT', 480000))
        progress = min(float(tax_status['total_taxable_income']) / dep_limit, 1.0)
        remaining = dep_limit - float(tax_status['total_taxable_income'])
        
        col_t1, col_t2 = st.columns([3, 1])
        with col_t1:
            # 進捗バーの表示
            bar_color = "green" if progress < 0.8 else "orange" if progress < 0.95 else "red"
            st.progress(progress)
            st.caption(f"親の扶養（所得48万円ライン）までの進捗: {progress:.1%}")
        with col_t2:
            st.metric("扶養まで残り", f"{int(remaining):,} 円")

        # 2. 住民税・確定申告のアラート
        kunto_limit = float(params.get('HADANO_KUNTO_LIMIT', 380000))
        side_limit = float(params.get('SIDE_INCOME_REPORT_LIMIT', 200000))
        
        c1, c2, c3 = st.columns(3)
        with c1:
            if tax_status['total_taxable_income'] > kunto_limit:
                st.warning("🏮 秦野市: 住民税(均等割)発生圏内")
            else:
                st.success("✅ 秦野市: 住民税 非課税圏内")
        
        with c2:
            if tax_status['side_total'] > side_limit:
                st.error("📝 所得税: 確定申告が必要です")
            elif tax_status['side_total'] > 0:
                st.info("ℹ️ 住民税の申告が必要です")
        
        with c3:
            st.metric("副業純利益(推計)", f"{int(tax_status['side_net_profit']):,} 円")
            
        with st.expander("ℹ️ 表示の意味と「税金の壁」について（ヘルプ）"):
            st.markdown("""
            **🛡️ 親の扶養（103万円の壁）**
            - あなたの「合計所得」が **48万円**（給与収入換算で103万円）を超えると、親御さんの税金が高くなります（扶養控除が外れます）。
            - 最も優先して守るべきラインです。
            
            **🏮 秦野市: 住民税(均等割)**
            - 所得税は0円でも、市役所に支払う「住民税の基本料金（約5,300円/年）」が発生するラインです。
            - 合計所得が **38万円**（給与換算で約93万円）を超えると発生します。
            - これを超えても親の扶養には影響しません。「社会勉強代」として割り切るのもアリです。
            
            **📝 副業の確定申告（20万円ルール）**
            - 給与以外の所得（note売上 - 経費）が **年間20万円** を超えると、税務署への確定申告が義務になります。
            - 20万円以下の場合、確定申告は不要ですが、**住民税の申告**は別途必要になる場合があります（アラートで通知します）。
            """)
        st.divider()
    # ==================================================
    # 👛 予算モニター & 🏦 仮想内訳
    # ==================================================
    col_left, col_right = st.columns([1, 1])
    
    with col_left:
        st.subheader("👛 あといくら使える？")
        
        # 1. 計算ロジック
        # 収入 - 固定費 - 積立（NISA+銀行） = 生活費の予算上限 (limit)
        limit = max(summary["monthly_income"] - summary["fix_cost"] - nisa_save - bank_save, 0.0)
        spent = summary["variable_cost"]
        rem = limit - spent
        
        # 2. 表示
        st.metric("🥗 残り予算", f"{int(max(rem, 0)):,} 円", delta=f"超過: {int(rem):,} 円" if rem < 0 else None, delta_color="inverse")
        st.progress(min(spent/limit, 1.0) if limit > 0 else 1.0)

        # ★ここを追加：動的に数値が変わるヘルプ機能
        with st.expander("ℹ️ 計算式と内訳を見る"):
            st.markdown(f"""
            **「使えるお金」＝ (収入 － 固定費 － 積立) － 今月の出費**
            
            | 項目 | 金額 |
            | :--- | ---: |
            | **💰 総収入** | **{int(summary['monthly_income']):,} 円** |
            | 🏠 固定費 | - {int(summary['fix_cost']):,} 円 |
            | 🏦 積立(銀行+NISA) | - {int(nisa_save + bank_save):,} 円 |
            | **🥗 今月の生活予算** | **= {int(limit):,} 円** |
            | 🍔 今月の出費(変動費) | - {int(spent):,} 円 |
            | **残り予算** | **= {int(rem):,} 円** |
            
            ※ Parameterの「月収」を0にしたので、Googleフォームに入力した収入合計がそのまま「総収入」になります。
            """)

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
        # ★ここを日本語化＆未払い対応
        show = df_fi_sim.copy()
        show["日付"] = show["date"].dt.strftime("%Y-%m")
        show = show.rename(columns={
            "investable_real": "投資可能資産(FI判定用)",
            "nisa_real": "NISA残高(予測)",
            "emergency_real": "銀行残高(生活費+防衛費)",
            "goals_fund_real": "Goals準備金",
            "unpaid_real": "🚨 Goals支払い不足額",
            "total_real": "総資産合計"
        })
        
        display_cols = ["日付", "投資可能資産(FI判定用)", "NISA残高(予測)", "銀行残高(生活費+防衛費)", "Goals準備金", "🚨 Goals支払い不足額", "総資産合計"]
        num_format_dict = {col: "{:,.0f} 円" for col in display_cols if col != "日付"}
        
        st.dataframe(show[display_cols].style.format(num_format_dict), use_container_width=True)
    # ==================================================
    # その他詳細（既存機能）
    # ==================================================
    with st.expander("📝 今月の支出分析・防衛費詳細"):
        # 1. 赤字要因分析のビジュアル化
        st.markdown("#### 🔍 赤字の内訳診断")
        
        # ★追加：収入と固定費の対比を表示
        inc_col1, inc_col2 = st.columns(2)
        with inc_col1:
            st.write(f"📊 **今月の総収入:** {int(summary['monthly_income']):,} 円")
        with inc_col2:
            st.write(f"🏠 **今月の固定費:** {int(summary['fix_cost']):,} 円")
        
        # 固定費率の表示（参考）
        fix_rate = (summary['fix_cost'] / summary['monthly_income'] * 100) if summary['monthly_income'] > 0 else 0
        if fix_rate > 100:
            st.error(f"⚠️ 固定費だけで収入を超えています（固定費率: {int(fix_rate)}%）")
        else:
            st.caption(f"（収入に対する固定費の割合: {int(fix_rate)}%）")

        st.divider()

        if deficit:
            d_col1, d_col2 = st.columns(2)
            with d_col1:
                st.error(f"**合計赤字額: {int(deficit['total_deficit']):,} 円**")
                st.caption("※収入を支出が上回っている状態です")
            
            with d_col2:
                # 重複を避けるため、logic.pyの戻り値に合わせて表示
                if deficit.get('fix_over', 0) > 0:
                    st.warning(f"🏠 **固定費オーバー: {int(deficit['fix_over']):,} 円**")
                if deficit.get('var_over', 0) > 0:
                    st.warning(f"🍔 **変動費オーバー: {int(deficit['var_over']):,} 円**")
            
            # 詳しい比較
            st.markdown(f"""
            - **固定費:** 実際の固定費が月収を超えています。
            - **変動費の適正目安:** {int(deficit.get('var_expected', 0)):,} 円 （月収の30%と仮定）
            - **実際の変動費支出:** {int(deficit.get('var_actual', 0)):,} 円
            """)
        else:
            st.success("✨ 今月は黒字です！収支バランスは良好です。")

        st.divider()

        # 2. 生活防衛費の詳細
        st.markdown("#### 🛡️ 生活防衛費の算出根拠")
        e_col1, e_col2, e_col3 = st.columns(3)
        
        with e_col1:
            st.write("**目標とする月数**")
            st.write(f"{ef['months_factor']} か月分")
            
        with e_col2:
            st.write("**判定基準額**")
            st.write(f"{int(ef['monthly_est_p75']):,} 円/月")
            st.caption("(過去P75値)")
            
        with e_col3:
            st.write("**現在の目標総額**")
            # ★ここで Lowell を消してカンマ区切りだけに修正
            st.write(f"**{int(ef['fund_rec']):,} 円**")

        st.info(f"💡 算出方法: {ef['method']}。直近の生活費が高くなると、目標額も自動で調整されます。")

    with st.expander("🎯 Goals個別進捗"):
        if not df_goals_progress.empty:
            for i, r in df_goals_progress.iterrows():
                st.write(f"**{r['name']}** ({int(r['achieved_rate']*100)}%)")
                st.progress(r["achieved_rate"])

if __name__ == "__main__":
    main()
