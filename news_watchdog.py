import time
import json
import requests
import os
import sys
from datetime import datetime
# 確保 bot.py 在同一目錄下，且有正確的 send_telegram_message 函數
from bot import send_telegram_message

# ================= 設定區 =================
WATCHLIST = ['HIMS', 'ZETA', 'ODDITY', 'NVDA', 'TSLA', 'AMD', 'OSCR']

# 嘗試讀取本地 .env 文件 (需要 pip install python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 從環境變數讀取 Keys (安全模式)
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

SCAN_INTERVAL = 900 
HISTORY_FILE = 'news_history.json'
# ==========================================

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                return set()
    return set()

def save_history(history_set):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(list(history_set), f)

def get_latest_news(ticker):
    if not NEWS_API_KEY:
        print(f"⚠️ 缺少 NEWS_API_KEY，跳過 {ticker}")
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
        response = requests.get(url, params=params)
        data = response.json()
        if response.status_code == 200:
            return data.get('articles', [])
        print(f"❌ NewsAPI 錯誤: {data.get('message')}")
        return []
    except Exception as e:
        print(f"❌ 抓取 {ticker} 失敗: {e}")
        return []

def analyze_news_gemini(ticker, title, description):
    """ 使用 Google Gemini 免費版進行分析 """
    if not GEMINI_API_KEY:
        print("⚠️ 未檢測到 GEMINI_API_KEY，跳過 AI 分析")
        return f"📰 {title}" 

    try:
        import google.generativeai as genai
        
        # 配置 API
        genai.configure(api_key=GEMINI_API_KEY)
        # 使用最新的 Flash 模型，速度更快
        model = genai.GenerativeModel('gemini-pro')
        
        prompt = f"""
        You are Peter Lynch. Analyze this news for stock: {ticker}.
        News: {title} - {description}
        
        Task: Is this news SIGNIFICANT for investment thesis? (Earnings, M&A, moat change)
        If YES, summarize in 1 sentence with "🚨 [URGENT]".
        If NO (noise, gossip, minor move), output "SKIP".
        """
        
        response = model.generate_content(prompt)
        return response.text.strip()
        
    except Exception as e:
        print(f"Gemini 分析失敗: {e}")
        return f"📰 {title}" # 失敗時回退到標題

def start_watchdog():
    # 判斷是否在 GitHub Actions 環境中運行
    IS_GITHUB_ACTION = os.getenv('GITHUB_ACTIONS') == 'true'
    
    mode_msg = "☁️ 雲端單次掃描模式" if IS_GITHUB_ACTION else "💻 本地循環監控模式"
    print(f"👀 Watchdog 啟動中... [{mode_msg}]")
    
    if not IS_GITHUB_ACTION:
        send_telegram_message(f"👀 新聞監控上線 ({mode_msg})")
    
    seen_urls = load_history()
    
    # 如果是 GitHub Action，只執行一次 loop 就退出 (防止超時)
    # 如果是本地，保持無限循環
    while True:
        print(f"[{datetime.now().strftime('%H:%M')}] 開始掃描...")
        
        for ticker in WATCHLIST:
            articles = get_latest_news(ticker)
            
            for article in articles:
                url = article.get('url')
                
                if url and url not in seen_urls:
                    title = article.get('title')
                    desc = article.get('description', '')
                    
                    # 使用 Gemini 分析
                    analysis = analyze_news_gemini(ticker, title, desc)
                    
                    # 過濾掉 SKIP 的新聞
                    if "SKIP" in analysis:
                        print(f"🗑️ 過濾雜訊: {title[:15]}...")
                        seen_urls.add(url)
                        continue
                        
                    # 發送警報
                    msg = f"**{ticker} 快訊**\n{analysis}\n[閱讀全文]({url})"
                    send_telegram_message(msg)
                    print(f"✅ 已推送 {ticker} 重大新聞")
                    
                    seen_urls.add(url)
            
            time.sleep(1) # 避免 API 请求過快
            
        save_history(seen_urls)
        
        if IS_GITHUB_ACTION:
            print("✅ GitHub Action 任務完成，自動退出。")
            break # 退出循環
            
        print(f"💤 休息 {SCAN_INTERVAL} 秒...")
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    start_watchdog()
