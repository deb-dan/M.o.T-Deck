"""A canceled grace callback cannot reap a newer detached session."""
from types import SimpleNamespace

from bridge import pty_aider


def test_old_timer_firing_after_reattach_preserves_the_new_grace_window(monkeypatch):
    timers = []

    class Timer:
        def __init__(self, interval, callback):
            self.callback = callback
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            pass  # A callback already entering the lock cannot be canceled.

    monkeypatch.setattr(pty_aider.threading, 'Timer', Timer)
    session = pty_aider.PtySession([], '.', {})
    session.proc = SimpleNamespace(poll=lambda: None)
    closed = []
    session.close = lambda: closed.append(True)
    first, second = lambda data: None, lambda data: None
    session.attach(first)
    session.detach(first, grace=600)
    session.attach(second)
    session.detach(second, grace=600)
    assert len(timers) == 2
    timers[0].callback()
    assert not closed, 'a superseded timer ended the new grace window early'
    assert session.grace_left() > 590
    timers[1].callback()
    assert closed == [True]
