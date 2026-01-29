import yfinance as yf
import pandas as pd
import time
import requests
from bot import send_telegram_message 

# ================= 設定區 =================
TEST_LIMIT = None  # 測試用，想跑全部改成 None
# ==========================================

def get_smallcap_tickers():
    """ 獲取 Small Cap 名單 """
    print("🌍 正在下載 S&P 600 (小型股) 名單...")
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_600_companies'
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        r = requests.get(url, headers=headers)
        table = pd.read_html(r.text)
        df = table[0]
        tickers = df['Symbol'].tolist()
        tickers = [t.replace('.', '-') for t in tickers]
        print(f"✅ 成功獲取 {len(tickers)} 隻小型股代碼！")
        return tickers
    except Exception as e:
        print(f"❌ 抓取名單失敗: {e}")
        return ['HIMS', 'OSCR', 'ELF', 'CROX', 'PLTR']

def get_garp_metrics(ticker):
    """ 抓取雙重增長數據並計算 PEG """
    try:
        stock = yf.Ticker(ticker)
        fast_info = stock.fast_info
        price = fast_info.last_price
        
        info = stock.info 
        
        # 1. 估值指標
        f_pe = info.get('forwardPE', None)
        t_pe = info.get('trailingPE', None)
        
        # 2. 增長指標 (YoY)
        rev_growth = info.get('revenueGrowth', None) # 營收增長
        eps_growth = info.get('earningsGrowth', None) # 盈餘增長
        
        # 3. 計算 PEG (優先使用 EPS Growth)
        # 只有當 EPS Growth 有效且大於 0 時才計算，避免除以零或負值
        growth_rate_for_peg = eps_growth if (eps_growth and eps_growth > 0) else rev_growth
        
        calculated_peg = None
        if f_pe and growth_rate_for_peg and growth_rate_for_peg > 0:
            calculated_peg = f_pe / (growth_rate_for_peg * 100)

        # 4. 趨勢判斷 (Forward < Trailing 代表預期成長)
        is_growing_pe = False
        if f_pe and t_pe and f_pe < t_pe:
            is_growing_pe = True

        return {
            'Symbol': ticker,
            'Price': price,
            'PEG': calculated_peg,
            'Forward_PE': f_pe,
            'Trailing_PE': t_pe,
            'Rev_Growth': rev_growth,
            'EPS_Growth': eps_growth,
            'Is_Growing': is_growing_pe
        }
    except Exception as e:
        return None

def run_screener():
    tickers = get_smallcap_tickers()
    
    if TEST_LIMIT:
        print(f"⚠️ 測試模式：只掃描前 {TEST_LIMIT} 隻股票。")
        tickers = tickers[:TEST_LIMIT]
    
    print("🔍 開始掃描 GARP 寶石 (雙重增長驗證)...")
    results = []
    
    total = len(tickers)
    for i, t in enumerate(tickers):
        if (i+1) % 10 == 0:
            print(f"[{i+1}/{total}] 分析 {t} ...")
            
        data = get_garp_metrics(t)
        if data and data['PEG'] is not None:
            results.append(data)
        time.sleep(0.2)

    print("📊 數據收集完成，正在進行篩選...")
    
    df = pd.DataFrame(results)
    
    if df.empty:
        print("❌ 沒有有效數據。")
        return

    # --- 核心篩選邏輯 (Strict GARP) ---
    garp_picks = df[
        (df['PEG'] < 1.5) &      # 便宜
        (df['PEG'] > 0.1) &      # 排除極端異常值
        (df['EPS_Growth'] > 0.15) & # EPS 高成長 (>15%)
        (df['Rev_Growth'] > 0.05) & # 營收也要成長 (>5%)，確保不是縮減業務
        (df['EPS_Growth'] < 2.0)    # 排除 EPS 成長 > 200% 的異常基數效應
    ]
    
    if not garp_picks.empty:
        garp_picks = garp_picks.sort_values(by='PEG')
        
        msg = "🚨 **Small Cap GARP 獵手 (雙重增長版)** 🚨\n"
        msg += f"掃描: {len(tickers)} | 命中: {len(garp_picks)}\n\n"
        
        top_picks = garp_picks.head(10)
        
        for index, row in top_picks.iterrows():
            price_str = f"${round(row['Price'], 2)}"
            peg_val = round(row['PEG'], 2)
            
            # 格式化數據
            rev_pct = f"{round(row['Rev_Growth'] * 100, 1)}%" if row['Rev_Growth'] else "N/A"
            eps_pct = f"{round(row['EPS_Growth'] * 100, 1)}%" if row['EPS_Growth'] else "N/A"
            
            # 趨勢圖標
            trend_icon = "📈" if row['Is_Growing'] else "⚠️"
            
            msg += f"---------------\n"
            msg += f"🚀 **{row['Symbol']}** ({price_str}) {trend_icon}\n"
            msg += f"📊 PEG: **{peg_val}**\n"
            msg += f"💰 EPS: {eps_pct} | 📦 Rev: {rev_pct}\n"
            msg += f"🔮 Fwd PE: {row['Forward_PE']} (vs TTM: {row['Trailing_PE']})\n"
            
        msg += "\n*篩選: PEG<1.5, EPS>15%, Rev>5%*"
        
        print("✅ 找到目標！正在發送 Telegram...")
        send_telegram_message(msg)
        print("📨 發送成功！")
        
    else:
        fail_msg = f"掃描 {len(tickers)} 隻股票，無符合嚴格 GARP 標準的標的。"
        print(fail_msg)
        send_telegram_message(fail_msg)

if __name__ == "__main__":
    run_screener()
