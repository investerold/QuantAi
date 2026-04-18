import time
import json
import requests
import os
from datetime import datetime
from bot import send_telegram_message

# ================= 設定區 =================
WATCHLIST = ['HIMS', 'ZETA', 'ODDITY', 'NVDA', 'TSLA', 'AMD', 'OSCR']

NEWS_API_KEY = os.getenv('NEWS_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

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
        return "SKIP", None

    try:
        import google.generativeai as genai
        import re

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash')

        prompt = f"""
你是一個專業股票分析師，請分析以下關於 {ticker} 的新聞。
新聞標題：{title}
新聞內容：{description}

【重要】以下類型直接輸出 SKIP，不做分析：
- 一般分析文章、「好唔好買」類型文章
- 無具體事件的市場評論
- 重複舊新聞

以下類型才做分析（必須有具體事件）：
- 財報、業績預警
- 併購、分拆
- FDA/監管審批
- 管理層異動（CEO/CFO）
- 重大合約簽署
- 競爭格局重大改變

如果是雜訊，只輸出（不要加任何其他字）：
SKIP

如果是重要新聞，只輸出以下 JSON（不要加 markdown、不要加反引號）：
{{"impact": "利多或利空或中性", "magnitude": "重大或中等或輕微", "summary": "一句話中文摘要30字內", "reason": "為何重要20字內"}}
"""

        response = model.generate_content(prompt)
        text = response.text.strip()

        # 清洗 markdown fences
        text = re.sub(r'```[\w]*', '', text).strip()

        if "SKIP" in text:
            return "SKIP", None

        # 嘗試用 regex 提取 JSON block（即使有多餘文字）
        json_match = re.search(r'\{.*?\}', text, re.DOTALL)
        if not json_match:
            print(f"⚠️ 無法提取 JSON，原始回應：{text[:100]}")
            return "SKIP", None  # parse 失敗 → 靜默跳過，唔發爛訊息

        result = json.loads(json_match.group())

        # 驗證必要欄位
        required = ["impact", "magnitude", "summary", "reason"]
        if not all(k in result for k in required):
            return "SKIP", None

        return "OK", result

    except json.JSONDecodeError as e:
        print(f"⚠️ JSON 解析失敗 ({ticker}): {e} | 原文: {text[:100]}")
        return "SKIP", None  # 解析失敗靜默跳過
    except Exception as e:
        print(f"❌ Gemini 分析失敗 ({ticker}): {e}")
        return "SKIP", None

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
