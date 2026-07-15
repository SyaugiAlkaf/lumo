class ChainError(RuntimeError):
    pass


class ChainSubmittedUnconfirmed(ChainError):
    """A create_intent transaction was submitted to the network but its outcome
    is unknown (poll timed out, or a read/parse failed AFTER an on-chain
    success). The escrow MAY have been funded, so the caller must not release
    the claim — a retry would double-escrow — and must persist the tx hash for
    reconciliation."""

    def __init__(self, tx_hash: str | None, message: str = ""):
        super().__init__(message or f"create_intent submitted but unconfirmed (tx {tx_hash})")
        self.tx_hash = tx_hash
