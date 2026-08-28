"""Learn Clash Royale from recordings of people playing it.

The simulator is calibrated against itself. Every constant in it was either
decoded from the client's own tables - which is trustworthy - or chosen by
somebody, which is not. The chosen ones are where it diverges from the game,
and the divergence is not small: measured against a single recorded match, an
unblocked Hog Rider's seven tower hits reproduce exactly, while a body-blocked
one lands four in simulation against two in reality.

That gap is why every policy trained here spams. In a world where three
Skeletons cost a Hog 0.6 seconds instead of five tower hits, throwing cards at
every threat is correct play. The agent learned it correctly.

One recorded match produced that measurement. This package is the same idea at
scale: take footage of a strong player, find the parts that are actually
matches, track what happens in them, and compare against what the simulator
says should have happened. Where they disagree, the simulator is wrong, and now
there is a number attached to it.

The stages are deliberately separable, because they fail differently:

    fetch     one video at a time, at 888x1920/60 where offered
    segment   find the spans that are matches, discard menus and talking
    track     run the detector over those spans, emit unit tracks
    calibrate turn tracks into measurements the engine can be checked against

Disk is the binding constraint on this machine, so `pipeline.py` deletes each
video once its tracks are written. The tracks are two orders of magnitude
smaller than the video and are the only part with lasting value.
"""

from __future__ import annotations

__all__ = ["fetch", "segment", "track", "calibrate"]
