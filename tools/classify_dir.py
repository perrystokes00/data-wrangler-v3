"""
classify_dir.py  --  run doc_classifier.py against a folder
===========================================================
doc_classifier.py is a library (no main). This is the thing you actually run.

It builds the classifier from an EXAMPLES folder (one subfolder per doc type),
then labels every document in a SCAN folder by nearest type prototype.

Examples folder layout (the examples ARE the model):
    doc_type_examples/
        Final Well Report/    fwr1.pdf  fwr2.pdf
        Completion Report/    comp1.pdf comp2.docx
        Petrophysics Report/  petro1.pdf

Usage
-----
    # classify a separate folder of documents
    python classify_dir.py --examples "C:\\Bulk\\doc_type_examples" ^
                           --scan     "C:\\Bulk\\to_classify"

    # quick smoke test: classify the example files themselves
    python classify_dir.py --examples "C:\\Bulk\\doc_type_examples" --selftest

Options
-------
    --backend {auto,st,tfidf}   force a backend (default: auto)
    --model   <name>            sentence-transformers model (default MiniLM)
    --margin  <float>           fallback threshold scale (default 0.5)
    --recursive                 recurse into the scan folder
"""
from __future__ import annotations
import argparse
import os
import sys

# import the library that lives next to this script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from doc_classifier import (DocClassifier, load_examples, sample_text,
                            DOC_TEXT_EXTS)


def _gather(folder: str, recursive: bool) -> list:
    """All classifiable files under folder."""
    hits = []
    if recursive:
        for root, _dirs, files in os.walk(folder):
            for f in files:
                if os.path.splitext(f)[1].lower() in DOC_TEXT_EXTS:
                    hits.append(os.path.join(root, f))
    else:
        for f in sorted(os.listdir(folder)):
            fp = os.path.join(folder, f)
            if os.path.isfile(fp) and \
               os.path.splitext(f)[1].lower() in DOC_TEXT_EXTS:
                hits.append(fp)
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description="Classify a folder of documents.")
    ap.add_argument("--examples", required=True,
                    help="folder with one subfolder per doc type")
    ap.add_argument("--scan", help="folder of documents to classify")
    ap.add_argument("--selftest", action="store_true",
                    help="classify the example files themselves")
    ap.add_argument("--backend", default="auto",
                    choices=["auto", "st", "tfidf"])
    ap.add_argument("--model", default="all-MiniLM-L6-v2")
    ap.add_argument("--margin", type=float, default=0.5)
    ap.add_argument("--recursive", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.examples):
        sys.exit(f"examples folder not found: {args.examples}")
    if not args.scan and not args.selftest:
        sys.exit("give --scan <folder> or --selftest")

    print(f"Loading examples from: {args.examples}")
    examples = load_examples(args.examples)
    if not examples:
        sys.exit("No examples found. The examples folder must contain one "
                 "SUBFOLDER per doc type, each holding a few example files "
                 "(.pdf/.docx/.txt...). A flat pile of files won't work.")
    for t, texts in examples.items():
        print(f"  · {t}: {len(texts)} example(s)")

    clf = DocClassifier(examples, backend=args.backend,
                        model_name=args.model, margin=args.margin)
    print(f"Backend: {clf.backend}  ({'semantic embeddings' if clf.backend=='st' else 'TF-IDF word overlap'})")

    target = args.scan if args.scan else args.examples
    recursive = args.recursive or args.selftest
    files = _gather(target, recursive)
    if not files:
        sys.exit(f"No classifiable documents found in: {target}")
    print(f"Classifying {len(files)} document(s) from: {target}\n")

    corpus = {fp: sample_text(fp) for fp in files}
    labels, thr = clf.classify_batch(corpus)

    rows = sorted(labels.items(), key=lambda kv: (kv[1][0], -kv[1][1]))
    name_w = min(60, max(len(os.path.basename(p)) for p in labels))
    print(f"{'document':<{name_w}}  {'type':<24} score")
    print("-" * (name_w + 34))
    review = 0
    for path, (label, score) in rows:
        if label == "REVIEW":
            review += 1
        print(f"{os.path.basename(path):<{name_w}}  {label:<24} {score:.3f}")
    print("-" * (name_w + 34))
    print(f"threshold {thr:.3f}  ·  {len(labels)} doc(s)  ·  "
          f"{review} sent to REVIEW")


if __name__ == "__main__":
    main()
