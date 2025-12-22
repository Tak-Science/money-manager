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

# 距離係数（学生モード）
DIST_COEF = {
    "near": 1.0,
    "mid": 0.2,
    "long": 0.05,
}

# 状態係数
STATE_COEF_EMERGENCY_NOT_MET = 1.2

# ==================================================
# 聖域（ミニマム積立）設定
# ==================================================
MIN_NISA_AMOUNT = 3000
MIN_BANK_AMOUNT = 5000

# ==================================================
# 緑色の余剰（安心バッファ）の設定 (NEW)
# ==================================================
# 生活防衛費（黄色）とは別に、普通口座に持っておく「運転資金」
# 「普段より出費が多い月（P75）」の何ヶ月分を持つか？
BANK_GREEN_BUFFER_MONTHS = 3.5

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
