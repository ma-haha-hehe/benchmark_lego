from __future__ import annotations

import argparse
from metrics import load_metrics_csv, summarize_metrics, print_summary_table


def parse_args():
    parser = argparse.ArgumentParser(description="Summarize evaluation CSV results")
    parser.add_argument("--csv", type=str, required=True, help="Path to evaluation CSV")
    return parser.parse_args()


def main():
    args = parse_args()

    rows = load_metrics_csv(args.csv)
    summary = summarize_metrics(rows)
    print_summary_table(summary)


if __name__ == "__main__":
    main()