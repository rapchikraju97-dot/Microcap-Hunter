import os
import sys
import time
import requests
from bs4 import BeautifulSoup

# Read credentials from environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SCREENER_URL = os.getenv("SCREENER_URL")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

def clean_float(val: str) -> float:
    """Safely converts string formatted numbers into floats."""
    if not val:
        return 0.0
    try:
        return float(val.replace(",", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        return 0.0

def send_telegram_alert(message: str) -> bool:
    """Dispatches a Markdown-formatted message to Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        return response.status_code == 200
    except Exception as e:
        print(f"Failed to deliver Telegram notification: {e}", file=sys.stderr)
        return False

def fetch_screener_stocks(url: str) -> list[dict]:
    """Extracts stock rows across all available pages of the screen."""
    page = 1
    stocks = []
    
    while True:
        page_url = f"{url}?page={page}"
        try:
            response = requests.get(page_url, headers=HEADERS, timeout=15)
        except Exception as e:
            print(f"Network error on page {page}: {e}", file=sys.stderr)
            break
            
        if response.status_code != 200:
            break
            
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table", class_="data-table")
        
        if not table:
            break
            
        tbody = table.find("tbody")
        if not tbody:
            break
            
        rows = tbody.find_all("tr")
        if not rows:
            break
            
        for row in rows:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cols) >= 8:
                stocks.append({
                    "name": cols[1],
                    "cmp": cols[2],
                    "pe": cols[3],
                    "mcap": cols[4],
                    "profit_growth": cols[5],
                    "cfo": cols[6],
                    "pat": cols[7]
                })
        
        # Determine if a next page exists
        next_button = soup.find("a", string=lambda t: t and "Next" in t)
        if not next_button:
            break
            
        page += 1
        time.sleep(1)  # Polite delay
        
    return stocks

def evaluate_cash_flow_health(stock: dict) -> tuple[str, str]:
    """Applies non-destructive quality checks to earnings quality."""
    cfo = clean_float(stock.get("cfo", "0"))
    pat = clean_float(stock.get("pat", "0"))
    
    if cfo <= 0:
        return "⚠️", "Negative Cash Flow (CFO ≤ 0)"
    
    if pat > 0 and (cfo / pat) < 0.6:
        conversion = round((cfo / pat) * 100, 1)
        return "⚠️", f"Weak Conversion ({conversion}% PAT to CFO)"
    
    return "✅", "Strong Cash Conversion"

def send_chunked_alerts(stocks: list, chunk_size: int = 5):
    """Batches results to respect Telegram character caps and rate limits."""
    if not stocks:
        print("No matches returned from screener.")
        return

    total = len(stocks)
    total_parts = (total + chunk_size - 1) // chunk_size
    
    for idx in range(0, total, chunk_size):
        batch = stocks[idx:idx + chunk_size]
        part_num = (idx // chunk_size) + 1
        
        msg = f"📡 *Multibagger Discovery Alert* (Part {part_num}/{total_parts})\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for s in batch:
            icon, status = evaluate_cash_flow_health(s)
            msg += f"🏢 *{s['name']}*\n"
            msg += f"• *Price:* ₹{s['cmp']} | *P/E:* {s['pe']}x\n"
            msg += f"• *MCap:* ₹{s['mcap']} Cr | *PAT Var:* {s['profit_growth']}%\n"
            msg += f"• *Cash Health:* {icon} {status}\n\n"
            
        send_telegram_alert(msg)
        time.sleep(1.5)

def main():
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SCREENER_URL]):
        print("Error: Missing one or more required environment variables.", file=sys.stderr)
        sys.exit(1)
        
    stocks = fetch_screener_stocks(SCREENER_URL)
    send_chunked_alerts(stocks, chunk_size=5)

if __name__ == "__main__":
    main()
