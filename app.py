import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import datetime
import plotly.graph_objects as go
import plotly.express as px
from dateutil.relativedelta import relativedelta

# --- ⚙️ 設定エリア ---
# ★重要: GitHubには絶対にIDやパスワードを直接書かないこと！
# Cloudで動くときは st.secrets から読み込みます
SPREADSHEET_KEY = '1pb1IH1twG9XDIo6Ma88XKcndnnet-dlHxQPu9zjbJ5w' 

# 基本設定
BIRTH_YEAR = 2004 
BIRTH_MONTH = 3   

st.set_page_config(page_title="Financial Freedom Dashboard", layout="wide")

# --- 🔌 データベース接続 (クラウド対応版) ---
@st.cache_resource
def get_spreadsheet():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    
    # ロジック: クラウドの「秘密の金庫」に鍵があるか確認し、なければ手元のファイルを探す
    if "gcp_service_account" in st.secrets:
        # Cloud上の場合
        creds_dict = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    else:
        # ローカルPCの場合
        try:
            creds = Credentials.from_service_account_file("service_account.json", scopes=scope)
        except:
            st.error("鍵ファイルが見つかりません！")
            st.stop()
            
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_KEY)

# --- 以下、前回の load_data 以降と同じ ---
def load_data():
    sh = get_spreadsheet()
    # ... (ここから下は変更ありません。前回のコードのままです)
    # ※もし貼り付けが面倒であれば、load_data以降は前回のコードをコピーして貼り付けてください
    try:
        df_params = pd.DataFrame(sh.worksheet('Parameters').get_all_records())
        df_fix = pd.DataFrame(sh.worksheet('Fix_Cost').get_all_records())
        
        try:
            df_balance = pd.DataFrame(sh.worksheet('Balance_Log').get_all_records())
            if not df_balance.empty:
                df_balance['日付'] = pd.to_datetime(df_balance['日付'], errors='coerce')
                cols = ['銀行残高', 'NISA評価額']
                for col in cols:
                    if col not in df_balance.columns: df_balance[col] = 0
                    df_balance[col] = pd.to_numeric(df_balance[col], errors='coerce')
                df_balance = df_balance.ffill().fillna(0)
        except:
            df_balance = pd.DataFrame(columns=['日付', '銀行残高', 'NISA評価額'])

        try:
            df_goals = pd.DataFrame(sh.worksheet('Goals').get_all_records())
            if 'タイプ' not in df_goals.columns: df_goals['タイプ'] = '目標'
        except:
            df_goals = pd.DataFrame(columns=['目標名', '金額', '達成期限', 'タイプ'])

        try:
            df_log = pd.DataFrame(sh.worksheet('Forms_Log').get_all_records())
            if not df_log.empty:
                if 'タイムスタンプ' in df_log.columns: ts_col = 'タイムスタンプ'
                elif 'Timestamp' in df_log.columns: ts_col = 'Timestamp'
                else: ts_col = None

                if '日付' not in df_log.columns: df_log['日付'] = pd.NaT
                else: df_log['日付'] = pd.to_datetime(df_log['日付'], errors='coerce')

                if ts_col:
                    df_log[ts_col] = pd.to_datetime(df_log[ts_col], errors='coerce')
                    df_log['日付'] = df_log['日付'].fillna(df_log[ts_col])
                
                df_log['金額'] = pd.to_numeric(df_log['金額'], errors='coerce').fillna(0)
        except:
            df_log = pd.DataFrame(columns=['日付', '金額', '費目', 'カテゴリ'])
            
    except Exception as e:
        st.error(f"データ読み込みエラー: {e}")
        st.stop()
    return df_params, df_fix, df_log, df_goals, df_balance

