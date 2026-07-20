class StonksError(Exception):
    """Base application error."""


class ProfileError(StonksError):
    """A profile is missing or invalid."""


class KeyFileError(StonksError):
    """A profile key cannot be used safely."""


class EncryptedStorageError(StonksError):
    """Encrypted storage cannot be authenticated or decoded."""


class LedgerError(StonksError):
    """A ledger invariant was violated."""


class ProviderError(StonksError):
    """A read-only provider failed."""


class ExecutionDeniedError(StonksError):
    """An execution capability was requested."""
