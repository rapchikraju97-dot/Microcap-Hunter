import os
import sys
import time
import json
from datetime import datetime, date
import requests
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SCREENER_URL = os.getenv("SCREENER_URL")

BASE_URL = "https://www.screener.in"
TRACKER_FILE = "alerts_tracker.json"

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
            "Asset-Light Operating Leverage: Negligible physical capex allows rapid margin expansion.",
            "Digital Monetization: High scalability with short collection cycles."
        ]
    },
    "Capital Goods & Defense": {
        "keywords": ["defense", "aerospace", "valve", "pump", "casting", "forging", "machining", "cnc", "industrial machinery", "tool", "taps"],
        "tailwinds": [
            "Import Substitution: Direct beneficiary of defense localization and Make in India.",
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

# ==================== TRACKER DATABASE SYSTEM ====================

def load_tracker_data() -> dict:
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"tracked_stocks": {}}

def save_tracker_data(data: dict):
    with open(TRACKER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def record_new_alerts(stocks: list):
    data = load_tracker_data()
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    for s in stocks:
        name = s["name"]
        price = clean_float(s.get("cmp", "0"))
        href = s.get("href", "")
        
        # Only log first discovery price so initial entry isn't overwritten
        if name not in data["tracked_stocks"]:
            data["tracked_stocks"][name] = {
                "first_alerted_date": today_str,
                "first_alerted_price": price,
                "latest_price": price,
                "href": href,
                "score": s.get("conviction_score", 0),
                "theme": s.get("theme", "Diversified")
            }
        else:
            # Update latest price and link
            data["tracked_stocks"][name]["latest_price"] = price
            if href:
                data["tracked_stocks"][name]["href"] = href
                
    save_tracker_data(data)

def fetch_current_price(session: requests.Session, href: str) -> float:
    if not href:
        return 0.0
    full_url = BASE_URL + href if href.startswith("/") else f"{BASE_URL}/{href}"
    try:
        resp = session.get(full_url, timeout=10)
        if resp.status_code != 200:
            return 0.0
        soup = BeautifulSoup(resp.text, "html.parser")
        top_ratios = soup.find("ul", id="top-ratios")
        if top_ratios:
            for li in top_ratios.find_all("li"):
                name = li.find("span", class_="name")
                val = li.find("span", class_="number")
                if name and val and "current price" in name.get_text(strip=True).lower():
                    return clean_float(val.get_text(strip=True))
    except Exception:
        pass
    return 0.0

def run_weekly_performance_report(session: requests.Session, force_run: bool = False):
    """Generates and sends a reliability performance scorecard."""
    data = load_tracker_data()
    tracked = data.get("tracked_stocks", {})
    if not tracked:
        return

    # Check if Friday (weekday == 4) or forced
    is_friday = (datetime.now().weekday() == 4)
    if not (is_friday or force_run):
        return

    print("Compiling weekly portfolio performance report...")
    today = date.today()
    results = []

    for name, info in tracked.items():
        entry_price = info.get("first_alerted_price", 0.0)
        if entry_price <= 0:
            continue
            
        cur_price = fetch_current_price(session, info.get("href", ""))
        if cur_price <= 0:
            cur_price = info.get("latest_price", entry_price)

        # Update latest price
        info["latest_price"] = cur_price
        
        # Calculate days held
        entry_date = datetime.strptime(info["first_alerted_date"], "%Y-%m-%d").date()
        days_held = (today - entry_date).days
        
        pct_return = round(((cur_price - entry_price) / entry_price) * 100, 2)
        results.append({
            "name": name,
            "entry_price": entry_price,
            "cur_price": cur_price,
            "return": pct_return,
            "days_held": days_held
        })
        time.sleep(0.5)

    save_tracker_data(data)

    if not results:
        return

    # Sort descending by return
    results.sort(key=lambda x: x["return"], reverse=True)
    
    winners = [r for r in results if r["return"] > 0]
    win_rate = round((len(winners) / len(results)) * 100, 1)
    avg_return = round(sum(r["return"] for r in results) / len(results), 2)
    avg_sign = "+" if avg_return > 0 else ""

    msg = f"📊 *Weekly Multibagger Reliability Audit*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"🎯 *Win Rate:* `{win_rate}%` ({len(winners)}/{len(results)} profitable)\n"
    msg += f"📈 *Average Return:* `{avg_sign}{avg_return}%`\n"
    msg += f"📦 *Total Tracked Picks:* `{len(results)}`\n\n"

    msg += "🏆 *Top Performers:*\n"
    for r in results[:3]:
        r_sign = "+" if r["return"] > 0 else ""
        msg += f"• *{r['name']}*: `{r_sign}{r['return']}%` (₹{r['entry_price']} ➔ ₹{r['cur_price']}) [{r['days_held']}d]\n"

    if len(results) > 3:
        msg += "\n🔻 *Laggards / Drawdowns:*\n"
        for r in results[-2:]:
            r_sign = "+" if r["return"] > 0 else ""
            msg += f"• *{r['name']}*: `{r_sign}{r['return']}%` (₹{r['entry_price']} ➔ ₹{r['cur_price']}) [{r['days_held']}d]\n"

    send_telegram_alert(msg)
    print("Weekly report dispatched to Telegram.")

# ==================== CORE SCRAPER & SCREENER ====================

def get_company_details(session: requests.Session, company_path: str) -> tuple[str, str, float, float, float]:
    if not company_path:
        return "Industrial Ancillary", "Niche supplier serving core industry verticals.", 0.0, 0.0, 0.0
        
    full_url = BASE_URL + company_path if company_path.startswith("/") else f"{BASE_URL}/{company_path}"
    try:
        resp = session.get(full_url, timeout=10)
        if resp.status_code != 200:
            return "Industrial Ancillary", "Niche supplier serving core industry verticals.", 0.0, 0.0, 0.0
            
        soup = BeautifulSoup(resp.text, "html.parser")
        
        sector = "Industrial Ancillary"
        peers_section = soup.find("section", id="peers")
        if peers_section:
            sector_tag = peers_section.find("a", href=lambda h: h and "/market/" in h)
            if sector_tag:
                sector = sector_tag.get_text(strip=True)

        about_div = soup.find("div", class_="about") or soup.find("div", class_="company-profile")
        description = "Niche supplier serving core industry verticals."
        if about_div:
            p_tag = about_div.find("p")
            if p_tag:
                description = p_tag.get_text(strip=True)

        real_cfo = 0.0
        cashflow_sec = soup.find("section", id="cash-flow")
        if cashflow_sec:
            table = cashflow_sec.find("table", class_="data-table")
            if table:
                for row in table.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in row.find_all("td")]
                    if cells and ("cash from operating activity" in cells[0].lower() or "operating cash" in cells[0].lower()):
                        real_cfo = clean_float(cells[-1])
                        break

        debt_to_equity = 0.0
        top_ratios = soup.find("ul", id="top-ratios")
        if top_ratios:
            for li in top_ratios.find_all("li"):
                name = li.find("span", class_="name")
                val = li.find("span", class_="number")
                if name and val and "debt to equity" in name.get_text(strip=True).lower():
                    debt_to_equity = clean_float(val.get_text(strip=True))
                    break

        pledged_pct = 0.0
        sh_sec = soup.find("section", id="shareholding")
        if sh_sec:
            sh_table = sh_sec.find("table", class_="data-table")
            if sh_table:
                for row in sh_table.find_all("tr"):
                    cells = [td.get_text(strip=True) for td in row.find_all("td")]
                    if cells and "pledged" in cells[0].lower():
                        pledged_pct = clean_float(cells[-1])
                        break

        return sector, description, real_cfo, debt_to_equity, pledged_pct
    except Exception:
        return "Industrial Ancillary", "Niche supplier serving core industry verticals.", 0.0, 0.0, 0.0

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

    scored_candidates = []
    for s in stocks:
        growth = clean_float(s.get("profit_growth", "0"))
        pe = clean_float(s.get("pe", "0"))
        mcap = clean_float(s.get("mcap", "0"))

        if mcap < 20.0 or pe <= 0 or pe > 35.0:
            continue

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
        scored_candidates.append(s)

    scored_candidates.sort(key=lambda x: x["pre_score"], reverse=True)

    qualified_picks = []
    print("Verifying balance sheets & shareholding constraints...")

    for s in scored_candidates:
        sector, about_text, real_cfo, d_to_e, pledged_pct = get_company_details(session, s.get("href", ""))
        
        # Zero Promoter Pledging Check
        if pledged_pct > 0.0:
            print(f"Disqualified {s['name']}: Promoter pledged shares ({pledged_pct}%)")
            continue
            
        # Debt to Equity < 0.5 Check
        if d_to_e >= 0.5:
            print(f"Disqualified {s['name']}: Debt-to-Equity too high ({d_to_e}x)")
            continue

        s["sector"] = sector
        s["about_text"] = about_text
        s["real_cfo"] = real_cfo
        s["d_to_e"] = d_to_e
        s["pledged_pct"] = pledged_pct
        
        if d_to_e == 0.0:
            s["pre_score"] += 10.0
            
        qualified_picks.append(s)
        time.sleep(0.3)
        
        if len(qualified_picks) >= 5:
            break

    final_picks = qualified_picks if qualified_picks else scored_candidates[:5]
    total = len(final_picks)
    chunk_size = 3
    total_parts = (total + chunk_size - 1) // chunk_size

    for idx in range(0, total, chunk_size):
        batch = final_picks[idx:idx + chunk_size]
        part_num = (idx // chunk_size) + 1
        
        msg = f"🔥 *High-Conviction Multibagger Picks* ({part_num}/{total_parts})\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for s in batch:
            theme_name, catalyst_points = identify_structural_catalyst(s.get("sector", "Diversified"), s.get("about_text", ""), s)
            s["theme"] = theme_name
            
            pat = clean_float(s.get("pat", "0"))
            growth = clean_float(s.get("profit_growth", "0"))
            growth_sign = "+" if growth > 0 else ""
            real_cfo = s.get("real_cfo", 0.0)
            d_to_e = s.get("d_to_e", 0.0)
            pledged = s.get("pledged_pct", 0.0)
            
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

            s["conviction_score"] = final_score
            about_txt = s.get("about_text", "")
            short_about = (about_txt[:115] + "...") if len(about_txt) > 115 else about_txt
            bullets = "\n".join([f"    • {p}" for p in catalyst_points])
            
            msg += f"🏢 *{s['name']}* (Score: `{final_score:.0f}/100`)\n"
            msg += f"├ 💰 *Valuation:* ₹{s['cmp']} | *P/E:* {s['pe']}x | *MCap:* ₹{s['mcap']} Cr\n"
            msg += f"├ 📈 *Earnings Velocity:* Qtr PAT Var: {growth_sign}{s['profit_growth']}%\n"
            msg += f"├ 🛡️ *Cash Quality:* {cash_badge}\n"
            msg += f"│   `Annual CFO: ₹{real_cfo:.1f} Cr | Qtr PAT: ₹{pat:.1f} Cr`\n"
            msg += f"├ 🏛️ *Balance Sheet:* D/E: `{d_to_e:.2f}x` | Pledge: `{pledged:.1f}%`\n"
            msg += f"├ 🏭 *Theme:* {theme_name}\n"
            msg += f"│   _{short_about}_\n"
            msg += f"└ 🚀 *Catalysts & Tailwinds:*\n{bullets}\n\n"

        send_telegram_alert(msg)
        time.sleep(1.5)

    # Record alerted picks to persistent database
    record_new_alerts(final_picks)

def main():
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SCREENER_URL]):
        print("Error: Missing environment variables.", file=sys.stderr)
        sys.exit(1)
        
    stocks, session = fetch_screener_stocks(SCREENER_URL)
    print(f"Total raw matches from Screener: {len(stocks)}")
    send_ranked_conviction_alerts(stocks, session)
    
    # Run performance audit (automatically runs on Fridays, or tracks ongoing prices)
    run_weekly_performance_report(session, force_run=False)

if __name__ == "__main__":
    main()
