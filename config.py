# config.py
# ==================================================
# 設定・定数ファイル
# ==================================================

# Google Sheets 設定
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1pb1IH1twG9XDIo6Ma88XKcndnnet-dlHxQPu9zjbJ5w/edit?gid=2102244245#gid=2102244245"

# Goals 距離分類
NEAR_YEARS = 2
MID_YEARS = 5

# 距離係数
DIST_COEF = {
    "near": 1.0,
    "mid": 0.5,
    "long": 0.2,
}

# 状態係数（生活防衛費未達のみ 1.2）
STATE_COEF_EMERGENCY_NOT_MET = 1.2

# KPI / カテゴリ定義
EXPENSE_CATEGORIES = [
    "食費（外食・交際）",
    "食費（日常）",
    "趣味・娯楽",
    "研究・書籍",
    "日用品",
    "交通費",
    "衣料品",
    "特別費",
    "その他",
]
INCOME_CATEGORIES = ["給与・バイト代", "臨時収入"]
