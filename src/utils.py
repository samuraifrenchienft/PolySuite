import re


def is_valid_address(address: str, check_checksum: bool = False) -> bool:
    """Check if a string is a valid Ethereum address.
    If check_checksum=True, validates EIP-55 checksum when mixed case.
    Uses eth_utils if available; otherwise format-only validation."""
    if not address or not isinstance(address, str):
        return False
    if not re.match(r"^0x[a-fA-F0-9]{40}$", address):
        return False
    if check_checksum and address != address.lower() and address != address.upper():
        try:
            from eth_utils import to_checksum_address, is_address
            return is_address(address) and address == to_checksum_address(address)
        except ImportError:
            # eth_utils not installed; cannot validate checksum
            return True
    return True
