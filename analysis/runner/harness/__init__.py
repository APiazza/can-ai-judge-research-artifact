"""Harness for the AI review runs: prompt templates, model calls, run records.

Review runs and coding runs are separate entry points. A review run can read only the AI-run inputs
folder; it never receives the key path, and it checks before each batch that no file it reads is the key.
"""

HARNESS_VERSION = "0.1.0"
