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
GEMINI_MODEL = 'gemini-2.5-flash' 
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
    """ 抓取 Yahoo 新聞，並加上 User-Agent 伪裝防止被封 """
    try:
        stock = yf.Ticker(ticker)
        # 使用 yfinance 內建機制抓取
        news_items = stock.news
        
        articles = []
        if not news_items:
            return []
            
        for item in news_items[:8]:
            article_id = item.get('uuid', item.get('link', ''))
            title = item.get('title', '')
            url = item.get('link', '')
            publisher = item.get('publisher', '未知來源')
            
            if not title or not url:
                continue
                
            articles.append({
                'id': article_id,
                'title': title,
                'description': f"來源: {publisher}。 {title}", 
                'url': url
            })
        return articles
    except Exception as e:
        print(f"❌ [yfinance] 抓取 {ticker} 失敗: {e}")
        return []

def analyze_news_gemini(ticker, title, description):
    if not GEMINI_API_KEY:
        return "ERROR_NO_KEY"

    try:
        from google import genai
    except ImportError:
        return "ERROR_NO_LIB"

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

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        return f"ERROR_API_FAIL: {str(e)[:50]}"

def format_telegram_message(ticker, analysis, url):
    sentiment_icon = "💡" 
    summary = analysis
    
    clean_analysis = analysis.replace('\\n', '\n').replace('---', '').replace('___', '').replace('`', '')
    lines = clean_analysis.split('\n')
    
    for line in lines:
        if line.startswith('[情緒]'):
            sentiment_part = line.replace('[情緒]', '').strip()
            if '🟢' in sentiment_part: sentiment_icon = "🟢"
            elif '🔴' in sentiment_part: sentiment_icon = "🔴"
            elif '⚪' in sentiment_part: sentiment_icon = "⚪"
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
    
    # 📊 數據診斷儀表板
    diagnostics = {
        "total_fetched": 0,
        "total_analyzed": 0,
        "total_skipped_by_ai": 0,
        "api_key_status": "🟢 已偵測到金鑰" if GEMINI_API_KEY else "🔴 未偵測到 (GitHub Secrets 未傳入)",
        "internal_errors": set()
    }
    
    for ticker in WATCHLIST.keys():
        articles = get_latest_news(ticker)
        diagnostics["total_fetched"] += len(articles)
        
        for article in articles:
            article_id = article.get('id')
            url = article.get('url')
            
            if not article_id or article_id in seen_ids:
                continue

            title = article.get('title', '')
            desc = article.get('description', '')
            
            diagnostics["total_analyzed"] += 1
            analysis = analyze_news_gemini(ticker, title, desc)
            
            if "ERROR" in analysis:
                diagnostics["internal_errors"].add(analysis)
                continue
                
            if analysis == "SKIP" or "SKIP" in analysis.upper():
                diagnostics["total_skipped_by_ai"] += 1
                seen_ids.add(article_id)
                continue
                
            msg = format_telegram_message(ticker, analysis, url)
            send_telegram_message(msg)
            print(f"✅ 已推送 {ticker} 新聞！")
            
            seen_ids.add(article_id)
            tickers_with_updates.add(ticker)
                
        time.sleep(2)
        
    save_history(seen_ids)
    
    all_tickers = set(WATCHLIST.keys())
    no_update_tickers = all_tickers - tickers_with_updates
    
    # 推送帶有數據診斷的報告
    if no_update_tickers:
        errors_str = f"\n⚠️ <b>系統異常:</b> {', '.join(diagnostics['internal_errors'])}" if diagnostics["internal_errors"] else ""
        no_news_msg = (
            f"📭 <b>掃描完成：本日以下標的無新動態</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"標的: {', '.join(sorted(no_update_tickers))}\n\n"
            f"📊 <b>看門狗運行診斷數據：</b>\n"
            f"• Gemini 金鑰狀態: {diagnostics['api_key_status']}\n"
            f"• 成功抓取新聞總數: <b>{diagnostics['total_fetched']} 篇</b>\n"
            f"• 送交 AI 分析篇數: <b>{diagnostics['total_analyzed']} 篇</b>\n"
            f"• 被 AI 判定為雜訊(SKIP): <b>{diagnostics['total_skipped_by_ai']} 篇</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"<i>(系統正常運作中，未發現符合策略的實質性催化劑)</i>"
            f"{errors_str}"
        )
        send_telegram_message(no_news_msg)
        print("✅ 已推送帶有診斷數據的總結")

    print("🏁 單次掃描完成。")

if __name__ == "__main__":
    start_watchdog()
