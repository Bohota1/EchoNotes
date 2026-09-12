"""Topic extraction - NexaNota Section 4.1.

"Each time when user uploaded a lecture video, 2 to 3 topics can be
subtracted from the transcribed text." This is a direct LLM extraction on
every note, unlike the old Idea11y-based `app.understanding.organizer`,
which tried to match a note against topics that already existed before
asking an LLM at all. NexaNota always asks fresh; existing-topic reuse
happens afterwards, by exact/fuzzy name match against what the extraction
returned (see `app.graph.service`), not by embedding-distance search.

Every LLM call here has a deterministic fallback, per the project-wide rule
in `app/llm/base.py` ("every caller is expected to have a non-LLM path") -
a note is never left unfiled just because no API key is configured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import get_settings

_SYSTEM = (
    "You extract lecture note topics. Given a short piece of transcribed "
    "speech, name 2 to 3 short topics (2-4 words each) it is actually "
    "about - specific enough to be useful ('Deadlock avoidance', not "
    "'Computer science'). Reply with JSON only: "
    '{"topics": [{"name": "...", "confidence": 0.0-1.0}, ...]}. '
    "confidence reflects how clearly the text is about that topic."
)


@dataclass(frozen=True)
class ExtractedTopic:
    name: str
    confidence: float


# --- rules-only vocabulary --------------------------------------------------
#
# The generic fallback below (a contiguous-run-of-content-words heuristic)
# cannot tell a real concept from an accidental run of words: "linked list"
# and "mainly allows efficient insertion" score the same way to it, because
# it only knows grammar (stopword or not), not vocabulary. It also can never
# produce a single-word topic ("Stack"), because it requires two or more
# content words in a row to even form a candidate.
#
# This table fixes both problems for known CS terms: a curated list of
# actual course vocabulary, spanning the subjects these notes are about
# (data structures, algorithms, operating systems, databases, networking,
# OOP, and machine learning), matched directly against the text - including
# single words - and given priority over the generic heuristic. It is not
# exhaustive; it only needs to cover common terms well enough that a note
# like "a linked list ... implement stack, queue and deque" produces
# `Linked List`, `Stack`, `Queue` instead of sentence fragments.
#
# Each canonical name maps to the surface forms (lowercase) that should
# resolve to it - plurals and common spelling variants included, since the
# text is never normalized before matching.
_CS_VOCABULARY: dict[str, tuple[str, ...]] = {
    # --- data structures ---
    "Linked List": (
        "linked list",
        "linked lists",
        "singly linked list",
        "doubly linked list",
        "circular linked list",
    ),
    "Array": ("array", "arrays", "dynamic array", "dynamic arrays"),
    "Stack": ("stack", "stacks"),
    "Queue": ("queue", "queues", "priority queue", "priority queues"),
    "Deque": ("deque", "deques", "double ended queue", "double-ended queue"),
    "Binary Search Tree": ("binary search tree", "binary search trees", "bst"),
    "Binary Tree": ("binary tree", "binary trees"),
    "AVL Tree": ("avl tree", "avl trees"),
    "Red-Black Tree": ("red-black tree", "red black tree", "red-black trees"),
    "Heap": ("heap", "heaps", "min heap", "max heap", "min-heap", "max-heap"),
    "Hash Table": (
        "hash table",
        "hash tables",
        "hash map",
        "hash maps",
        "hashmap",
        "hashing",
    ),
    "Trie": ("trie", "tries"),
    "Graph": ("graph", "graphs", "adjacency list", "adjacency matrix"),
    "B-Tree": ("b-tree", "b tree", "b+ tree", "b-trees"),
    # --- algorithms ---
    "Recursion": ("recursion", "recursive"),
    "Merge Sort": ("merge sort", "merge sorts"),
    "Quick Sort": ("quick sort", "quicksort"),
    "Bubble Sort": ("bubble sort",),
    "Insertion Sort": ("insertion sort",),
    "Selection Sort": ("selection sort",),
    "Binary Search": ("binary search",),
    "Linear Search": ("linear search",),
    "Depth First Search": ("depth first search", "depth-first search", "dfs"),
    "Breadth First Search": ("breadth first search", "breadth-first search", "bfs"),
    "Dynamic Programming": ("dynamic programming",),
    "Greedy Algorithm": ("greedy algorithm", "greedy algorithms"),
    "Divide And Conquer": ("divide and conquer",),
    "Backtracking": ("backtracking",),
    "Time Complexity": ("time complexity",),
    "Space Complexity": ("space complexity",),
    "Big O Notation": ("big o notation", "big-o notation", "big o"),
    "Algorithm": ("algorithm", "algorithms"),
    # --- operating systems ---
    "Process": ("process", "processes"),
    "Thread": ("thread", "threads", "multithreading"),
    "Deadlock": ("deadlock", "deadlocks"),
    "Mutual Exclusion": ("mutual exclusion",),
    "Circular Wait": ("circular wait",),
    "Scheduling": ("scheduling", "round robin scheduling", "round-robin scheduling"),
    "Semaphore": ("semaphore", "semaphores"),
    "Mutex": ("mutex", "mutexes"),
    "Race Condition": ("race condition", "race conditions"),
    "Context Switch": ("context switch", "context switching"),
    "Virtual Memory": ("virtual memory",),
    "Page Fault": ("page fault", "page faults", "page replacement"),
    "Paging": ("paging",),
    "Segmentation": ("segmentation",),
    "Operating System": ("operating system", "operating systems"),
    "Kernel": ("kernel",),
    "System Call": ("system call", "system calls"),
    "Interrupt": ("interrupt", "interrupts"),
    "Critical Section": ("critical section", "critical sections"),
    "Synchronization": ("synchronization", "synchronisation"),
    "Starvation": ("starvation",),
    # --- databases ---
    "Database": ("database", "databases"),
    "Index": ("index", "indexes", "indices"),
    "Primary Key": ("primary key", "primary keys"),
    "Foreign Key": ("foreign key", "foreign keys"),
    "Normalization": ("normalization", "normalisation"),
    "Transaction": ("transaction", "transactions"),
    "ACID": ("acid properties", "acid"),
    "Schema": ("database schema", "schema design"),
    "SQL": ("sql",),
    "NoSQL": ("nosql", "no sql"),
    # --- networking ---
    "TCP": ("tcp",),
    "UDP": ("udp",),
    "Protocol": ("protocol", "protocols"),
    "Packet": ("packet", "packets"),
    "Socket": ("socket", "sockets"),
    "DNS": ("dns",),
    "HTTP": ("http", "https"),
    # --- object-oriented programming ---
    "Inheritance": ("inheritance",),
    "Polymorphism": ("polymorphism",),
    "Encapsulation": ("encapsulation",),
    "Abstraction": ("abstraction",),
    "Pointer": ("pointer", "pointers"),
    # --- machine learning ---
    "Machine Learning": ("machine learning",),
    "Gradient Descent": ("gradient descent",),
    "Loss Function": ("loss function", "loss functions"),
    "Learning Rate": ("learning rate", "learning rates"),
    "Neural Network": ("neural network", "neural networks"),
    "Backpropagation": ("backpropagation", "back propagation"),
    "Overfitting": ("overfitting",),
    "Supervised Learning": ("supervised learning",),
    "Unsupervised Learning": ("unsupervised learning",),
    "Reinforcement Learning": ("reinforcement learning",),
}


def _build_vocabulary_patterns() -> list[tuple[str, re.Pattern[str]]]:
    """One compiled pattern per canonical term, matching any of its known
    surface forms - and ordered so multi-word forms are tried before
    shorter ones, so e.g. "binary search tree" claims its full span before
    the bare word "tree" (not in this table, but the principle also applies
    between entries like "hash table" and a hypothetical bare "table")."""
    entries: list[tuple[str, re.Pattern[str], int]] = []
    for canonical, forms in _CS_VOCABULARY.items():
        alternatives = sorted({re.escape(f) for f in forms}, key=len, reverse=True)
        pattern = re.compile(r"\b(?:" + "|".join(alternatives) + r")\b", re.IGNORECASE)
        max_words = max(len(f.split()) for f in forms)
        entries.append((canonical, pattern, max_words))
    entries.sort(key=lambda e: -e[2])
    return [(canonical, pattern) for canonical, pattern, _ in entries]


_VOCAB_PATTERNS = _build_vocabulary_patterns()


def _vocabulary_matches(text: str) -> list[tuple[str, int, int]]:
    """Known CS terms found in `text`, in reading order, with no overlaps:
    once a span is claimed (checked longest-term-first) it can't also become
    part of a shorter match, e.g. "binary search tree" wins outright rather
    than also registering as a separate "binary search" hit."""
    claimed: list[tuple[int, int]] = []
    found: list[tuple[str, int, int]] = []
    for canonical, pattern in _VOCAB_PATTERNS:
        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            if any(start < c_end and end > c_start for c_start, c_end in claimed):
                continue
            claimed.append((start, end))
            found.append((canonical, start, end))
    found.sort(key=lambda t: t[1])
    return found


def _fallback_extract(text: str, limit: int) -> list[ExtractedTopic]:
    """Deterministic extraction with no LLM.

    Two passes, in priority order:

    1. Known CS vocabulary (`_CS_VOCABULARY`) - real named concepts matched
       against a curated term list. These win over pass 2 whenever they're
       found, and unlike pass 2 they can be a single word ("Stack", "DFS"),
       because they're matched by meaning, not by word-counting.
    2. `app.understanding.entities.extract_key_phrases` - the same
       noun-phrase-shaped, contiguous-content-word extraction already used
       for the Understanding view's "Key phrases" list - fills any slots
       vocabulary didn't cover. It has no notion of which words form a real
       concept, so it is only trusted as a fallback of last resort: on
       ordinary speech it is as likely to surface "mainly allows efficient
       insertion" as anything a note is actually about.
    """
    from app.understanding.entities import extract_key_phrases

    topics: list[ExtractedTopic] = []
    seen: set[str] = set()

    for canonical, _start, _end in _vocabulary_matches(text):
        key = canonical.lower()
        if key in seen:
            continue
        seen.add(key)
        topics.append(ExtractedTopic(name=canonical, confidence=0.7))
        if len(topics) >= limit:
            return topics

    remaining = limit - len(topics)
    if remaining > 0:
        phrases = extract_key_phrases(text, limit=remaining * 3)
        for phrase in phrases:
            name = phrase.value.title()
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            topics.append(ExtractedTopic(name=name, confidence=min(1.0, phrase.confidence)))
            if len(topics) >= limit:
                break

    return topics or [ExtractedTopic(name=get_settings().default_subject_name, confidence=0.2)]


def extract_topics(text: str, *, min_topics: int = 2, max_topics: int = 3) -> list[ExtractedTopic]:
    """2-3 topics for one note's text. Never raises: an LLM failure falls
    back to `_fallback_extract` rather than leaving the note unfiled."""
    text = (text or "").strip()
    if not text:
        return []

    from app.llm import get_llm_client

    client = get_llm_client()
    if not client.available:
        return _fallback_extract(text, max_topics)

    try:
        result = client.complete_json(
            f"Text:\n{text}\n\nExtract {min_topics} to {max_topics} topics.",
            system=_SYSTEM,
            max_tokens=300,
        )
        raw = result.get("topics", []) if isinstance(result, dict) else []
        topics = [
            ExtractedTopic(
                name=str(item.get("name", "")).strip(),
                confidence=float(item.get("confidence", 0.6) or 0.6),
            )
            for item in raw
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
        if topics:
            return topics[:max_topics]
    except Exception:
        pass

    return _fallback_extract(text, max_topics)
