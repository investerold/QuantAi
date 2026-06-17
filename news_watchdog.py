import time
import json
import os
import yfinance as yf
from datetime import datetime
from bot import send_telegram_message

# ================= 設定區 =================
WATCHLIST = {
    "HIMS": ['"Hims & Hers"', '"HIMS"'],
    "ZETA": ['"Zeta Global"', '"ZETA"'],
    "ODDITY": ['"Oddity Tech"', '"ODD"'],
    "TSLA": ['"Tesla"', '"TSLA"'],
    "OSCR": ['"Oscar Health"', '"OSCR"']
}

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_MODEL = 'gemini-2.5-flash' # 建議使用標準 flash 模型以提高判斷準確率
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
    """ 優化：改用 uuid 作為唯一識別，並處理 yfinance summary 常缺漏的問題 """
    try:
        stock = yf.Ticker(ticker)
        news_items = stock.news
        
        articles = []
        for item in news_items[:8]:
            # Yahoo Finance 網址常變動，優先使用 uuid 作為去重鍵
            article_id = item.get('uuid', item.get('link', ''))
            title = item.get('title', '')
            url = item.get('link', '')
            publisher = item.get('publisher', '未知來源')
            
            if not title or not url:
                continue
                
            articles.append({
                'id': article_id,
                'title': title,
                'description': f"來源: {publisher}。 {title}", # 確保即使無 summary 也有足夠文字
                'url': url
            })
        return articles
    except Exception as e:
        print(f"❌ [yfinance] 抓取 {ticker} 失敗: {e}")
        return []

def analyze_news_gemini(ticker, title, description):
    if not GEMINI_API_KEY:
        return "SKIP"

    try:
        from google import genai
    except ImportError:
        print("⚠️ 請先安裝: pip install google-genai")
        return "SKIP"

    # 針對 GARP 與 Option Selling 優化的 Prompt
    prompt = f"""
    你是專注於 GARP 策略與期權賣方 (Option Selling) 的量化金融分析師。
    請分析 {ticker} 的這則新聞：
    標題：{title} 
    摘要：{description}
    
    判斷標準 (只要符合任一即視為「有」)：
    1. 財報前瞻、分析師評級調整、新產品發布等會引起短期 IV (隱含波動率) 膨脹或收縮的事件。
    2. 影響公司長期營收增長或商業護城河的實質基本面消息。
    
    若為無關痛癢的市場雜訊，請直接輸出四個英文字母：SKIP
    若有實質影響，請嚴格按照以下格式回覆 (絕不可加上任何 Markdown 符號或代碼塊)：
    [情緒] 🟢利好 (或 🔴利空 / ⚪中性)
    [總結] (用1-2句繁體中文總結核心催化劑，並簡述對期權定價或基本面的潛在影響)
    """

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # 增加重試機制，防止 429 錯誤吞噬新聞
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            return response.text.strip()
            
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg:
                print(f"⏳ [Gemini API] 觸發限制，等待 5 秒後重試 (第 {attempt+1}/{max_retries} 次)...")
                time.sleep(5)
            else:
                print(f"⚠️ [Gemini API] 分析失敗: {error_msg}")
                return "SKIP"
                
    return "SKIP"

def format_telegram_message(ticker, analysis, url):
    """ 統一使用 HTML 排版 """
    sentiment_icon = "💡" 
    summary = analysis
    
    clean_analysis = analysis.replace('\\n', '\n').replace('---', '').replace('___', '').replace('`', '')
    lines = clean_analysis.split('\n')
    
    for line in lines:
        if line.startswith('[情緒]'):
            sentiment_part = line.replace('[情緒]', '').strip()
            if '🟢' in sentiment_part: sentiment_icon = "🟢"
            elif '🔴' in sentiment_part: sentiment_icon = "🔴"
            elif '⚪' in sentiment_icon: sentiment_icon = "⚪"
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
    seen_ids = load_history()
    tickers_with_updates = set()
    
    for ticker in WATCHLIST.keys():
        articles = get_latest_news(ticker)
        
        for article in articles:
            article_id = article.get('id')
            url = article.get('url')
            
            if not article_id or article_id in seen_ids:
                continue

            title = article.get('title', '')
            desc = article.get('description', '')
            
            analysis = analyze_news_gemini(ticker, title, desc)
            
            # 精準過濾
            if analysis == "SKIP" or "SKIP" in analysis.upper():
                print(f"🗑️ 過濾雜訊: {ticker} - {title[:25]}...")
                seen_ids.add(article_id)
                continue
                
            msg = format_telegram_message(ticker, analysis, url)
            send_telegram_message(msg)
            print(f"✅ 已推送 {ticker} 新聞！")
            
            seen_ids.add(article_id)
            tickers_with_updates.add(ticker)
                
        time.sleep(2) # 避免密集請求 API
        
    save_history(seen_ids)
    
    all_tickers = set(WATCHLIST.keys())
    no_update_tickers = all_tickers - tickers_with_updates
    
    # 修正 Telegram 格式：統一使用 HTML (<b> 替代 Markdown 的 *)
    if no_update_tickers:
        no_news_msg = (
            f"📭 <b>掃描完成：本日以下標的無新動態</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{', '.join(sorted(no_update_tickers))}\n"
            f"<i>(系統正常運作中，未發現上述股票的實質性催化劑)</i>"
        )
        send_telegram_message(no_news_msg)
        print("✅ 已推送無更新名單總結")

    print("🏁 單次掃描完成，程式結束。")

if __name__ == "__main__":
    start_watchdog()
