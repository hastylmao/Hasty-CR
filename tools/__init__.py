"""Offline tooling: calibration, emulator capture, replay comparison.

This file is deliberately not empty of purpose. Without it `tools/` is only a
namespace portion, and Python's import system lets a *regular* package of the
same name anywhere on `sys.path` win outright - path order does not save you,
because the finder keeps scanning past a namespace portion until it finds a
regular package. There is such a package in site-packages on at least one
machine, and the entire calibration test suite stopped importing the moment it
appeared, with nothing in this repository having changed.
"""
