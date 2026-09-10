"""Run the LNT pipeline over an audio file from the command line, for paper replication.

    python scripts/run_lnt.py path/to/lecture.wav --language hi --top-k 10

Prints the transcript, the extractive summary, the extracted themes and topics, and the four
quality metrics with Qi - the same outputs the paper reports in Tables 5 and 6.
"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the LNT framework over one recording")
    parser.add_argument("audio", help="path to the recording")
    parser.add_argument("--language", default=None, help="ISO-639-1 source language; auto-detect if omitted")
    parser.add_argument("--top-k", type=int, default=10, help="sentences in the summary (paper's K)")
    parser.add_argument("--topics", type=int, default=9, help="LDA topic count")
    args = parser.parse_args()
    raise NotImplementedError


if __name__ == "__main__":
    main()