def calculate_budget(df_params, df_fix, df_log):
    today = datetime.date.today()
    df_params['適用開始日'] = pd.to_datetime(df_params['適用開始日'])
    valid_params = df_params[df_params['適用開始日'].dt.date <= today].sort_values('適用開始日')
    
    try: yearly_income = float(valid_params[valid_params['項目'] == '年収'].iloc[-1]['値'])
    except: yearly_income = 0
    monthly_income_est = yearly_income / 12
    
    try: current_asset = float(valid_params[valid_params['項目'] == '現在資産'].iloc[-1]['値'])
    except: current_asset = 0
    
    try: defense_months = float(valid_params[valid_params['項目'] == '生活防衛費係数'].iloc[-1]['値'])
    except: defense_months = 6

    active_fix = df_fix[
        (pd.to_datetime(df_fix['開始日']).dt.date <= today) &
        ((df_fix['終了日'] == "") | (pd.to_datetime(df_fix['終了日']).dt.date > today))
    ]
    monthly_fix_total = 0
    defense_cost_base = 0 
    for _, row in active_fix.iterrows():
        amt = float(row['金額'])
        if row['サイクル'] == '毎月':
            monthly_fix_total += amt
            defense_cost_base += amt
        elif row['サイクル'] == '毎年':
            monthly_fix_total += amt / 12
            defense_cost_base += amt / 12

    current_log = df_log[
        (df_log['日付'].dt.year == today.year) & 
        (df_log['日付'].dt.month == today.month)
    ]
    actual_income = current_log[current_log['費目'].isin(['給与・バイト代', '臨時収入'])]['金額'].sum()
    actual_spend = current_log[~current_log['費目'].isin(['給与・バイト代', '臨時収入'])]['金額'].sum()
    
    defense_cost_base += (actual_spend * 1.2) 
    target_defense = defense_cost_base * defense_months
    
    base_money = max(monthly_income_est, actual_income)
    remaining = base_money - monthly_fix_total - actual_spend
    
    if remaining < 0:
        to_bank = 0; to_invest = 0; to_free = 0
        status_msg = f"⚠️ 赤字です！ {abs(remaining):,}円 の超過です。"
    else:
        defense_gap = target_defense - current_asset
        to_bank = remaining * 0.5 if defense_gap > 0 else 0
        remaining_after_bank = remaining - to_bank
        to_invest = remaining_after_bank * 0.6
        to_free = remaining_after_bank * 0.4
        status_msg = "✅ 予算内です。積立を行いましょう。"
    
    return {
        '予測月収': int(monthly_income_est),
        '実績収入': int(actual_income),
        '固定費': int(monthly_fix_total),
        '変動費実績': int(actual_spend),
        '銀行積立推奨': int(to_bank),
        '投資推奨': int(to_invest),
        '自由費': int(to_free),
        '防衛費目標': int(target_defense),
        '現在資産': int(current_asset),
        'メッセージ': status_msg,
        'ログデータ': current_log
    }

def calculate_future_asset(df_params, df_fix, df_goals, end_age):
    df_params['適用開始日'] = pd.to_datetime(df_params['適用開始日'])
    start_date = datetime.date.today().replace(day=1)
    target_date = datetime.date(BIRTH_YEAR + end_age, BIRTH_MONTH, 1)
    
    months = (target_date.year - start_date.year) * 12 + (target_date.month - start_date.month)
    if months < 0: months = 0
    results = []
    
    try: current_asset = float(df_params[df_params['項目'] == '現在資産'].iloc[-1]['値'])
    except: current_asset = 0
    asset = current_asset
    current_date = start_date
    
    expense_events = df_goals[df_goals['タイプ'] == '支出'].copy()
    if not expense_events.empty:
        expense_events['達成期限'] = pd.to_datetime(expense_events['達成期限'])

    for _ in range(months + 1):
        valid_params = df_params[df_params['適用開始日'].dt.date <= current_date]
        try: income = float(valid_params[valid_params['項目'] == '年収'].iloc[-1]['値']) / 12
        except: income = 0
        try: rate = float(valid_params[valid_params['項目'] == '投資年利'].iloc[-1]['値']) / 12
        except: rate = 0
        
        active_fix = df_fix[
            (pd.to_datetime(df_fix['開始日']).dt.date <= current_date) &
            ((df_fix['終了日'] == "") | (pd.to_datetime(df_fix['終了日']).dt.date > current_date))
        ]
        
        total_expense = 0; fixed_invest = 0    
        for _, row in active_fix.iterrows():
            val = float(row['金額'])
            if row['サイクル'] == '毎年': val = val / 12
            cat = str(row['カテゴリ'])
            if '投資' in cat or '貯金' in cat or 'NISA' in cat: fixed_invest += val
            else: total_expense += val
            
        net_saving = income - total_expense
        asset = (asset + net_saving) * (1 + rate)
        
        if not expense_events.empty:
            events_this_month = expense_events[
                (expense_events['達成期限'].dt.year == current_date.year) &
                (expense_events['達成期限'].dt.month == current_date.month)
            ]
            for _, event in events_this_month.iterrows():
                asset -= float(event['金額'])
        
        results.append({'年月': current_date, '総資産': int(asset)})
        current_date += relativedelta(months=1)
        
    return pd.DataFrame(results)

