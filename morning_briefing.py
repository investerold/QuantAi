import yfinance as yf
import requests
from datetime import datetime, timedelta
from bot import send_telegram_message
import os

# ================= 設定區 =================
# 你的長線持倉
MY_PORTFOLIO = ['HIMS', 'ZETA', 'ODDITY', 'NVDA', 'TSLA', 'AMD', 'OSCR']

# OpenAI API Key (需要申請，下面會教你)
# 如果沒有，可以先用免費的新聞摘要，不用AI分析
OPENAI_API_KEY = None  # 填入你的key，例如 'sk-...'

# News API Key (免費，下面會教你申請)
NEWS_API_KEY = 'fdd4f066081e4231a20e66319d581117'
# 加上引號，Python 就知道這是一個字符串 (String)
# ==========================================

def get_stock_news(ticker, days_back=3):
    """
    抓取股票近期新聞 (暴力測試版)
    """
    if not NEWS_API_KEY:
        print("❌ 錯誤: 沒有填 News API Key")
        return []
    
    print(f"📡 正在向 NewsAPI 請求 {ticker} 的新聞...")
    
    try:
        # 這裡我們不設日期，只抓最新的，確保一定有東西
        url = f"https://newsapi.org/v2/everything"
        params = {
            'q': f"{ticker} stock OR {ticker} earnings", 
            'pageSize': 5, # 抓5篇
            'sortBy': 'publishedAt', # 按時間排序 (最新)
            'language': 'en',
            'apiKey': NEWS_API_KEY
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        if response.status_code == 200:
            articles = data.get('articles', [])
            print(f"✅ {ticker}: 抓到 {len(articles)} 篇新聞")
            return articles[:3]
        else:
            print(f"❌ API 請求失敗: {data}")
            return []
            
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")
        return []


def get_recent_earnings(ticker):
    """
    檢查是否有最新財報
    """
    try:
        stock = yf.Ticker(ticker)
        # 獲取財報日曆
        calendar = stock.calendar
        
        # 檢查是否在過去3天內有財報
        if calendar is not None and 'Earnings Date' in calendar:
            earnings_date = calendar['Earnings Date']
            if isinstance(earnings_date, list) and len(earnings_date) > 0:
                # 轉換為時間戳比對
                recent = (datetime.now() - earnings_date[0]).days <= 3
                if recent:
                    return True
        return False
    except:
        return False

def analyze_with_ai(ticker, news_summary):
    """
    用 AI (Peter Lynch 視角) 分析新聞
    """
    if not OPENAI_API_KEY:
        return news_summary  # 如果沒有AI key，直接回傳摘要
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        prompt = f"""
You are Peter Lynch, legendary investor. 

Stock: {ticker}
Recent News Summary: {news_summary}

Task:
1. Filter out noise (macro fears, analyst upgrades/downgrades without substance).
2. Focus on: Business fundamentals, competitive moat changes, management actions.
3. Rate urgency: 🟢 Good news / 🟡 Monitor / 🔴 Red flag
4. One-sentence verdict: Should I hold, trim, or add?

Keep response under 80 words, direct and actionable.
"""
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # 便宜又快的模型
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response.choices[0].message.content
    except Exception as e:
        return f"AI分析失敗: {e}"

def morning_briefing():
    """
    主函數：生成晨間簡報
    """
    print("☀️ 開始生成晨間簡報...")
    
    report = f"📰 **晨間持倉簡報** ({datetime.now().strftime('%Y-%m-%d')})\n\n"
    
    has_updates = False
    
    for ticker in MY_PORTFOLIO:
        print(f"正在分析 {ticker}...")
        
        # 1. 檢查財報
        has_earnings = get_recent_earnings(ticker)
        
        # 2. 抓新聞
        news = get_stock_news(ticker, days_back=1)
        
        if has_earnings or news:
            has_updates = True
            report += f"---\n**{ticker}**\n"
            
            if has_earnings:
                report += "🔔 最近有財報發布！\n"
            
            if news:
                # 整理新聞標題
                news_text = "\n".join([f"• {article['title']}" for article in news[:2]])
                
                # 如果有 AI，讓它分析
                if OPENAI_API_KEY:
                    analysis = analyze_with_ai(ticker, news_text)
                    report += f"{analysis}\n"
                else:
                    report += f"{news_text}\n"
            
            report += "\n"
    
    # 發送報告
    if has_updates:
        report += "*Peter Lynch提醒: 別被短期新聞牽著走。*"
        send_telegram_message(report)
        print("✅ 簡報已發送！")
    else:
        send_telegram_message(f"今日你的持倉 ({', '.join(MY_PORTFOLIO)}) 無重大新聞。市場平靜。")
        print("📭 今日無重大更新。")

if __name__ == "__main__":
    morning_briefing()
