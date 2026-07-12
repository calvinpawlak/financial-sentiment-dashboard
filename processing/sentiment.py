"""
Layer 2 - sentiment scoring via VADER (vaderSentiment).

VADER (Valence Aware Dictionary and sEntiment Reasoner) is tuned for short,
informal social-media-style text - slang, ALL CAPS emphasis, punctuation
like "!!!", emoticons - which is exactly what Reddit/StockTwits posts look
like, and it holds up reasonably well on news headlines too. This is why it
was chosen over TextBlob for this pipeline.

Classification uses VADER's own documented convention for its compound
score (-1 most negative to +1 most positive):
    compound >= 0.05   -> bullish
    compound <= -0.05  -> bearish
    otherwise          -> neutral

Note this is *not* directly comparable to the reference project
indiser/market-sentiment-analyzer, which uses TextBlob polarity thresholds
of +0.1 / -0.1 - different underlying models, different scales, even though
both happen to range roughly -1..+1.

Usage:
    from processing.sentiment import score_new_rows
    score_new_rows()   # scores everything not yet in scored_sentiment
"""
import logging
from datetime import datetime, timezone

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from storage.db import get_conn, get_unscored, insert_scored_sentiment

logger = logging.getLogger(__name__)

_analyzer = SentimentIntensityAnalyzer()

# VADER's general-purpose lexicon misreads common financial slang - e.g.
# "Nvidia crushes expectations" scored bearish (compound -0.44) out of the
# box, because "crushes" reads as violent/destructive in everyday English.
# These overrides nudge a handful of unambiguous finance terms toward their
# actual market meaning. Magnitudes follow VADER's own lexicon scale
# (roughly -4 to +4). Deliberately left out anything context-dependent
# either way (e.g. "dip" - "buy the dip" is bullish slang, "the stock
# dipped" is describing a decline - guessing wrong there would be worse
# than leaving it to VADER's general-purpose default).
_FINANCE_LEXICON_OVERRIDES = {
    "crush": 2.5, "crushes": 2.5, "crushed": 2.5,      # "crushed earnings" = beat big
    "beat": 2.0, "beats": 2.0,
    "miss": -2.0, "misses": -2.0, "missed": -2.0,      # "missed estimates"
    "bullish": 2.5, "bearish": -2.5,
    "moon": 2.0, "mooning": 2.5,                       # "to the moon"
    "rally": 1.8, "rallies": 1.8, "rallying": 1.8,
    "selloff": -2.0, "sell-off": -2.0,
    "downgrade": -2.0, "downgraded": -2.0,
    "upgrade": 2.0, "upgraded": 2.0,
}
_analyzer.lexicon.update(_FINANCE_LEXICON_OVERRIDES)

BULLISH_THRESHOLD = 0.05
BEARISH_THRESHOLD = -0.05

# (origin_table, text_column) pairs to score. raw_social has a "text" field
# (post/message body); raw_news only has a "title" (headline) to score.
_SCORABLE_SOURCES = [
    ("raw_social", "text"),
    ("raw_news", "title"),
]


def classify(compound: float) -> str:
    if compound >= BULLISH_THRESHOLD:
        return "bullish"
    if compound <= BEARISH_THRESHOLD:
        return "bearish"
    return "neutral"


def score_text(text: str) -> dict:
    """Run VADER on a single piece of text. Returns compound/pos/neu/neg
    scores plus a bullish/bearish/neutral label."""
    text = text or ""
    scores = _analyzer.polarity_scores(text)
    return {
        "compound": scores["compound"],
        "pos": scores["pos"],
        "neu": scores["neu"],
        "neg": scores["neg"],
        "label": classify(scores["compound"]),
    }


def score_new_rows() -> int:
    """Score every raw_social/raw_news row that doesn't already have a
    scored_sentiment entry. Safe to call repeatedly - already-scored rows
    are skipped via the (origin_table, origin_id) UNIQUE constraint.
    Returns the number of newly scored rows."""
    scored_at = datetime.now(timezone.utc).isoformat()
    total = 0

    with get_conn() as conn:
        for origin_table, text_column in _SCORABLE_SOURCES:
            rows = get_unscored(conn, origin_table, text_column)
            for row_id, ticker, source, text in rows:
                result = score_text(text)
                insert_scored_sentiment(
                    conn, origin_table, row_id, ticker, source, text,
                    result["compound"], result["pos"], result["neu"], result["neg"],
                    result["label"], scored_at,
                )
                total += 1

    logger.info("Scored %d new rows", total)
    return total
