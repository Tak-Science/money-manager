import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime
from dateutil.relativedelta import relativedelta

# --- 設定 ---
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
# URLを貼り付けてください
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1Ih1twG9XDIo5M9o9Qp_qVn5Z6v-p-U3i2T-u8-v8-mE/edit"

st.set_page_config(page_title="Financial Freedom Dashboard", layout="wide")

def get_spreadsheet():
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)
    return service.spreadsheets()

@st.cache_data(ttl=60)
def load_data():
    sheet = get_spreadsheet()
    try:
        spreadsheet_id = SPREADSHEET_URL.split('/d/')[1].split('/')[0]
    except:
        st.error("URLを確認してください。")
        st.stop()

    def get_df(sheet_name, range_name):
        try:
            res = sheet.values().get(spreadsheetId=spreadsheet_id, range=f'{sheet_name}!{range_name}').execute()
            data = res.get('values', [])
            if not data: return pd.DataFrame()
            return pd.DataFrame(data[1:], columns=data[0])
        except: return pd.DataFrame()

    df_params = get_df('Parameters', 'A:D')
    df_fix = get_df('Fix_Cost', 'A:H')
    df_balance = get_df('Balance_Log', 'A:Z')
    df_forms = get_df('Forms_Log', 'A:G') # フォーム回答用シート
    df_goals = get_df('Goals', 'A:F')

    return df_params, df_fix, df_balance, df_forms, df_goals

