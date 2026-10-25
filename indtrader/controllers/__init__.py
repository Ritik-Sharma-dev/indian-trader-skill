"""The controller layer: one module per command area.

Each handler takes ``(args, ctx)``, asks the models for data, prints a view
of it (or JSON with ``--json``) and returns the exit code. ``agents`` runs an
agent and saves its report.
"""
