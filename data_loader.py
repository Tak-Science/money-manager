import streamlit as st
import pandas as pd
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# 先ほど作った設定ファイルを読み込みます
import config

# ==================================================
# Google Sheets 接続
# ==================================================
def get_spreadsheet():
    """Google Sheets APIに接続するサービスを作成します"""
    # secretsはStreamlitの機能で読み込み、SCOPESはconfigから読み込みます
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=config.SCOPES)
    service = build("sheets", "v4", credentials=creds)
    return service.spreadsheets()

# ==================================================
# データ読み込み（堅牢版）
# ==================================================
@st.cache_data(ttl=60)
def load_data():
    """スプレッドシートから全シートのデータを読み込みます"""
    sheet = get_spreadsheet()
    # configからURLを取得してIDを抽出
    spreadsheet_id = config.SPREADSHEET_URL.split("/d/")[1].split("/")[0]

    def get_df(sheet_name, range_):
        try:
            res = sheet.values().get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!{range_}").execute()
            values = res.get("values", [])
            
            if not values:
                return pd.DataFrame()

            # データの「歯抜け」を補正する処理
            header = values[0]       # 1行目（見出し）
            data = values[1:]        # 2行目以降（中身）
            n_cols = len(header)     # 見出しの列数

            # データ行の長さが足りない場合、Noneで埋めて長さを揃える
            fixed_data = [row + [None] * (n_cols - len(row)) for row in data]

            return pd.DataFrame(fixed_data, columns=header)
            
        except Exception as e:
            st.error(f"❌ シート「{sheet_name}」読み込みエラー: {e}")
            return pd.DataFrame()

    # 各シートを読み込み
    df_params  = get_df("Parameters",       "A:D")
    df_fix     = get_df("Fix_Cost",         "A:G")
    df_forms   = get_df("Forms_Log",        "A:G")
    df_balance = get_df("Balance_Log",      "A:C")
    df_goals   = get_df("Goals",            "A:Z") 
    df_goals_log = get_df("Goals_Save_Log","A:D")

    return df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log

# ==================================================
# 前処理（型整形）
# ==================================================
def preprocess_data(df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log):
    """読み込んだデータの型（日付や数値）を整えます"""
    
    # Parameters
    if not df_params.empty and "適用開始日" in df_params.columns:
        df_params["適用開始日"] = pd.to_datetime(df_params["適用開始日"], errors="coerce")

    # Fix_Cost
    if not df_fix.empty:
        if "開始日" in df_fix.columns:
            df_fix["開始日"] = pd.to_datetime(df_fix["開始日"], errors="coerce")
        if "終了日" in df_fix.columns:
            df_fix["終了日"] = pd.to_datetime(df_fix["終了日"], errors="coerce")
        if "金額" in df_fix.columns:
            df_fix["金額"] = pd.to_numeric(df_fix["金額"], errors="coerce").fillna(0)
        if "サイクル" in df_fix.columns:
            df_fix["サイクル"] = df_fix["サイクル"].fillna("毎月")

    # Forms_Log
    if not df_forms.empty:
        if "日付" in df_forms.columns:
            df_forms["日付"] = pd.to_datetime(df_forms["日付"], errors="coerce")
        if "金額" in df_forms.columns:
            df_forms["金額"] = pd.to_numeric(df_forms["金額"], errors="coerce").fillna(0)
        if "満足度" in df_forms.columns:
            df_forms["満足度"] = pd.to_numeric(df_forms["満足度"], errors="coerce")
        
        if "費目" in df_forms.columns:
            df_forms["費目"] = df_forms["費目"].astype(str).str.strip()

    # Balance_Log
    if not df_balance.empty:
        if "日付" in df_balance.columns:
            df_balance["日付"] = pd.to_datetime(df_balance["日付"], errors="coerce")
        if "銀行残高" in df_balance.columns:
            df_balance["銀行残高"] = pd.to_numeric(df_balance["銀行残高"], errors="coerce")
        if "NISA評価額" in df_balance.columns:
            df_balance["NISA評価額"] = pd.to_numeric(df_balance["NISA評価額"], errors="coerce")

    # Goals
    if df_goals is not None and (not df_goals.empty):
        df_goals.columns = df_goals.columns.str.strip()

        if "達成期限" in df_goals.columns:
            df_goals["達成期限"] = pd.to_datetime(df_goals["達成期限"], errors="coerce")
        
        if "金額" in df_goals.columns:
            df_goals["金額"] = df_goals["金額"].astype(str).str.replace(",", "").str.replace("¥", "").str.replace("円", "")
            df_goals["金額"] = pd.to_numeric(df_goals["金額"], errors="coerce")

        if "支払済" in df_goals.columns:
            df_goals["支払済"] = df_goals["支払済"].astype(str).str.strip().str.upper() == "TRUE"
        else:
            df_goals["支払済"] = False

    # Goals_Save_Log（実績）
    if df_goals_log is not None and (not df_goals_log.empty):
        if "月" in df_goals_log.columns:
            def parse_month(x):
                s = str(x).strip()
                if re.match(r"^\d{4}-\d{2}$", s):
                    s = s + "-01"
                return pd.to_datetime(s, errors="coerce")
            df_goals_log["月_dt"] = df_goals_log["月"].apply(parse_month)
        elif "日付" in df_goals_log.columns:
            df_goals_log["月_dt"] = pd.to_datetime(df_goals_log["日付"], errors="coerce")
        else:
            df_goals_log["月_dt"] = pd.NaT

        if "積立額" in df_goals_log.columns:
            df_goals_log["積立額"] = pd.to_numeric(df_goals_log["積立額"], errors="coerce").fillna(0)
        else:
            df_goals_log["積立額"] = 0.0

    return df_params, df_fix, df_forms, df_balance, df_goals, df_goals_log