def main():
    st.title("💰 Financial Freedom Dashboard v5.1")
    
    st.sidebar.header("🔧 表示設定")
    if st.sidebar.button('データを更新する'):
        st.cache_resource.clear()
        st.rerun()
    
    sim_age = st.sidebar.slider("シミュレーション終了年齢", 30, 100, 40)
    
    with st.spinner('データ分析中...'):
        df_params, df_fix, df_log, df_goals, df_balance = load_data()
        budget = calculate_budget(df_params, df_fix, df_log)
        df_future = calculate_future_asset(df_params, df_fix, df_goals, sim_age)
    
    st.header("📅 今月のマネー配分")
    if "⚠️" in budget['メッセージ']: st.error(budget['メッセージ'])
    else: st.success(budget['メッセージ'])

    c1, c2, c3 = st.columns(3)
    c1.info(f"🏦 **銀行へ貯金**\n\n### {budget['銀行積立推奨']:,} 円")
    c2.success(f"📈 **NISA/投資へ**\n\n### {budget['投資推奨']:,} 円")
    c3.warning(f"🍺 **自由費(遊び)**\n\n### {budget['自由費']:,} 円")

    st.divider()
    st.subheader("🧐 今月の支出分析")
    
    log_df = budget['ログデータ']
    if not log_df.empty:
        expense_df = log_df[~log_df['費目'].isin(['給与・バイト代', '臨時収入'])]
        if not expense_df.empty:
            col_chart, col_data = st.columns([1, 1])
            with col_chart:
                fig_pie = px.pie(expense_df, values='金額', names='費目', 
                                 title='何に使った？（カテゴリ割合）', hole=0.4)
                st.plotly_chart(fig_pie, use_container_width=True)
            with col_data:
                st.write("**▼ 最近の出費リスト**")
                st.dataframe(expense_df[['日付', '費目', '金額', 'メモ']].sort_values('日付', ascending=False), hide_index=True)
                st.info("💡 **節約のヒント:** 固定費以外の「費目」で、削れそうなものはありませんか？")
        else:
            st.info("今月の支出データはまだありません。")
    else:
        st.info("データがありません。")

    st.divider()
    st.header("📊 実際の資産推移 (Balance Log)")
    period_opt = st.radio("表示期間:", ["全期間", "最近3ヶ月", "最近6ヶ月"], horizontal=True)
    if not df_balance.empty:
        plot_df = df_balance.copy()
        if period_opt == "最近3ヶ月":
            start_dt = pd.Timestamp.now() - pd.DateOffset(months=3)
            plot_df = plot_df[plot_df['日付'] >= start_dt]
        elif period_opt == "最近6ヶ月":
            start_dt = pd.Timestamp.now() - pd.DateOffset(months=6)
            plot_df = plot_df[plot_df['日付'] >= start_dt]

        fig_bal = px.area(plot_df, x='日付', y=['銀行残高', 'NISA評価額'], 
                          title="資産の内訳推移", color_discrete_sequence=['#636EFA', '#00CC96'])
        fig_bal.update_traces(mode='lines+markers') 
        st.plotly_chart(fig_bal, use_container_width=True)
    else:
        st.info("Balance_Log シートにデータを入力すると、ここに実績グラフが表示されます。")

    st.divider()
    st.header(f"🚀 {sim_age}歳までの資産推移シミュレーション")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_future['年月'], y=df_future['総資産'],
                             mode='lines', name='予測資産', line=dict(color='#00CC96', width=3)))
    if not df_goals.empty:
        for _, row in df_goals.iterrows():
            target_val = float(row['金額'])
            target_date = pd.to_datetime(row['達成期限'])
            if df_future['年月'].min() <= target_date.date() <= df_future['年月'].max():
                if row.get('タイプ') == '支出':
                    fig.add_trace(go.Scatter(x=[target_date], y=[target_val],
                        mode='markers+text', name=f"支出: {row['目標名']}",
                        text=[f"💸{row['目標名']}"], textposition="bottom center",
                        marker=dict(size=12, symbol='triangle-down', color='red')))
                else:
                    fig.add_shape(type="line", x0=df_future['年月'].iloc[0], x1=target_date,
                        y0=target_val, y1=target_val, line=dict(color="orange", width=1, dash="dot"))
                    fig.add_trace(go.Scatter(x=[target_date], y=[target_val],
                        mode='markers+text', name=f"目標: {row['目標名']}",
                        text=[f"🚩{row['目標名']}"], textposition="top left",
                        marker=dict(size=10, color='orange')))

    st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()