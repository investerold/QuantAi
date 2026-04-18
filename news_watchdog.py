import time
import json
import requests
import os
from datetime import datetime
from bot import send_telegram_message

# ================= 設定區 =================
WATCHLIST = ['HIMS', 'ZETA', 'ODDITY', 'NVDA', 'TSLA', 'AMD', 'OSCR']

# 你的 API Keys
NEWS_API_KEY = os.getenv('NEWS_API_KEY')  # 保持不變
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY') # 填入 AIza 開頭的 Key

SCAN_INTERVAL = 900 
# ==========================================

HISTORY_FILE = 'news_history.json'

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_history(history_set):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(list(history_set), f)

def get_latest_news(ticker):
    if not NEWS_API_KEY:
        return []
    
    # 優化過的查詢語句
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
        return []
    except Exception as e:
        print(f"❌ 抓取 {ticker} 失敗: {e}")
        return []

def analyze_news_gemini(ticker, title, description):
    """ 使用 Google Gemini 免費版進行分析 """
    if not GEMINI_API_KEY:
        return f"📰 {title}" 

    try:
        import google.generativeai as genai
        
        # 配置 API
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
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
    print(f"👀 24/7 新聞看門狗 (Gemini版) 已啟動... (每 {SCAN_INTERVAL/60} 分鐘掃描一次)")
    send_telegram_message("👀 新聞監控系統已上線！(Powered by Gemini)")
    
    seen_urls = load_history()
    
    while True:
        print(f"[{datetime.now().strftime('%H:%M')}] 開始新一輪掃描...")
        
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
                        print(f"🗑️ 過濾雜訊: {title[:20]}...")
                        seen_urls.add(url)
                        continue
                        
                    # 發送警報
                    msg = f"**{ticker} 快訊**\n{analysis}\n[閱讀全文]({url})"
                    send_telegram_message(msg)
                    print(f"✅ 已推送 {ticker} 重大新聞")
                    
                    seen_urls.add(url)
                    
            time.sleep(1)
            
        save_history(seen_urls)
        print(f"💤 休息 {SCAN_INTERVAL} 秒...")
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    start_watchdog()
