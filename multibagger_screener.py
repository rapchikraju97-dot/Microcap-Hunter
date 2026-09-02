import os
import sys
import time
import requests
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SCREENER_URL = os.getenv("SCREENER_URL")

BASE_URL = "https://www.screener.in"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.screener.in/",
    "Upgrade-Insecure-Requests": "1"
}

CATALYST_TAXONOMY = {
    "Gaming, IT & Digital Platforms": {
        "keywords": ["gaming", "metaverse", "software", "information technology", "digital", "saas", "cloud"],
        "tailwinds": [
            "Asset-Light Operating Leverage: Negligible physical capex allows rapid incremental margin expansion.",
            "Digital Monetization: High global scalability with immediate billing realization."
        ]
    },
    "Capital Goods & Defense": {
        "keywords": ["defense", "aerospace", "valve", "pump", "casting", "forging", "machining", "cnc", "industrial machinery", "tool", "taps"],
        "tailwinds": [
            "Import Substitution: Beneficiary of Make in India and defense localization.",
            "Operating Leverage: High capacity utilization accelerating margin expansion."
        ]
    },
    "Power & Renewable Transition": {
        "keywords": ["power", "solar", "transformer", "cable", "wire", "switchgear", "grid", "renewable", "substation"],
        "tailwinds": [
            "Grid Modernization: Transmission Capex expanding to evacuate renewable power.",
            "Order Book Visibility: Multi-year backlog backed by utility tenders."
        ]
    },
    "Chemicals & Specialized Materials": {
        "keywords": ["chemical", "specialty chemical", "intermediate", "agrochem", "api", "pharma", "polymer", "gelatine", "ossein"],
        "tailwinds": [
            "China+1 Shift: Global supply chains diversifying raw material intermediate sourcing.",
            "Spread Recovery: Raw material input normalization driving EBITDA rebound."
        ]
    },
    "Infrastructure & Construction": {
        "keywords": ["rail", "wagon", "tunnel", "bridge", "highway", "port", "logistics", "civil construction", "infrastructure", "construct"],
        "tailwinds": [
            "National Infra Outlays: Beneficiary of strategic transit corridors and highway capex.",
            "Execution Moat: Specialized civil works command protected margins vs plain contractors."
        ]
    },
    "Consumer Retail & Distribution": {
        "keywords": ["retail", "smart phones", "appliances", "consumer durable", "store", "distribution"],
        "tailwinds": [
            "Store Network Expansion: Aggressive retail footprint scaling operating leverage.",
            "Consumer Premiumization: Rapid volume growth in higher-ticket consumer devices."
        ]
    }
}

