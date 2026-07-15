"""SEC EDGAR company filing events via the official JSON APIs."""
import logging
from datetime import datetime, timezone

import requests

from config.settings import SEC_FILINGS_PER_TICKER, SEC_FORMS, SEC_USER_AGENT, TICKERS

logger = logging.getLogger(__name__)
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"


def _headers():
    if not SEC_USER_AGENT:
        raise RuntimeError("SEC_USER_AGENT is not configured in .env")
    return {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}


def fetch_recent_filings(tickers=None, limit=SEC_FILINGS_PER_TICKER):
    tickers = tickers or TICKERS
    headers = _headers()
    response = requests.get(TICKER_MAP_URL, headers=headers, timeout=30)
    response.raise_for_status()
    ticker_map = {row["ticker"].upper(): row for row in response.json().values()}
    ingested_at = datetime.now(timezone.utc).isoformat()
    events = []
    for ticker in tickers:
        company = ticker_map.get(ticker.upper())
        if not company:
            logger.info("No SEC company mapping for %s; skipping", ticker)
            continue
        cik = int(company["cik_str"])
        filing_response = requests.get(SUBMISSIONS_URL.format(cik=cik), headers=headers, timeout=30)
        filing_response.raise_for_status()
        recent = filing_response.json().get("filings", {}).get("recent", {})
        accepted = 0
        for form, accession, document, filing_date in zip(
            recent.get("form", []), recent.get("accessionNumber", []),
            recent.get("primaryDocument", []), recent.get("filingDate", []),
        ):
            if form not in SEC_FORMS:
                continue
            compact_accession = accession.replace("-", "")
            events.append({
                "ticker": ticker, "source": "sec_edgar", "category": form,
                "title": f"{form} filing - {company['title']}",
                "link": ARCHIVES_URL.format(cik=cik, accession=compact_accession, document=document),
                "published_at": filing_date, "ingested_at": ingested_at,
            })
            accepted += 1
            if accepted >= limit:
                break
    return events
