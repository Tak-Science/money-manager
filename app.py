import streamlit as st
import pandas as pd
import plotly.express as px
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime

# --- 設定 ---
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# 👇 【重要】ここにあなたのスプレッドシートのURLを貼り付けてください！
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1pb1IH1twG9XDIo6Ma88XKcndnnet-dlHxQPu9zjbJ5w/edit?gid=2102244245#gid=2102244245"

st.set_page_config(page_title="Financial Freedom Dashboard", layout="wide")

# --- 関数: スプレッドシート接続 ---
def get_spreadsheet():
    # Secretsから鍵情報だけを取得
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)
    return service.spreadsheets()

# --- 関数: データ読み込み ---
@st.cache_data(ttl=60)
def load_data():
    sheet = get_spreadsheet()
    
    # URLからIDを抽出
    try:
        spreadsheet_id = SPREADSHEET_URL.split('/d/')[1].split('/')[0]
    except:
        st.error("URLの形式がおかしいようです。正しいスプレッドシートのURLを貼り付けましたか？")
        st.stop()

    # 1. Parameters シート
    try:
        # A:D列を取得 (A:日付, B:項目, C:値, D:備考)
        res_p = sheet.values().get(spreadsheetId=spreadsheet_id, range='Parameters!A:D').execute()
        headers = res_p.get('values', [])[0]
        data = res_p.get('values', [])[1:]
        df_params = pd.DataFrame(data, columns=headers)
        
        # 数値化 & 空白除去
        if '値' in df_params.columns:
            df_params['値'] = pd.to_numeric(df_params['値'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        if '項目' in df_params.columns:
            df_params['項目'] = df_params['項目'].astype(str).str.strip() # 前後の空白を削除
    except Exception as e:
        st.error(f"Parametersシート読み込みエラー: {e}")
        df_params = pd.DataFrame()

    # 2. Fix_Cost シート（日付判定のためにG列まで取得）
    try:
        # A:G列を取得 (F:開始日, G:終了日 を想定)
        res_f = sheet.values().get(spreadsheetId=spreadsheet_id, range='Fix_Cost!A:G').execute()
        headers = res_f.get('values', [])[0]
        data = res_f.get('values', [])[1:]
        # データ数がヘッダーより少ない場合の調整
        if data:
            df_fix = pd.DataFrame(data, columns=headers)
        else:
            df_fix = pd.DataFrame(columns=headers)

        # 「金額」列を数値化
        if '金額' in df_fix.columns:
            df_fix['金額'] = pd.to_numeric(df_fix['金額'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            
    except Exception as e:
        st.error(f"Fix_Costシート読み込みエラー: {e}")
        df_fix = pd.DataFrame()

    # 3. Balance_Log シート
    try:
        res_b = sheet.values().get(spreadsheetId=spreadsheet_id, range='Balance_Log!A:Z').execute()
        headers = res_b.get('values', [])[0]
        data = res_b.get('values', [])[1:]
        df_balance = pd.DataFrame(data, columns=headers)
        
        # 数値化
        for col in df_balance.columns:
            if col != '日付':
                df_balance[col] = pd.to_numeric(df_balance[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
    except Exception as e:
        st.error(f"Balance_Logシート読み込みエラー: {e}")
        df_balance = pd.DataFrame()

    return df_params, df_fix, df_balance

# --- メイン処理 ---
def main():
    st.title("💰 Financial Freedom Dashboard v5.2")
    
    # URL未入力チェック
    if "ここに" in SPREADSHEET_URL:
        st.warning("⚠️ コードの12行目に、スプレッドシートのURLを貼り付けてください！")
        st.stop()

    # データ読み込み
    df_params, df_fix, df_balance = load_data()

    if df_params.empty:
        st.warning("データを読み込めませんでした。")
        st.stop()

    # --- 1. 基本データの抽出 ---
    
    # 月収 (Parametersから取得)
    monthly_income = 0
    if '項目' in df_params.columns:
        # "月収" を探す
        income_row = df_params[df_params['項目'] == '月収']
        if not income_row.empty:
            monthly_income = income_row['値'].values[0]
        else:
            # なければ "年収" を探して12で割る
            income_row_y = df_params[df_params['項目'] == '年収']
            if not income_row_y.empty:
                monthly_income = income_row_y['値'].values[0] / 12

    # 現在資産
    current_asset = 0
    if not df_balance.empty:
        numeric_cols = [c for c in df_balance.columns if c != '日付']
        current_asset = df_balance.iloc[-1][numeric_cols].sum()
    else:
        if '項目' in df_params.columns:
            asset_row = df_params[df_params['項目'] == '現在資産']
            if not asset_row.empty:
                current_asset = asset_row['値'].values[0]

    # --- 固定費の日付フィルタリング ---
    # 今日の日付
    today = datetime.now()
    
    # 有効な固定費だけを抽出するリスト
    valid_costs = []
    
    if not df_fix.empty:
        # 開始日・終了日カラムがあるか確認（なければ全件対象）
        has_start = '開始日' in df_fix.columns
        has_end = '終了日' in df_fix.columns
        
        for index, row in df_fix.iterrows():
            is_valid = True
            
            # 開始日チェック
            if has_start and row['開始日'] and str(row['開始日']).strip() != '':
                try:
                    start_date = pd.to_datetime(row['開始日'])
                    if today < start_date:
                        is_valid = False
                except:
                    pass # 日付形式がおかしい場合は無視して有効とする

            # 終了日チェック
            if has_end and row['終了日'] and str(row['終了日']).strip() != '':
                try:
                    end_date = pd.to_datetime(row['終了日'])
                    if today > end_date:
                        is_valid = False
                except:
                    pass

            if is_valid:
                valid_costs.append(row)
    
    # データフレームに変換し直して合計
    if valid_costs:
        df_fix_valid = pd.DataFrame(valid_costs)
        monthly_fixed_cost = df_fix_valid['金額'].sum()
    else:
        monthly_fixed_cost = 0


    # 生活防衛費係数
    defense_months = 6
    if '項目' in df_params.columns:
        row = df_params[df_params['項目'] == '生活防衛費係数']
        if not row.empty:
            defense_months = row['値'].values[0]

    # --- 2. 計算 ---

    # 簡易手取り (★ご希望通り 税金20%を引く計算を残しました)
    net_income = monthly_income * 0.8 
    
    # 自由資金 (手取り - 固定費)
    free_cash = net_income - monthly_fixed_cost
    
    # 生活防衛費目標
    target_defense = (monthly_fixed_cost + 50000) * defense_months

    # --- 3. 表示 ---

    st.sidebar.header("⚙️ Settings")
    current_age = st.sidebar.number_input("Age", 20, 60, 24)
    retire_age = st.sidebar.slider("FIRE Age", 30, 65, 45)

    # KPI表示
    st.markdown("### 📊 Monthly Status")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("月収 (額面)", f"¥{monthly_income:,.0f}")
    c2.metric("固定費合計 (今月分)", f"¥{monthly_fixed_cost:,.0f}", delta_color="inverse")
    c3.metric("手取り (概算)", f"¥{net_income:,.0f}")
    
    if free_cash >= 0:
        c4.metric("🔥 自由資金", f"¥{free_cash:,.0f}", delta=f"{(free_cash/net_income)*100:.1f}%")
    else:
        c4.metric("🔥 自由資金", f"¥{free_cash:,.0f}", delta="赤字です！", delta_color="inverse")

    # 赤字警告の詳細
    if free_cash < 0:
        st.error(f"今月は **¥{abs(free_cash):,.0f}** の赤字予測です。（手取り ¥{net_income:,.0f} - 固定費 ¥{monthly_fixed_cost:,.0f}）")

    st.markdown("---")

    # 生活防衛費
    st.markdown(f"### 🛡️ 生活防衛費 (Target: {defense_months}ヶ月分)")
    if target_defense > 0:
        progress = min(current_asset / target_defense, 1.0)
    else:
        progress = 0
    
    st.progress(progress)
    st.caption(f"Current: ¥{current_asset:,.0f} / Target: ¥{target_defense:,.0f}")
    
    if progress < 1.0:
        st.warning(f"あと ¥{target_defense - current_asset:,.0f} 必要です")
    else:
        st.success("✅ 生活防衛費 クリア！")

    st.markdown("---")

    # グラフ描画
    if not df_balance.empty:
        st.markdown("### 📈 資産推移")
        df_balance['日付'] = pd.to_datetime(df_balance['日付'])
        numeric_cols = [c for c in df_balance.columns if c != '日付']
        st.plotly_chart(px.area(df_balance, x='日付', y=numeric_cols), use_container_width=True)

    # シミュレーション
    st.markdown("### 🔮 将来シミュレーション")
    years = retire_age - current_age
    data = []
    bal = current_asset
    rate = 0.05
    if '項目' in df_params.columns:
        r_row = df_params[df_params['項目'] == '投資年利']
        if not r_row.empty:
            rate = r_row['値'].values[0]

    monthly_save = max(0, free_cash)

    for y in range(years + 1):
        data.append({"Age": current_age + y, "Asset": bal})
        bal = bal * (1 + rate) + (monthly_save * 12)
    
    fig = px.line(pd.DataFrame(data), x="Age", y="Asset", title=f"毎月 ¥{monthly_save:,.0f} 積立 (年利 {rate*100}%)")
    fig.add_hline(y=100000000, line_dash="dash", line_color="red")
    st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()
