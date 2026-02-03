import yfinance as yf
import pandas as pd
import os
import requests
import time
from datetime import datetime, timezone

# --- 配置區 ---
WATCHLIST = ['ZETA', 'ODD', 'HIMS', 'OSCR',] # 加入你想監控的

# 異動標準
MIN_VOLUME = 500          # 最小成交量 (張)
VOL_OI_RATIO = 1.2        # 成交量是未平倉量的多少倍 (1.2 代表多出 20% 新倉)
CHECK_NEXT_N_EXPIRY = 2   # 只檢查最近 N 個到期日 (為了速度)

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

def analyze_options(ticker):
    print(f"🔍 Scanning {ticker}...")
    try:
        stock = yf.Ticker(ticker)
        
        # 獲取當前股價
        current_price = stock.fast_info.get('lastPrice', 0)
        if current_price == 0:
            # Fallback
            hist = stock.history(period="1d")
            if not hist.empty:
                current_price = hist['Close'].iloc[-1]
        
        # 獲取期權鏈日期
        expirations = stock.options
        if not expirations:
            print(f"   No options data for {ticker}")
            return

        alerts = []

        # 只檢查最近的 N 個到期日
        for exp_date in expirations[:CHECK_NEXT_N_EXPIRY]:
            # 獲取 Call 和 Put
            opt_chain = stock.option_chain(exp_date)
            
            # 合併 Call 和 Put 進行遍歷，標記類型
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
                
                # 數據清理 (有些是 NaN)
                vol = 0 if pd.isna(vol) else int(vol)
                oi = 0 if pd.isna(oi) else int(oi)

                # --- 核心篩選邏輯 ---
                # 1. 成交量必須足夠大
                if vol < MIN_VOLUME:
                    continue
                
                # 2. Open Interest 為 0 的情況 (極端異動) 或 Vol/OI 比率達標
                if oi == 0:
                    ratio = 999.0 # 代表無限大
                else:
                    ratio = vol / oi

                if ratio >= VOL_OI_RATIO:
                    # 計算價外程度 (OTM %)
                    if opt_type == 'CALL':
                        otm_pct = (strike - current_price) / current_price * 100
                        direction = "bullish" if strike > current_price else "itm"
                    else: # PUT
                        otm_pct = (current_price - strike) / current_price * 100
                        direction = "bearish" if strike < current_price else "itm"

                    # 格式化 alert
                    emoji = "🐂" if opt_type == 'CALL' else "🐻"
                    moneyness = "OTM" if direction != "itm" else "ITM"
                    
                    alert_msg = (
                        f"{emoji} **{ticker} {opt_type}**\n"
                        f"Exp: {exp_date} | Strike: ${strike}\n"
                        f"📊 Vol: {vol} / OI: {oi} (x{ratio:.1f})\n"
                        f"💰 Price: ${row['lastPrice']:.2f} ({moneyness} {otm_pct:.1f}%)\n"
                    )
                    alerts.append(alert_msg)

        if alerts:
            header = f"🚨 **Unusual Options Activity** 🚨\nTarget: {ticker} (${current_price:.2f})\n-------------------\n"
            full_msg = header + "\n".join(alerts)
            send_telegram_msg(full_msg)
            print(f"✅ Alert sent for {ticker}")
        else:
            print(f"   No unusual activity found for {ticker}")

    except Exception as e:
        print(f"Error scanning {ticker}: {e}")

if __name__ == "__main__":
    print(f"🚀 Starting Options Scan at {datetime.now(timezone.utc)}")
    for symbol in WATCHLIST:
        analyze_options(symbol)
        time.sleep(1) # 避免被 Yahoo 封鎖
    print("🏁 Scan Complete.")