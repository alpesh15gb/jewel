# Transaction idempotency

Counter requests that can create financial/stock records use stable request identifiers where applicable so a retry after a network interruption cannot silently post the same logical transaction twice. The final UAT includes a disconnect/reconnect case specifically to verify this behavior in the packaged Windows client/server setup.
