import yfinance as yf
import pandas as pd
import os
import requests
import time
from datetime import datetime, timezone

# --- 配置區 ---
WATCHLIST = ['ZETA', 'ODD', 'HIMS', 'OSCR']

# 異動標準
MIN_VOLUME = 500          # 最小成交量
VOL_OI_RATIO = 1.2        # 量/倉比
CHECK_NEXT_N_EXPIRY = 2   # 檢查最近 N 個到期日

TELEGRAM_TOKEN = os.environ.get('TG_TOKEN')
CHAT_ID = os.environ.get('TG_CHAT_ID')

def send_telegram_msg(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ Error: TG_TOKEN or TG_CHAT_ID not set.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID, 
        "text": message, 
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Msg failed: {e}")

def get_sentiment(opt_type, change_pct):
    """
    根據期權類型和價格變化推斷情緒
    """
    if change_pct > 0:
        action = "BUYING (Long)"
        # 買 Call 是看漲，買 Put 是看跌
        sentiment = "🟢 BULLISH" if opt_type == 'CALL' else "🔴 BEARISH"
    elif change_pct < 0:
        action = "SELLING (Short)"
        # 賣 Call 是看跌，賣 Put 是看漲 (支撐)
        sentiment = "🔴 BEARISH" if opt_type == 'CALL' else "🟢 BULLISH"
    else:
        action = "Neutral"
        sentiment = "⚪ NEUTRAL"
    
    return action, sentiment

def analyze_options(ticker):
    print(f"🔍 Scanning {ticker}...")
    try:
        stock = yf.Ticker(ticker)
        
        # 獲取現價
        current_price = stock.fast_info.get('lastPrice', 0)
        if current_price == 0:
            hist = stock.history(period="1d")
            if not hist.empty:
                current_price = hist['Close'].iloc[-1]
        
        expirations = stock.options
        if not expirations:
            return

        alerts = []

        for exp_date in expirations[:CHECK_NEXT_N_EXPIRY]:
            opt_chain = stock.option_chain(exp_date)
            
            # 合併數據
            calls = opt_chain.calls
            calls['Type'] = 'CALL'
            puts = opt_chain.puts
            puts['Type'] = 'PUT'
            
            all_opts = pd.concat([calls, puts])

            for _, row in all_opts.iterrows():
                vol = row['volume']
                oi = row['openInterest']
                strike = row['strike']
                opt_type = row['Type']
                last_price = row['lastPrice']
                change_pct = row['percentChange'] # 這是關鍵：價格漲跌幅
                
                # 數據清理
                vol = 0 if pd.isna(vol) else int(vol)
                oi = 0 if pd.isna(oi) else int(oi)
                change_pct = 0.0 if pd.isna(change_pct) else float(change_pct)

                # 篩選條件
                if vol < MIN_VOLUME: continue
                
                ratio = 999.0 if oi == 0 else vol / oi

                if ratio >= VOL_OI_RATIO:
                    # 判斷是買還是賣
                    action_str, sentiment_str = get_sentiment(opt_type, change_pct)
                    
                    # 計算價內/價外
                    if opt_type == 'CALL':
                        otm_pct = (strike - current_price) / current_price * 100
                        moneyness = "OTM" if strike > current_price else "ITM"
                    else:
                        otm_pct = (current_price - strike) / current_price * 100
                        moneyness = "OTM" if strike < current_price else "ITM"

                    # 只有真的有漲跌才發送 (過濾掉價格不變的雜訊)
                    if change_pct == 0: continue

                    emoji = "🔥"
                    alert_msg = (
                        f"{sentiment_str} **{ticker} {opt_type}**\n"
                        f"Exp: {exp_date} | Strike: ${strike}\n"
                        f"📊 Vol: {vol} / OI: {oi} (x{ratio:.1f})\n"
                        f"💵 Price: ${last_price:.2f} ({change_pct:+.1f}%)\n"
                        f"🔎 Action: {action_str}\n"
                        f"🎯 {moneyness} {abs(otm_pct):.1f}%\n"
                    )
                    alerts.append(alert_msg)

        if alerts:
            header = f"{emoji} **Options Alert: {ticker}** (${current_price:.2f})\n-------------------\n"
            full_msg = header + "\n".join(alerts)
            send_telegram_msg(full_msg)
            print(f"✅ Alert sent for {ticker}")

    except Exception as e:
        print(f"Error scanning {ticker}: {e}")

if __name__ == "__main__":
    print(f"🚀 Starting Options Scan at {datetime.now(timezone.utc)}")
    for symbol in WATCHLIST:
        analyze_options(symbol)
    print("🏁 Scan Complete.")
