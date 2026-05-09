import time
import json
import requests
import os
from datetime import datetime
from bot import send_telegram_message

# ================= 設定區 =================
WATCHLIST = {
    "HIMS": ['"Hims & Hers"', '"HIMS"'],
    "ZETA": ['"Zeta Global"', '"ZETA"'],
    "ODDITY": ['"Oddity Tech"', '"ODD"'],
    "NVDA": ['"NVIDIA"', '"NVDA"'],
    "TSLA": ['"Tesla"', '"TSLA"'],
    "AMD": ['"Advanced Micro Devices"', '"AMD"'],
    "OSCR": ['"Oscar Health"', '"OSCR"']
}

NEWS_API_KEY = os.getenv('NEWS_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_MODEL = 'gemini-2.5-flash-lite'

HISTORY_FILE = 'news_history.json'

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    return set()

def save_history(history_set):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(history_set), f, ensure_ascii=False, indent=4)

def get_latest_news(ticker, aliases):
    if not NEWS_API_KEY:
        return []
    
    # 放寬條件：只要有提到公司名或 Ticker 就抓取（不做嚴格事件過濾）
    query_string = " OR ".join(aliases)
    
    url = "https://newsapi.org/v2/everything"
    params = {
        'q': query_string,
        'sortBy': 'publishedAt',
        'language': 'en',
        'pageSize': 3,  # 每個標的最多抓取最新 3 條，避免 API 或 Token 超載
        'apiKey': NEWS_API_KEY
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if response.status_code == 200:
            return data.get('articles', [])
        
        if response.status_code == 429:
            print("❌ [News API] 配額已耗盡，請檢查方案。")
        else:
            print(f"❌ [News API] 抓取 {ticker} 失敗: {data.get('message', '未知錯誤')}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"❌ [網絡錯誤] 抓取 {ticker} 失敗: {e}")
        return []

# 主程式 (news_watchdog.py) 中的這兩個函數替換掉：

def analyze_news_gemini(ticker, title, description):
    if not GEMINI_API_KEY:
        print("⚠️ [系統] 未偵測到 GEMINI_API_KEY，跳過分析。")
        return "SKIP"

    try:
        from google import genai
    except ImportError:
        print("⚠️ 請先安裝: pip install google-genai")
        return "SKIP"

    prompt = f"""
    你是專注於 GARP 策略 (彼得·林區風格) 與期權賣方策略的金融分析師。
    請分析以下 {ticker} 的新聞：
    標題：{title} 
    摘要：{description}
    
    任務：
    1. 判斷此新聞是否包含「值得關注的商業發展」或「基本面變化」。
    2. 如果「有」，請嚴格按照以下格式回覆（請勿加上任何 Markdown 符號或 Markdown 代碼塊）：
       [情緒] (請填寫：🟢利好 / 🔴利空 / ⚪中性)
       [總結] (用 1-2 句繁體中文精確總結，並點出對公司護城河或波動率的潛在影響)
    3. 如果「完全無關」(例如純粹市場雜訊、廣告)，請直接輸出 "SKIP"。
    """

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        return response.text.strip()
        
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg:
            print(f"⏳ [Gemini API] 觸發限制，等待後重試...")
            time.sleep(3)
        else:
            print(f"⚠️ [Gemini API] 分析失敗: {error_msg}")
        return "SKIP"

def format_telegram_message(ticker, analysis, url):
    """ 使用 HTML 排版，打造專業金融快訊 UI """
    
    # 預設變數
    sentiment_icon = "💡" 
    summary = analysis
    
    # 解析 Gemini 吐出來的情緒標籤
    lines = analysis.split('\\n')
    for line in lines:
        if line.startswith('[情緒]'):
            sentiment_part = line.replace('[情緒]', '').strip()
            # 抓取第一顆表情符號當大標題的 Icon
            if '🟢' in sentiment_part:
                sentiment_icon = "🟢"
            elif '🔴' in sentiment_part:
                sentiment_icon = "🔴"
            elif '⚪' in sentiment_part:
                sentiment_icon = "⚪"
        elif line.startswith('[總結]'):
            summary = line.replace('[總結]', '').strip()

    # 如果 Gemini 沒有完全遵守格式，就回退使用整段文字
    if summary == analysis:
        summary = analysis.replace('[情緒]', '').replace('[總結]', '').strip()

    # 專業 HTML 排版 (不再有討厭的下劃線跟反斜線)
    msg = (
        f"<b>{sentiment_icon} {ticker} 投資快訊</b>\\n"
        f"━━━━━━━━━━━━━━━\\n"
        f"<i>{summary}</i>\\n"
        f"━━━━━━━━━━━━━━━\\n"
        f"🔗 <a href='{url}'>點擊閱讀完整原文</a>"
    )
    return msg

def start_watchdog():
    print(f"👀 新聞看門狗開始執行掃描...")
    seen_urls = load_history()
    
    # 用來記錄哪些標的「真的有推送新聞」，哪些「沒有更新」
    tickers_with_updates = set()
    
    for ticker, aliases in WATCHLIST.items():
        articles = get_latest_news(ticker, aliases)
        
        for article in articles:
            url = article.get('url')
            if not url or url in seen_urls:
                continue

            title = article.get('title') or ''
            desc = article.get('description', '') or ''
            
            analysis = analyze_news_gemini(ticker, title, desc)
            
            if analysis == "SKIP" or "SKIP" in analysis.upper():
                print(f"🗑️ 過濾雜訊: {ticker} - {title[:25]}...")
                seen_urls.add(url)
                continue
                
            msg = format_telegram_message(ticker, analysis, url)
            send_telegram_message(msg)
            print(f"✅ 已推送 {ticker} 新聞！")
            
            seen_urls.add(url)
            tickers_with_updates.add(ticker)
                
        time.sleep(3)
        
    save_history(seen_urls)
    
    # ==== 掃描結束：總結「無新聞」名單（Heartbeat） ====
    all_tickers = set(WATCHLIST.keys())
    no_update_tickers = all_tickers - tickers_with_updates
    
    if no_update_tickers:
        no_news_msg = (
            f"📭 *掃描完成：本日以下標的無新動態*\\n"
            f"━━━━━━━━━━━━━━━\\n"
            f"{', '.join(sorted(no_update_tickers))}\\n"
            f"*(系統正常運作中，未發現上述股票的相關新聞)*"
        )
        send_telegram_message(no_news_msg)
        print("✅ 已推送無更新名單總結")

    print("🏁 單次掃描完成，程式結束。")

if __name__ == "__main__":
    start_watchdog()