def main():
    st.title("💰 Financial Freedom Dashboard v5.3")
    df_params, df_fix, df_balance, df_forms, df_goals = load_data()

    if df_params.empty:
        st.warning("スプレッドシートの読み込みに失敗しました。Secretsの設定を確認してください。")
        st.stop()

    # --- 1. 数値のクリーニングと集計 ---
    today = datetime.now()
    this_month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 月収の取得 (Parameters)
    monthly_income = 0
    if not df_params.empty:
        row = df_params[df_params['項目'].str.contains('月収', na=False)]
        if not row.empty:
            monthly_income = pd.to_numeric(row.iloc[0]['値'], errors='coerce')

    # 現在の資産合計
    latest_asset = 0
    latest_bank = 0
    latest_nisa = 0
    if not df_balance.empty:
        df_balance['日付'] = pd.to_datetime(df_balance['日付'])
        last_row = df_balance.sort_values('日付').iloc[-1]
        latest_bank = pd.to_numeric(last_row['銀行残高'], errors='coerce') if '銀行残高' in last_row else 0
        latest_nisa = pd.to_numeric(last_row['NISA評価額'], errors='coerce') if 'NISA評価額' in last_row else 0
        latest_asset = latest_bank + latest_nisa

    # 今月の固定費 & 積立額の集計
    fixed_cost_only = 0
    monthly_savings_bank = 0
    monthly_savings_nisa = 0
    
    if not df_fix.empty:
        df_fix['金額'] = pd.to_numeric(df_fix['金額'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        for _, row in df_fix.iterrows():
            # 日付判定
            start = pd.to_datetime(row['開始日']) if row.get('開始日') else datetime(2000, 1, 1)
            end = pd.to_datetime(row['終了日']) if row.get('終了日') else datetime(2099, 12, 31)
            
            if start <= today <= end:
                cat = str(row.get('カテゴリ', ''))
                amt = row['金額']
                if '投資' in cat or 'NISA' in str(row['項目']):
                    monthly_savings_nisa += amt
                elif '貯金' in cat or '銀行' in str(row['項目']):
                    monthly_savings_bank += amt
                else:
                    fixed_cost_only += amt

    # 今月のフォーム支出 (Forms_Log)
    forms_spending = 0
    if not df_forms.empty:
        df_forms['日付'] = pd.to_datetime(df_forms['日付'], errors='coerce')
        df_forms['金額'] = pd.to_numeric(df_forms['金額'], errors='coerce').fillna(0)
        this_month_forms = df_forms[df_forms['日付'] >= this_month_start]
        forms_spending = this_month_forms['金額'].sum()

    # --- 2. 収支計算 ---
    net_income = monthly_income * 0.8
    total_outgo = fixed_cost_only + forms_spending + monthly_savings_bank + monthly_savings_nisa
    free_cash = net_income - total_outgo

    # --- 3. KPI表示 ---
    st.markdown("### 📊 Monthly Status")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("月収 (手取り80%)", f"¥{net_income:,.0f}")
    c2.metric("固定費+変動費", f"¥{fixed_cost_only + forms_spending:,.0f}")
    c3.metric("今月積立合計", f"¥{monthly_savings_bank + monthly_savings_nisa:,.0f}")
    
    if free_cash >= 0:
        c4.metric("🔥 自由資金", f"¥{free_cash:,.0f}")
    else:
        c4.metric("🔥 自由資金", f"¥{free_cash:,.0f}", delta="赤字です！", delta_color="inverse")

    st.info(f"内訳: 固定費 ¥{fixed_cost_only:,.0f} + フォーム支出 ¥{forms_spending:,.0f} + 積立 ¥{monthly_savings_bank + monthly_savings_nisa:,.0f}")

    # --- 4. 生活防衛費 ---
    st.markdown("---")
    defense_months = 6.0
    if not df_params.empty:
        row = df_params[df_params['項目'].str.contains('生活防衛費係数', na=False)]
        if not row.empty: defense_months = pd.to_numeric(row.iloc[0]['値'], errors='coerce')

    target_defense = (fixed_cost_only + 50000) * defense_months
    progress = min(latest_asset / target_defense, 1.0) if target_defense > 0 else 0
    
    st.markdown(f"### 🛡️ 生活防衛費 (Target: {defense_months}ヶ月分)")
    st.progress(progress)
    st.write(f"現在: ¥{latest_asset:,.0f} / 目標: ¥{target_defense:,.0f}")
    if latest_asset < target_defense:
        st.warning(f"あと **¥{target_defense - latest_asset:,.0f}** 必要です")
    else:
        st.success("✅ 生活防衛費達成！")

    # --- 5. 資産推移 (点表示追加) ---
    st.markdown("---")
    st.markdown("### 📈 資産推移")
    if not df_balance.empty:
        df_plot = df_balance.sort_values('日付')
        fig_balance = px.line(df_plot, x='日付', y=['銀行残高', 'NISA評価額'], markers=True) # markers=Trueで点を表示
        st.plotly_chart(fig_balance, use_container_width=True)

    # --- 6. 目標 (Goals) ---
    st.markdown("### 🎯 Goals")
    if not df_goals.empty:
        df_goals['金額'] = pd.to_numeric(df_goals['金額'], errors='coerce').fillna(0)
        for _, row in df_goals.iterrows():
            col_g1, col_g2 = st.columns([3, 1])
            g_amt = row['金額']
            g_type = row.get('タイプ', '目標')
            if g_type == '支出':
                col_g1.write(f"📉 {row['目標名']} (期限: {row['達成期限']})")
                col_g2.write(f"- ¥{g_amt:,.0f}")
            else:
                col_g1.write(f"🏆 {row['目標名']} (期限: {row['達成期限']})")
                col_g2.write(f"¥{g_amt:,.0f}")

    # --- 7. 将来シミュレーション (NISAスケジュール反映型) ---
    st.markdown("---")
    st.markdown("### 🔮 将来シミュレーション (1億円への道)")
    
    age = st.sidebar.number_input("現在年齢", 10, 100, 24)
    rate = 0.05
    if not df_params.empty:
        row = df_params[df_params['項目'].str.contains('投資年利', na=False)]
        if not row.empty: rate = pd.to_numeric(row.iloc[0]['値'], errors='coerce')

    sim_years = 40
    sim_data = []
    curr_bal = latest_asset
    
    for i in range(sim_years * 12):
        sim_date = today + relativedelta(months=i)
        
        # スケジュールに基づいた積立額の動的計算
        sim_monthly_nisa = 0
        if not df_fix.empty:
            for _, row in df_fix.iterrows():
                if '投資' in str(row.get('カテゴリ', '')) or 'NISA' in str(row['項目']):
                    s = pd.to_datetime(row['開始日']) if row.get('開始日') else datetime(2000, 1, 1)
                    e = pd.to_datetime(row['終了日']) if row.get('終了日') else datetime(2099, 12, 31)
                    if s <= sim_date <= e:
                        sim_monthly_nisa += row['金額']
        
        # 利息計算 + 積立
        curr_bal = curr_bal * (1 + rate/12) + sim_monthly_nisa
        
        if i % 12 == 0:
            sim_data.append({"Age": age + (i//12), "Asset": curr_bal})

    df_sim = pd.DataFrame(sim_data)
    fig_sim = px.line(df_sim, x="Age", y="Asset", title="推計資産推移")
    fig_sim.add_hline(y=100000000, line_dash="dash", line_color="red", annotation_text="1億円")
    st.plotly_chart(fig_sim, use_container_width=True)

if __name__ == "__main__":
    main()