def clean_float(val: str) -> float:
    if not val:
        return 0.0
    try:
        return float(val.replace(",", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        return 0.0

def build_page_url(base_url: str, page: int) -> str:
    url_parts = list(urlparse(base_url.strip()))
    query = parse_qs(url_parts[4])
    query["page"] = [str(page)]
    url_parts[4] = urlencode(query, doseq=True)
    return urlunparse(url_parts)

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

def get_company_details(session: requests.Session, company_path: str) -> tuple[str, str, float]:
    """Extracts Sector, About text, and genuine latest Annual Operating Cash Flow (CFO)."""
    if not company_path:
        return "Industrial Ancillary", "Niche supplier serving core industry verticals.", 0.0
        
    full_url = BASE_URL + company_path if company_path.startswith("/") else f"{BASE_URL}/{company_path}"
    try:
        resp = session.get(full_url, timeout=10)
        if resp.status_code != 200:
            return "Industrial Ancillary", "Niche supplier serving core industry verticals.", 0.0
            
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # 1. Sector
        sector = "Industrial Ancillary"
        peers_section = soup.find("section", id="peers")
        if peers_section:
            sector_tag = peers_section.find("a", href=lambda h: h and "/market/" in h)
            if sector_tag:
                sector = sector_tag.get_text(strip=True)

        # 2. About Description
        about_div = soup.find("div", class_="about") or soup.find("div", class_="company-profile")
        description = "Niche supplier serving core industry verticals."
        if about_div:
            p_tag = about_div.find("p")
            if p_tag:
                description = p_tag.get_text(strip=True)

        # 3. Direct Annual Cash Flow Extraction
        real_cfo = 0.0
        cashflow_sec = soup.find("section", id="cash-flow")
        if cashflow_sec:
            table = cashflow_sec.find("table", class_="data-table")
            if table:
                for row in table.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in row.find_all("td")]
                    if cells and ("cash from operating activity" in cells[0].lower() or "operating cash" in cells[0].lower()):
                        # Get the latest reported annual figure (last column)
                        real_cfo = clean_float(cells[-1])
                        break
                        
        return sector, description, real_cfo
    except Exception:
        return "Industrial Ancillary", "Niche supplier serving core industry verticals.", 0.0

def fetch_screener_stocks(url: str) -> tuple[list[dict], requests.Session]:
    session = requests.Session()
    session.headers.update(HEADERS)
    page = 1
    stocks = []
    
    while True:
        page_url = build_page_url(url, page)
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
            tables = soup.find_all("table")
            if tables:
                table = tables[0]
            else:
                break
                
        thead = table.find("thead")
        raw_headers = [th.get_text(strip=True) for th in thead.find_all("th")] if thead else []
        headers = [h.lower() for h in raw_headers]

        def find_exact_col(positive_needles, negative_needles=None):
            if negative_needles is None:
                negative_needles = []
            for needle in positive_needles:
                for idx, h in enumerate(headers):
                    if any(neg in h for neg in negative_needles):
                        continue
                    if needle in h:
                        return idx
            return -1

        idx_name = find_exact_col(["name"])
        idx_cmp = find_exact_col(["cmp rs", "cmp", "current price", "price"])
        idx_pe = find_exact_col(["p/e", "price to earning"])
        idx_mcap = find_exact_col(["mar cap", "market cap"])
        idx_pat = find_exact_col(["np qtr", "net profit latest quarter", "profit after tax latest quarter"], negative_needles=["var", "growth", "div"])
        idx_growth = find_exact_col(["qtr profit var", "profit var", "yoy quarterly profit growth"], negative_needles=["div", "yield"])

        tbody = table.find("tbody") or table
        rows = tbody.find_all("tr")
        data_rows = [r for r in rows if r.find_all("td")]

        if not data_rows:
            break

        for row in data_rows:
            tds = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(tds) < 3:
                continue

            link_tag = row.find("a", href=True)
            company_href = link_tag["href"] if link_tag else ""

            def get_val(col_idx, fallback_idx, default="N/A"):
                if col_idx != -1 and col_idx < len(tds):
                    return tds[col_idx]
                if fallback_idx < len(tds):
                    return tds[fallback_idx]
                return default

            stocks.append({
                "name": get_val(idx_name, 1, "Unknown"),
                "href": company_href,
                "cmp": get_val(idx_cmp, 2, "N/A"),
                "pe": get_val(idx_pe, 3, "N/A"),
                "mcap": get_val(idx_mcap, 4, "N/A"),
                "pat": get_val(idx_pat, 6, "0"),
                "profit_growth": get_val(idx_growth, 7, "0.00")
            })
        
        if len(data_rows) < 25:
            break
            
        page += 1
        time.sleep(1.5)
        
    return stocks, session

def identify_structural_catalyst(sector: str, description: str, stock: dict) -> tuple[str, list[str]]:
    text = (sector + " " + description).lower()
    matched_theme = None
    tailwinds = []
    
    for theme, config in CATALYST_TAXONOMY.items():
        if any(kw in text for kw in config["keywords"]):
            matched_theme = theme
            tailwinds.extend(config["tailwinds"])
            break
            
    pe = clean_float(stock.get("pe", "0"))
    if 0 < pe <= 15:
        tailwinds.append(f"Twin-Engine Re-Rating: Low multiple ({pe:.1f}x) provides multiple-expansion runway if growth holds.")
    elif 15 < pe <= 24:
        tailwinds.append("Compounder Valuation: Balanced multiple enables organic EPS growth with institutional accumulation.")
        
    if not matched_theme:
        matched_theme = sector if sector not in ["Diversified", "General", "Commodities"] else "Niche Engineering Ancillary"
        tailwinds.append("Second-Order Beneficiary: Positioned to capture ancillary demand from primary industry volume expansion.")

    return matched_theme, tailwinds

def send_ranked_conviction_alerts(stocks: list, session: requests.Session):
    if not stocks:
        print("No stocks scraped from Screener.")
        return

    scored_stocks = []
    for s in stocks:
        growth = clean_float(s.get("profit_growth", "0"))
        pe = clean_float(s.get("pe", "0"))
        mcap = clean_float(s.get("mcap", "0"))

        if mcap < 20.0 or pe <= 0 or pe > 35.0:
            continue

        # Preliminary scoring based on screen metrics
        score = 0.0
        if growth >= 50.0:
            score += 40.0
        elif growth >= 25.0:
            score += 30.0
        elif growth >= 15.0:
            score += 15.0
        else:
            score += 5.0

        if 5.0 <= pe <= 15.0:
            score += 30.0
        elif 15.0 < pe <= 24.0:
            score += 20.0
        else:
            score += 10.0

        s["pre_score"] = score
        scored_stocks.append(s)

    # Sort and take top 5 candidates to pull verified cash flows
    top_candidates = sorted(scored_stocks, key=lambda x: x["pre_score"], reverse=True)[:5]

    total = len(top_candidates)
    chunk_size = 3
    total_parts = (total + chunk_size - 1) // chunk_size

    for idx in range(0, total, chunk_size):
        batch = top_candidates[idx:idx + chunk_size]
        part_num = (idx // chunk_size) + 1
        
        msg = f"🔥 *High-Conviction Multibagger Picks* ({part_num}/{total_parts})\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for s in batch:
            sector, about_text, real_cfo = get_company_details(session, s.get("href", ""))
            theme_name, catalyst_points = identify_structural_catalyst(sector, about_text, s)
            
            pat = clean_float(s.get("pat", "0"))
            growth = clean_float(s.get("profit_growth", "0"))
            growth_sign = "+" if growth > 0 else ""
            
            annualized_pat = pat * 4
            if real_cfo <= 0:
                cash_badge = "⚠️ Negative Cash Flow (CFO ≤ 0)"
                final_score = max(35, s["pre_score"] - 10)
            elif annualized_pat > 0 and (real_cfo / annualized_pat) >= 0.5:
                conv_pct = round((real_cfo / annualized_pat) * 100)
                cash_badge = f"✅ Strong Conversion (~{conv_pct}% CFO/PAT)"
                final_score = min(100, s["pre_score"] + 30)
            else:
                cash_badge = "⚠️ Moderate Cash Flow"
                final_score = min(100, s["pre_score"] + 15)

            short_about = (about_text[:115] + "...") if len(about_text) > 115 else about_text
            bullets = "\n".join([f"    • {p}" for p in catalyst_points])
            
            msg += f"🏢 *{s['name']}* (Score: `{final_score:.0f}/100`)\n"
            msg += f"├ 💰 *Valuation:* ₹{s['cmp']} | *P/E:* {s['pe']}x | *MCap:* ₹{s['mcap']} Cr\n"
            msg += f"├ 📈 *Earnings Velocity:* Qtr PAT Var: {growth_sign}{s['profit_growth']}%\n"
            msg += f"├ 🛡️ *Cash Quality:* {cash_badge}\n"
            msg += f"│   `Annual CFO: ₹{real_cfo:.1f} Cr | Qtr PAT: ₹{pat:.1f} Cr`\n"
            msg += f"├ 🏭 *Theme:* {theme_name}\n"
            msg += f"│   _{short_about}_\n"
            msg += f"└ 🚀 *Catalysts & Tailwinds:*\n{bullets}\n\n"
            
            time.sleep(0.5)

        send_telegram_alert(msg)
        time.sleep(1.5)

def main():
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SCREENER_URL]):
        print("Error: Missing environment variables.", file=sys.stderr)
        sys.exit(1)
        
    stocks, session = fetch_screener_stocks(SCREENER_URL)
    print(f"Total raw matches from Screener: {len(stocks)}")
    send_ranked_conviction_alerts(stocks, session)

if __name__ == "__main__":
    main()
