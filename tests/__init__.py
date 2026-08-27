"""Test package marker.

Without this, `from tests.test_brain import ...` in test_push_quality.py fails
collection and takes the entire suite with it - only single-file runs worked.
"""
