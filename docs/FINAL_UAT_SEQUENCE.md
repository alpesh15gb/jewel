# Final UAT sequence

Run tests in this order so failures are isolated: install/upgrade -> server fingerprint/TLS -> login/password change/roles -> business state/timezone -> rates/opening test stock -> scanner/label -> sale -> concurrent same-tag sale -> partial return/credit note -> purchase/credit/old gold -> day-close/Data Health -> Tally test/sync/reconcile -> verified backup -> restore drill -> main-PC reboot -> counter reconnect. Do not enter live opening stock until this sequence passes.
