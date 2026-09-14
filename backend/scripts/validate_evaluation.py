"""Validate the frozen evaluation package without calling a model or database."""

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EVALUATION = ROOT / "evaluation" / "v1"
EXPECTED_CATEGORIES = {
    "direct",
    "new_input_application",
    "paraphrase",
    "ambiguous",
    "false_premise",
    "unavailable_information",
    "document_scope",
    "prompt_injection",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    manifest = _load(EVALUATION / "manifest.json")
    assert _hash(ROOT / "backend" / "app" / "chat" / "prompt.py") == manifest["tutor_prompt_sha256"]
    corpus_names = set(manifest["corpus"])
    for name, expected_hash in manifest["corpus"].items():
        assert _hash(EVALUATION / "corpus" / name) == expected_hash

    all_ids: set[str] = set()
    for split in ("development", "holdout"):
        path = EVALUATION / f"{split}.json"
        assert _hash(path) == manifest[f"{split}_sha256"]
        package = _load(path)
        cases = package["cases"]
        assert package["split"] == split
        assert len(cases) == 8
        assert {case["category"] for case in cases} == EXPECTED_CATEGORIES
        for case in cases:
            assert case["case_id"] not in all_ids
            all_ids.add(case["case_id"])
            assert case["question"].strip()
            assert case["expected_status"] in {"answered", "insufficient_context"}
            assert set(case["document_scope"]) <= corpus_names
            assert set(case["supporting_sources"]) <= set(case["document_scope"])
            assert isinstance(case["required_points"], list)
            assert isinstance(case["forbidden_points"], list)
            assert case["rationale"].strip()

    print("version=rag-eval-v1")
    print("development_cases=8")
    print("holdout_cases=8")
    print("corpus_documents=4")
    print("validation=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
