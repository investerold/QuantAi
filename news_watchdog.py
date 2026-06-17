import time
import json
import os
import yfinance as yf
from datetime import datetime
from bot import send_telegram_message

# ================= 設定區 =================
# 已移除清倉的 NVDA 與 AMD
WATCHLIST = {
    "HIMS": ['"Hims & Hers"', '"HIMS"'],
    "ZETA": ['"Zeta Global"', '"ZETA"'],
    "ODDITY": ['"Oddity Tech"', '"ODD"'],
    "TSLA": ['"Tesla"', '"TSLA"'],
    "OSCR": ['"Oscar Health"', '"OSCR"']
}

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
    """ 使用 yfinance 精準抓取 Ticker 綁定新聞，過濾非相關雜訊 """
    try:
        stock = yf.Ticker(ticker)
        news_items = stock.news
        
        articles = []
        for item in news_items[:8]:  # 抓取最新的 8 篇
            title = item.get('title', '')
            url = item.get('link', '')
            publisher = item.get('publisher', '未知來源')
            summary = item.get('summary', '') # 部分新聞可能沒有 summary
            
            desc = f"來源: {publisher}。 {summary}".strip()
            
            if title and url:
                articles.append({
                    'title': title,
                    'description': desc,
                    'url': url
                })
        return articles
    except Exception as e:
        print(f"❌ [yfinance] 抓取 {ticker} 失敗: {e}")
        return []

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
    1. 判斷此新聞是否包含以下任一條件：
       - 「基本面變化」或「商業護城河發展」。
       - 「波動率 (IV) 催化劑」(例如：財報前瞻、分析師評級調整、管理層發言、產品發布)。
    2. 對於中小型成長股 ({ticker})，請放寬審查標準，任何可能影響短期期權定價的實質資訊都算作「有」。
    3. 如果「有」，請嚴格按照以下格式回覆（請勿加上任何 Markdown 符號或 Markdown 代碼塊）：
       [情緒] (請填寫：🟢利好 / 🔴利空 / ⚪中性)
       [總結] (用 1-2 句繁體中文精確總結，並點出對護城河或短期波動率的潛在影響)
    4. 如果「完全無關」(例如：純粹市場雜訊、農場文章、無具體內容的分析師總結)，請直接輸出 "SKIP"。
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
    """ 使用 HTML 排版，修復 \n 變成文字的 Bug """
    sentiment_icon = "💡" 
    summary = analysis
    
    clean_analysis = analysis.replace('\\n', '\n')
    clean_analysis = clean_analysis.replace('---', '').replace('___', '')
    
    lines = clean_analysis.split('\n')
    for line in lines:
        if line.startswith('[情緒]'):
            sentiment_part = line.replace('[情緒]', '').strip()
            if '🟢' in sentiment_part:
                sentiment_icon = "🟢"
            elif '🔴' in sentiment_part:
                sentiment_icon = "🔴"
            elif '⚪' in sentiment_part:
                sentiment_icon = "⚪"
        elif line.startswith('[總結]'):
            summary = line.replace('[總結]', '').strip()

    if summary == analysis:
        summary = clean_analysis.replace('[情緒]', '').replace('[總結]', '').strip()

    msg = (
        f"<b>{sentiment_icon} {ticker} 投資快訊</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"<i>{summary}</i>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔗 <a href='{url}'>點擊閱讀完整原文</a>"
    )
    return msg

def start_watchdog():
    print(f"👀 新聞看門狗開始執行掃描...")
    seen_urls = load_history()
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
    
    all_tickers = set(WATCHLIST.keys())
    no_update_tickers = all_tickers - tickers_with_updates
    
    if no_update_tickers:
        no_news_msg = (
            f"📭 *掃描完成：本日以下標的無新動態*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{', '.join(sorted(no_update_tickers))}\n"
            f"*(系統正常運作中，未發現上述股票的實質性催化劑)*"
        )
        send_telegram_message(no_news_msg)
        print("✅ 已推送無更新名單總結")

    print("🏁 單次掃描完成，程式結束。")

if __name__ == "__main__":
    start_watchdog()
