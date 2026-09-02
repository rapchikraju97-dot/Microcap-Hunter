import os
import sys
import time
import requests
from bs4 import BeautifulSoup

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SCREENER_URL = os.getenv("SCREENER_URL")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.screener.in/",
    "Upgrade-Insecure-Requests": "1"
}

def clean_float(val: str) -> float:
    if not val:
        return 0.0
    try:
        return float(val.replace(",", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        return 0.0

def send_telegram_alert(message: str) -> bool:
    token = (TELEGRAM_BOT_TOKEN or "").strip().replace('"', '').replace("'", "")
    if token.lower().startswith("bot"):
        token = token[3:]
    
    chat_id = str(TELEGRAM_CHAT_ID or "").strip().replace('"', '').replace("'", "")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            print(f"Telegram API Error {resp.status_code}: {resp.text}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"Failed to deliver Telegram notification: {e}", file=sys.stderr)
        return False

def fetch_screener_stocks(url: str) -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)
    page = 1
    stocks = []
    
    while True:
        page_url = f"{url}?page={page}" if "?" not in url else f"{url}&page={page}"
        try:
            resp = session.get(page_url, timeout=20, allow_redirects=True)
        except Exception as e:
            print(f"Network error on page {page}: {e}", file=sys.stderr)
            break
            
        if resp.status_code != 200 or "/login/" in resp.url:
            break
            
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", class_="data-table")
        if not table:
            break
            
        thead = table.find("thead")
        if not thead:
            break
            
        headers = [th.get_text(strip=True).lower() for th in thead.find_all("th")]

        def locate(candidates):
            for cand in candidates:
                for idx, h in enumerate(headers):
                    if cand in h:
                        return idx
            return -1

        idx_name = locate(["name"])
        idx_cmp = locate(["cmp", "current price", "price"])
        idx_pe = locate(["p/e", "price to earning"])
        idx_mcap = locate(["mar cap", "market capitalization", "market cap"])
        idx_growth = locate(["yoy quarterly profit growth", "qtr profit var", "profit growth"])
        idx_cfo = locate(["cash from operations last year", "cfo last year", "cfo"])
        idx_pat = locate(["profit after tax latest quarter", "net profit latest quarter", "profit after tax", "net profit", "pat"])

        tbody = table.find("tbody")
        if not tbody:
            break
            
        for row in tbody.find_all("tr"):
            tds = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(tds) < len(headers):
                continue
                
            stocks.append({
                "name": tds[idx_name] if idx_name != -1 else tds[1],
                "cmp": tds[idx_cmp] if idx_cmp != -1 else "N/A",
                "pe": tds[idx_pe] if idx_pe != -1 else "N/A",
                "mcap": tds[idx_mcap] if idx_mcap != -1 else "N/A",
                "profit_growth": tds[idx_growth] if idx_growth != -1 else "0.00",
                "cfo": tds[idx_cfo] if idx_cfo != -1 else "0",
                "pat": tds[idx_pat] if idx_pat != -1 else "0"
            })
        
        next_button = soup.find("a", string=lambda t: t and "Next" in t)
        if not next_button:
            break
            
        page += 1
        time.sleep(1.5)
        
    return stocks

def evaluate_cash_flow_health(stock: dict) -> tuple[str, str, str]:
    cfo = clean_float(stock.get("cfo", "0"))
    pat = clean_float(stock.get("pat", "0"))
    
    details = f"CFO: ₹{cfo:.1f} Cr | Qtr PAT: ₹{pat:.1f} Cr"

    if cfo <= 0:
        return "⚠️", "Negative Cash Flow", f"{details} (CFO ≤ 0)"
    
    # Quarterly PAT ko annualize (~4x) karke annual CFO se compare karte hain
    annualized_pat = pat * 4
    if annualized_pat > 0:
        conversion = round((cfo / annualized_pat) * 100, 1)
        if conversion < 50.0:
            return "⚠️", "Low Cash Conversion", f"{details} (~{conversion}% conversion)"
        return "✅", "Strong Cash Conversion", f"{details} (~{conversion}% conversion)"
    
    return "✅", "Cash Positive", details

def send_chunked_alerts(stocks: list, chunk_size: int = 5):
    if not stocks:
        print("No matches to alert.")
        return

    total = len(stocks)
    total_parts = (total + chunk_size - 1) // chunk_size
    
    for idx in range(0, total, chunk_size):
        batch = stocks[idx:idx + chunk_size]
        part_num = (idx // chunk_size) + 1
        
        msg = f"📡 *Multibagger Discovery Scan* ({part_num}/{total_parts})\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for s in batch:
            icon, status, cash_detail = evaluate_cash_flow_health(s)
            
            growth_val = clean_float(s['profit_growth'])
            growth_sign = "+" if growth_val > 0 else ""
            
            msg += f"🏢 *{s['name']}*\n"
            msg += f"├ 💰 *Valuation:* ₹{s['cmp']} | *P/E:* {s['pe']}x | *MCap:* ₹{s['mcap']} Cr\n"
            msg += f"├ 📈 *Earnings:* Qtr PAT Var: {growth_sign}{s['profit_growth']}%\n"
            msg += f"└ 🛡️ *Cash Health:* {icon} *{status}*\n"
            msg += f"    `{cash_detail}`\n\n"
            
        send_telegram_alert(msg)
        time.sleep(1.5)

def main():
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SCREENER_URL]):
        print("Error: Missing environment variables.", file=sys.stderr)
        sys.exit(1)
        
    stocks = fetch_screener_stocks(SCREENER_URL)
    print(f"Total stocks extracted: {len(stocks)}")
    send_chunked_alerts(stocks, chunk_size=5)

if __name__ == "__main__":
    main()
