"""Operational scripts that ship with the image (`python -m scripts.seed`).

A package rather than loose files so the seeded fixtures can be imported by name —
``tests/`` runs the *real* seed function rather than a copy of it, which is the only
way a test can prove the demo's own artifact works.
"""
