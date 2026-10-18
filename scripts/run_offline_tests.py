#!/usr/bin/env python3
"""Run all unittest modules except the explicitly live Elasticsearch suite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

suite = unittest.defaultTestLoader.discover(
    str(ROOT / "tests"), pattern="test_*.py"
)
offline = unittest.TestSuite()
for group in suite:
    for test in group:
        module = getattr(test, "__module__", "")
        if module.endswith(("test_concept_live_acceptance", "live_concept_acceptance")):
            continue
        offline.addTest(test)
result = unittest.TextTestRunner(verbosity=2).run(offline)
raise SystemExit(not result.wasSuccessful())
