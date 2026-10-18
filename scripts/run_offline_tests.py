#!/usr/bin/env python3
"""Run the complete default offline suite, including unittest and pytest tests.

The explicitly live Elasticsearch module is named ``live_concept_acceptance``
and is not collected by pytest's default ``test_*.py`` discovery pattern.
"""

from __future__ import annotations

import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
raise SystemExit(pytest.main(["-q", str(ROOT / "tests")]))
