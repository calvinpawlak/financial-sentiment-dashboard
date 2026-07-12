"""
Quick CLI sentiment summary - a preview of what the layer 4 dashboard will
eventually show, and a fast way to sanity-check layer 2 scoring. Run any
time after main.py has ingested and scored at least one cycle's worth of
data:

    python report.py            # last 24 hours
    python report.py --hours 6  # custom window
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage.queries import get_sentiment_summary, verdict_for, get_signal, get_latest_social_sentiment_agg


def main():
    parser = argparse.ArgumentParser(description="Sentiment summary from scored_sentiment.")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours (default 24).")
    args = parser.parse_args()

    summary = get_sentiment_summary(args.hours)

    print(f"\nSentiment summary - last {args.hours}h")
    print("-" * 78)
    if not summary:
        print("No scored data yet - run `python main.py` at least once first.")
        return

    for ticker in sorted(summary):
        counts = summary[ticker]
        total = sum(counts.values())
        verdict = verdict_for(counts)
        signal = get_signal(ticker, hours=args.hours)["signal"]
        print(
            f"{ticker:6s}  bullish={counts['bullish']:4d}  bearish={counts['bearish']:4d}  "
            f"neutral={counts['neutral']:4d}  (n={total:4d})   verdict={verdict:14s}  signal={signal}"
        )
        social_agg = get_latest_social_sentiment_agg(ticker)
        agg_parts = []
        for platform in ("reddit", "twitter"):
            info = social_agg.get(platform)
            if info and info["mention"] is not None:
                agg_parts.append(
                    f"{platform}: {info['mention']} mentions "
                    f"(+{info['positive_score']:.2f}/-{info['negative_score']:.2f})"
                )
        if agg_parts:
            print(f"        Finnhub social (supplementary, not in counts above): {', '.join(agg_parts)}")
    print()
    print("Note: sentiment verdicts are heuristic; the BUY/SELL/HOLD signal is a simple")
    print("mechanical rule (sentiment + price direction) - neither is financial advice.")
    print("Finnhub social sentiment lines (if shown) are a separate, pre-aggregated source -")
    print("not merged into the bullish/bearish/neutral counts above. Treat all of this as")
    print("one input among many, and do your own research.")


if __name__ == "__main__":
    main()
