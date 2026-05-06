
import time
import json
import requests
import os
from datetime import datetime
from bot import send_telegram_message

# ================= 設定區 =================
WATCHLIST = ['HIMS', 'ZETA', 'ODDITY', 'NVDA', 'TSLA', 'AMD', 'OSCR']
# ... (以下保留原本 v3 版本的代碼不變)


import time
import json
import requests
import os
from datetime import datetime
from bot import send_telegram_message

# ================= 設定區 =================
WATCHLIST = ['HIMS', 'ZETA', 'ODDITY', 'NVDA', 'TSLA', 'AMD', 'OSCR']

# 你的 API Keys
NEWS_API_KEY = os.getenv('NEWS_API_KEY')  
# 這是你的新 Gemini Key
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# 新聞掃描間隔 (避免觸發 News API 的 Rate Limit，建議最少保持 15 分鐘 / 900 秒)
SCAN_INTERVAL = 900 
# ==========================================

HISTORY_FILE = 'news_history.json'

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    return set()

def save_history(history_set):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(history_set), f, ensure_ascii=False, indent=4)

def get_latest_news(ticker):
    """
    抓取特定股票的最新新聞，過濾較舊或不相關內容
    """
    if not NEWS_API_KEY:
        return []
    
    url = "https://newsapi.org/v2/everything"
    params = {
        'q': f'("{ticker}" AND "stock") OR ("{ticker}" AND "earnings") OR ("{ticker}" AND "revenue")',
        'sortBy': 'publishedAt',
        'language': 'en',
        'pageSize': 3,
        'apiKey': NEWS_API_KEY
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if response.status_code == 200:
            return data.get('articles', [])
        else:
            print(f"❌ [News API] 抓取 {ticker} 失敗: {data.get('message', '未知錯誤')}")
            return []
    except requests.exceptions.RequestException as e:
        print(f"❌ [網絡錯誤] 抓取 {ticker} 失敗: {e}")
        return []

def analyze_news_gemini(ticker, title, description):
    """ 
    使用最新版本的 Google Gemini 2.0 Flash 進行投資分析
    注意：已遷移至全新的 google.genai SDK
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == '在此填入你的新_API_KEY':
        return "SKIP"

    try:
        # 新版 SDK 的引入方式
        from google import genai
        
        # 配置 API - 新版寫法使用 Client() 初始化
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        prompt = f"""
        請以彼得·林區 (Peter Lynch) 結合 GARP (合理價格成長) 的投資哲學，分析以下 {ticker} 的新聞：
        新聞標題：{title} 
        新聞摘要：{description}
        
        任務：
        1. 判斷此新聞是否對投資基本面有「重大影響」(如：財報超預期、重大併購、護城河改變等)。
        2. 如果「有重大影響」(YES)：請用 1-2 句話精確總結影響，並加上 "🚨 [核心觸發]"。
        3. 如果「沒有重大影響」(NO)：包含市場噪音、小道消息、日常股價波動等，請只輸出 "SKIP"。
        
        請用繁體中文回答。
        """
        
        # 新版 SDK 的請求寫法
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
        )
        
        return response.text.strip()
        
    except Exception as e:
        error_msg = f"⚠️ [Gemini API] 分析失敗: {e}"
        print(error_msg)
        
        # 發生錯誤時回傳 SKIP，避免推送未分析的雜訊
        return "SKIP"

def format_telegram_message(ticker, analysis, url):
    """ 格式化 Telegram 訊息，優化 UI 與可讀性 """
    if "財報" in analysis or "earnings" in analysis.lower():
        emoji = "📊"
    elif "併購" in analysis or "收購" in analysis:
        emoji = "🤝"
    else:
        emoji = "⚡"
        
    msg = (
        f"*{emoji} {ticker} 投資快訊*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{analysis}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔗 [點擊閱讀完整報導]({url})"
    )
    return msg

def start_watchdog():
    print(f"👀 新聞看門狗 (GitHub Actions 版) 開始執行單次掃描...")
    
    seen_urls = load_history()
    
    for ticker in WATCHLIST:
        articles = get_latest_news(ticker)
        
        for article in articles:
            url = article.get('url')
            
            if url and url not in seen_urls:
                title = article.get('title')
                desc = article.get('description', '')
                    
                analysis = analyze_news_gemini(ticker, title, desc)
                
                if "SKIP" in analysis:
                    print(f"🗑️ 過濾雜訊: {ticker} - {title[:25]}...")
                    seen_urls.add(url)
                    continue
                    
                msg = format_telegram_message(ticker, analysis, url)
                send_telegram_message(msg)
                print(f"✅ 已推送 {ticker} 重大新聞！")
                
                seen_urls.add(url)
                
        # 避免 API 請求過快
        time.sleep(2)
        
    save_history(seen_urls)
    print("🏁 單次掃描完成，程式結束。")

if __name__ == "__main__":
    start_watchdog()

if __name__ == "__main__":
    try:
        start_watchdog()
    except KeyboardInterrupt:
        print("\n🛑 系統已手動停止。")
        send_telegram_message("🔴 *系統通知*\n新聞監控系統已停止。")
