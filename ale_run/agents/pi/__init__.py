"""Pi coding-agent harness for ALE.

Drives the ``@earendil-works/pi-coding-agent`` CLI (``pi``) headlessly via
its JSON event stream mode (``pi --mode json``). Provider/model routing is
configured through pi's ``models.json`` custom-provider mechanism so any
OpenAI-compatible gateway (e.g. apihy) can be used without a fork.
"""
