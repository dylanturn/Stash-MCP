"""``stash-mcp-cli`` — admin tooling for tenant/store provisioning.

Intentionally narrow: this is for the "the IdP is broken and I need to
fix something" path, plus tenant/store provisioning automation. It is
*not* an alternative way to mint API tokens — those only come from
``/auth/tokens`` after an OIDC login.
"""

def main(argv: list[str] | None = None) -> int:
    """Lazy wrapper so ``python -m stash_mcp.cli`` doesn't double-import
    ``__main__`` when the entry-point script also imports the package."""
    from .__main__ import main as _main

    return _main(argv)


__all__ = ["main"]
