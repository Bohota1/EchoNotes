"""Download the NLTK data the LNT pipeline needs. Run once after installing requirements.

    python scripts/bootstrap_nltk.py
"""

import nltk

PACKAGES = [
    "punkt",                              # sentence tokenization (Section 3.4.5)
    "punkt_tab",
    "stopwords",                          # stop-word removal (Section 3.4.1)
    "wordnet",                            # WordNetLemmatizer / Morphy (Section 3.4.2)
    "omw-1.4",
    "averaged_perceptron_tagger",         # POS tags for lemmatization and proper-noun scoring
    "averaged_perceptron_tagger_eng",
    "maxent_ne_chunker",                  # named entities (Feature 5)
    "maxent_ne_chunker_tab",
    "words",
]


def main() -> None:
    for package in PACKAGES:
        print(f"downloading {package} ...")
        nltk.download(package)
    print("done")


if __name__ == "__main__":
    main()
