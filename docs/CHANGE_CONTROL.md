# Production change control

After Bijoria goes live, changes to billing, tax, stock status, accounting, backup/restore, authentication, TLS or Tally integration must be developed on a branch, covered by regression tests, pass the Windows release gate, and be installed through the supported in-place installer. Direct edits to the production database or installed binaries are not supported.
