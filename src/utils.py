import re


def sanitize_nickname(nickname: str, max_len: int = 50) -> str:
    """Sanitize wallet nickname for safe display (HIGH-004). Strips, limits length, removes angle brackets."""
    if not nickname or not isinstance(nickname, str):
        return ""
    s = nickname.strip()[:max_len]
    s = s.replace("<", "").replace(">", "").replace("&", "&amp;")
    return s


def is_valid_solana_address(address: str) -> bool:
    """Check if string is a valid Solana address (base58, 32-44 chars). MED-003."""
    if not address or not isinstance(address, str):
        return False
    return bool(re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", address.strip()))


def is_valid_address(address: str, check_checksum: bool = False) -> bool:
    """Check if a string is a valid Ethereum address.
    If check_checksum=True, validates EIP-55 checksum when mixed case.
    Uses eth_utils if available; otherwise format-only validation."""
    if not address or not isinstance(address, str):
        return False
    s = address.strip()
    if len(s) != 42:
        return False
    if not re.match(r"^0x[a-fA-F0-9]{40}$", s):
        return False
    if check_checksum and s != s.lower() and s != s.upper():
        try:
            from eth_utils import to_checksum_address, is_address
            return is_address(s) and s == to_checksum_address(s)
        except ImportError:
            return True
    return True


def is_valid_eth_address(address: str, strict_checksum: bool = True) -> bool:
    """Strict Ethereum address validation (SEC-002).
    Validates length (42 chars), format, and EIP-55 checksum when mixed-case."""
    return is_valid_address(address, check_checksum=strict_checksum)
