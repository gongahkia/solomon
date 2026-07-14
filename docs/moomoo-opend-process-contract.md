# Moomoo OpenD process contract

The operator starts and logs in to a local OpenD gateway. The vNext CLI may only connect to the configured local endpoint for read-only operations. It does not start OpenD, handle login secrets, unlock trading, or call order-submission APIs.

OpenD’s documented `unlock_trade` interface mutates process-wide lock state and needs a password to unlock. Until Moomoo documents a non-mutating state-read interface, vNext reports the unlock state as unknown rather than probing it.
