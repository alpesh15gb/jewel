# Three-PC counter UAT

Use one serialized test tag that is in stock.

1. Sign in on Counter 1 and Counter 2 with different named users.
2. Scan the same tag on both counters.
3. Submit both sales as close together as possible.
4. Exactly one sale must post. The other counter must receive a controlled conflict and must not create another invoice, stock movement or journal.
5. Verify the winning tag is `sold`, the invoice exists once, and Data Health remains green.
6. Return the test item through the supported credit-note workflow and confirm it becomes available exactly once according to the return disposition.
7. Repeat after a main-PC reboot and again after briefly disconnecting/reconnecting one counter's LAN connection.

Any duplicate invoice, duplicate stock movement, silent retry or inconsistent status blocks go-live.
