"""
doc_classifier.py
=================
Example-driven document-type classifier. You name the types and show a few
example documents of each; it builds one prototype vector per type, then labels
any document by nearest prototype above a calibrated cutoff (REVIEW below it).
No training — the examples ARE the model. Add a type by dropping in examples.

Backends (auto-selected):
  * sentence-transformers  — semantic embeddings (preferred; matches on meaning).
  * TF-IDF                 — word-overlap fallback when the model isn't installed,
                             so this runs anywhere. Same retrieval logic; only the
                             vectorizer changes.

Typical use (batch, the way the inventory stage calls it):
    from doc_classifier import DocClassifier, load_examples
    clf = DocClassifier(load_examples(r"C:\\Bulk\\doc_type_examples"))
    labels, thr = clf.classify_batch({inv_id: text, ...})
    # labels: {inv_id: (doc_type | "REVIEW", score)}

Example layout on disk (one subfolder per type):
    doc_type_examples/
        Final Well Report/   fwr1.pdf  fwr2.pdf
        Completion Report/   comp1.pdf comp2.docx
        Petrophysics Report/ petro1.pdf
"""
from __future__ import annotations
import os
import glob
import numpy as np

DOC_TEXT_EXTS = {".pdf", ".docx", ".doc", ".txt", ".rtf", ".md", ".html", ".htm"}


# ── text sampling ───────────────────────────────────────────────────────────

def sample_text(path: str, max_pages: int = 2, max_chars: int = 6000) -> str:
    """First couple of pages of a document as plain text — enough to judge TYPE
    without a full extract. Lazy imports so the module loads without pdf libs."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pdf":
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                txt = "\n".join((p.extract_text() or "") for p in pdf.pages[:max_pages])
            return txt[:max_chars]
        if ext in (".docx",):
            import docx  # python-docx
            d = docx.Document(path)
            return "\n".join(p.text for p in d.paragraphs)[:max_chars]
        if ext in (".txt", ".md", ".csv", ".html", ".htm", ".rtf"):
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                return fh.read(max_chars)
    except Exception:
        return ""
    return ""


def load_examples(examples_dir: str) -> dict:
    """Read {type_name: [text, ...]} from per-type subfolders of examples_dir."""
    examples = {}
    if not os.path.isdir(examples_dir):
        return examples
    for name in sorted(os.listdir(examples_dir)):
        sub = os.path.join(examples_dir, name)
        if not os.path.isdir(sub):
            continue
        texts = []
        for fp in glob.glob(os.path.join(sub, "*")):
            if os.path.splitext(fp)[1].lower() in DOC_TEXT_EXTS:
                t = sample_text(fp)
                if t.strip():
                    texts.append(t)
        if texts:
            examples[name] = texts
    return examples


# ── helpers ─────────────────────────────────────────────────────────────────

def _l2(M):
    M = np.asarray(M, dtype=float)
    if M.ndim == 1:
        return M / (np.linalg.norm(M) + 1e-9)
    return M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)


def _have_sentence_transformers() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return True
    except Exception:
        return False


# ── classifier ──────────────────────────────────────────────────────────────

class DocClassifier:
    """Build type prototypes from example texts; classify documents by nearest
    prototype above a self-calibrated threshold."""

    def __init__(self, examples: dict, backend: str = "auto",
                 model_name: str = "all-MiniLM-L6-v2", margin: float = 0.5):
        if not examples:
            raise ValueError("examples is empty — provide {type: [texts]}")
        self.types = list(examples)
        self.examples = examples
        self.margin = margin
        self.backend = (("st" if _have_sentence_transformers() else "tfidf")
                        if backend == "auto" else backend)
        self._model = None
        self._tfidf = None
        if self.backend == "st":
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(model_name)
            self._protos, self._thr = self._fit_static()

    # ST path: prototypes built once, reused across batches (inductive).
    def _encode_st(self, texts):
        return _l2(self._model.encode(list(texts), show_progress_bar=False))

    def _fit_static(self):
        proto, sims_self = [], []
        ex_vecs = {t: self._encode_st(self.examples[t]) for t in self.types}
        for t in self.types:
            proto.append(_l2(ex_vecs[t].mean(axis=0)))
        protos = np.vstack(proto)
        thr = self._calibrate(ex_vecs, protos)
        return protos, thr

    def _calibrate(self, ex_vecs: dict, protos):
        """Threshold = midpoint between the loosest example-to-own-prototype sim
        and the tightest example-to-OTHER-prototype sim. Scale-independent, so it
        works for both embeddings and TF-IDF."""
        self_sims, cross_sims = [], []
        for ti, t in enumerate(self.types):
            S = ex_vecs[t] @ protos.T            # (n_ex, n_types)
            self_sims += list(S[:, ti])
            for tj in range(len(self.types)):
                if tj != ti:
                    cross_sims += list(S[:, tj])
        lo_self = float(np.min(self_sims))
        hi_cross = float(np.max(cross_sims)) if cross_sims else 0.0
        if hi_cross >= lo_self:                  # overlapping; fall back to margin
            return round(lo_self * self.margin, 4)
        return round(hi_cross + (lo_self - hi_cross) * 0.5, 4)

    def classify_batch(self, corpus: dict):
        """corpus: {doc_id: text}. Returns ({doc_id: (type|'REVIEW', score)}, threshold)."""
        ids = [d for d in corpus if (corpus[d] or "").strip()]
        if not ids:
            return {}, getattr(self, "_thr", 0.0)

        if self.backend == "st":
            protos, thr = self._protos, self._thr
            doc_vecs = self._encode_st([corpus[d] for d in ids])
        else:
            # TF-IDF is transductive: fit on examples + this batch, rebuild protos.
            from sklearn.feature_extraction.text import TfidfVectorizer
            ex_texts, ex_owner = [], []
            for t in self.types:
                for x in self.examples[t]:
                    ex_texts.append(x); ex_owner.append(t)
            vec = TfidfVectorizer(stop_words="english")
            X = vec.fit_transform(ex_texts + [corpus[d] for d in ids]).toarray()
            Xex, doc_vecs = _l2(X[:len(ex_texts)]), _l2(X[len(ex_texts):])
            ex_vecs = {t: Xex[[i for i, o in enumerate(ex_owner) if o == t]]
                       for t in self.types}
            protos = np.vstack([_l2(ex_vecs[t].mean(axis=0)) for t in self.types])
            thr = self._calibrate(ex_vecs, protos)

        sims = doc_vecs @ protos.T               # (n_docs, n_types)
        out = {}
        for i, d in enumerate(ids):
            b = int(np.argmax(sims[i])); sc = round(float(sims[i][b]), 4)
            out[d] = (self.types[b] if sc >= thr else "REVIEW", sc)
        for d in corpus:
            out.setdefault(d, ("REVIEW", 0.0))   # empty-text docs -> review
        return out, thr
