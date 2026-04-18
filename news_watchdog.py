import time
import json
import requests
import os
from datetime import datetime
from bot import send_telegram_message

# ================= 設定區 =================
WATCHLIST = ['HIMS', 'ZETA', 'ODDITY', 'NVDA', 'TSLA', 'AMD', 'OSCR']

NEWS_API_KEY = 'fdd4f066081e4231a20e66319d581117'
GEMINI_API_KEY = 'AIzaSyC-vgL2fxsl45MdWxM5VTqjo3n2jjYM8IQY'

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
    if not GEMINI_API_KEY:
        return None, None

    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')

        prompt = f"""
你是一個專業股票分析師，請分析以下關於 {ticker} 的新聞。
新聞標題：{title}
新聞內容：{description}

請判斷此新聞對投資者的重要性。

如果是雜訊（一般市場波動、無實質影響的輿論），只輸出：SKIP

如果是重要新聞，請用以下 JSON 格式輸出（不要加 markdown code block）：
{{
  "impact": "利多" 或 "利空" 或 "中性",
  "magnitude": "重大" 或 "中等" 或 "輕微",
  "summary": "一句話中文摘要（30字內）",
  "reason": "為何重要（20字內）"
}}

重要新聞包括：財報、M&A、FDA審批、管理層異動、重大合約、競爭格局改變等。
"""

        response = model.generate_content(prompt)
        text = response.text.strip()

        if "SKIP" in text:
            return "SKIP", None

        # 解析 JSON
        result = json.loads(text)
        return "OK", result

    except Exception as e:
        print(f"Gemini 分析失敗: {e}")
        return "OK", {"impact": "中性", "magnitude": "輕微", "summary": title, "reason": "分析失敗，請自行判斷"}

def format_message(ticker, result, url, published_at):
    # Impact emoji mapping
    impact_emoji = {
        "利多": "📈",
        "利空": "📉",
        "中性": "➡️"
    }
    magnitude_emoji = {
        "重大": "🚨🚨🚨",
        "中等": "⚠️⚠️",
        "輕微": "ℹ️"
    }
    impact_bar = {
        "重大": "█████",
        "中等": "███░░",
        "輕微": "█░░░░"
    }

    ie = impact_emoji.get(result['impact'], "➡️")
    me = magnitude_emoji.get(result['magnitude'], "ℹ️")
    bar = impact_bar.get(result['magnitude'], "█░░░░")

    # 格式化發布時間
    try:
        dt = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ")
        time_str = dt.strftime("%m/%d %H:%M UTC")
    except:
        time_str = "剛剛"

    msg = (
        f"{me} *{ticker}* 重要快訊\n"
        f"{'─' * 22}\n"
        f"{ie} 方向：*{result['impact']}*　|　影響：*{result['magnitude']}*\n"
        f"強度：{bar}\n"
        f"{'─' * 22}\n"
        f"📋 *{result['summary']}*\n"
        f"💡 重要原因：{result['reason']}\n"
        f"{'─' * 22}\n"
        f"🕐 {time_str}\n"
        f"[📎 閱讀原文]({url})"
    )
    return msg

def start_watchdog():
    print(f"👀 新聞看門狗已啟動... (每 {SCAN_INTERVAL//60} 分鐘掃描一次)")
    send_telegram_message("👀 *新聞監控系統已上線！*\n監控中：" + " | ".join(WATCHLIST))

    seen_urls = load_history()

    while True:
        print(f"[{datetime.now().strftime('%H:%M')}] 開始新一輪掃描...")

        for ticker in WATCHLIST:
            articles = get_latest_news(ticker)

            for article in articles:
                url = article.get('url')
                if not url or url in seen_urls:
                    continue

                title = article.get('title', '')
                desc = article.get('description', '')
                published_at = article.get('publishedAt', '')

                status, result = analyze_news_gemini(ticker, title, desc)

                if status == "SKIP":
                    print(f"🗑️ 過濾雜訊: {title[:30]}...")
                elif status == "OK" and result:
                    msg = format_message(ticker, result, url, published_at)
                    send_telegram_message(msg)
                    print(f"✅ 已推送 {ticker}｜{result['impact']}｜{result['magnitude']}")

                seen_urls.add(url)
                time.sleep(1)

        save_history(seen_urls)
        print(f"💤 休息 {SCAN_INTERVAL} 秒...")
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    start_watchdog()
