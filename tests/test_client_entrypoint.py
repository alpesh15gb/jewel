from __future__ import annotations

import run_client


def test_client_self_test_resolves_runtime_modules_without_starting_gui(monkeypatch):
    def fail_if_gui_started():
        raise AssertionError("--self-test must not start the Tk application")

    monkeypatch.setattr(run_client, "main", fail_if_gui_started)
    assert run_client.self_test() == 0
