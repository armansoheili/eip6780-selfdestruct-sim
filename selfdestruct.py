"""EIP-6780 SELFDESTRUCT simulator in pure Python.

Before Cancun, ``SELFDESTRUCT`` (opcode 0xFF) always deleted the calling
contract: its balance went to a beneficiary and its code and storage were
wiped. EIP-6780 changed that: since Cancun, a contract's code and storage
are only removed when the contract was created in the *same* transaction
as the ``SELFDESTRUCT``. An older contract that self-destructs keeps its
code and storage -- only its balance moves to the beneficiary.

This module models that rule exactly:

* :class:`State` -- a tiny world state of accounts plus per-transaction
  creation tracking (``end_tx`` clears the "created in this tx" flags).
* :func:`selfdestruct` -- execute ``SELFDESTRUCT`` with pre-Cancun or
  Cancun (EIP-6780) semantics; returns what was transferred and whether
  the account was deleted.
* :func:`selfdestruct_gas` -- the EIP-2929 gas cost: 5000 base, +2600 for
  a cold beneficiary, +25000 when the beneficiary is a new account
  receiving a non-zero balance.

Run ``python selfdestruct.py --demo`` for the three headline scenarios,
or ``python selfdestruct.py --test`` to run the doctests.
"""

from __future__ import annotations

import argparse
import doctest

GAS_SELFDESTRUCT = 5000
GAS_COLD_ACCOUNT_ACCESS = 2600
GAS_NEW_ACCOUNT = 25000


def addr(n):
    """Return a 20-byte hex address for small integer ``n``.

    >>> addr(1)
    '0x0000000000000000000000000000000000000001'
    >>> addr(255)
    '0x00000000000000000000000000000000000000ff'
    """
    return "0x" + f"{n:040x}"


class Account:
    """A minimal account: balance, code, storage and creation flag."""

    def __init__(self, address, balance=0, code=b"", storage=None, nonce=0,
                 created_in_tx=False):
        self.address = address
        self.balance = balance
        self.code = bytes(code)
        self.storage = dict(storage or {})
        self.nonce = nonce
        self.created_in_tx = created_in_tx

    def __repr__(self):
        return (f"Account({self.address!r}, balance={self.balance}, "
                f"code={self.code!r}, nonce={self.nonce})")


class State:
    """A tiny world state: accounts plus per-transaction creation tracking."""

    def __init__(self):
        self.accounts = {}
        self._next_address = 1

    def create_account(self, balance=0, code=b"", storage=None):
        """Create a plain (externally owned style) account.

        >>> s = State()
        >>> a = s.create_account(balance=5)
        >>> a.balance
        5
        >>> a.address
        '0x0000000000000000000000000000000000000001'
        """
        address = addr(self._next_address)
        self._next_address += 1
        acct = Account(address, balance=balance, code=code, storage=storage)
        self.accounts[address] = acct
        return acct

    def create_contract(self, creator, code=b"", value=0, storage=None):
        """Deploy a contract funded with ``value`` taken from ``creator``.

        The new contract is marked as created in the current transaction --
        exactly what EIP-6780 keys its deletion rule on.

        >>> s = State()
        >>> funder = s.create_account(balance=100)
        >>> c = s.create_contract(funder.address, code=b"CODE", value=40)
        >>> funder.balance
        60
        >>> c.balance
        40
        >>> c.created_in_tx
        True
        >>> c.nonce
        1
        """
        creator_acct = self.accounts[creator]
        if creator_acct.balance < value:
            raise ValueError("insufficient balance to fund contract creation")
        creator_acct.balance -= value
        acct = self.create_account(balance=value, code=code, storage=storage)
        acct.created_in_tx = True
        acct.nonce = 1
        return acct

    def end_tx(self):
        """End the current transaction: creation flags stop applying."""
        for acct in self.accounts.values():
            acct.created_in_tx = False


def selfdestruct_gas(beneficiary_warm=False, beneficiary_exists=True, value=0):
    """Gas cost of SELFDESTRUCT (EIP-2929 warm/cold + new-account rules).

    >>> selfdestruct_gas(beneficiary_warm=True, beneficiary_exists=True, value=10)
    5000
    >>> selfdestruct_gas(beneficiary_warm=False, beneficiary_exists=True, value=10)
    7600
    >>> selfdestruct_gas(beneficiary_warm=False, beneficiary_exists=False, value=10)
    32600
    >>> selfdestruct_gas(beneficiary_warm=False, beneficiary_exists=False, value=0)
    7600
    """
    gas = GAS_SELFDESTRUCT
    if not beneficiary_warm:
        gas += GAS_COLD_ACCOUNT_ACCESS
    if not beneficiary_exists and value > 0:
        gas += GAS_NEW_ACCOUNT
    return gas


def selfdestruct(state, caller, beneficiary, *, cancun=True):
    """Execute SELFDESTRUCT from ``caller``, sending its balance to ``beneficiary``.

    Returns ``{"transferred": ..., "deleted": ..., "beneficiary": ...}``.
    ``deleted`` is True only when the account's code and storage were
    removed. Cancun (EIP-6780) semantics delete only contracts created in
    the same transaction; pre-Cancun semantics always delete.

    An old contract self-destructing after Cancun keeps its code:

    >>> s = State()
    >>> old = s.create_account(balance=7, code=b"CODE")
    >>> heir = s.create_account()
    >>> selfdestruct(s, old.address, heir.address)
    {'transferred': 7, 'deleted': False, 'beneficiary': '0x0000000000000000000000000000000000000002'}
    >>> heir.balance
    7
    >>> old.code
    b'CODE'

    The same contract before Cancun is fully removed:

    >>> s = State()
    >>> old = s.create_account(balance=3, code=b"CODE")
    >>> heir = s.create_account()
    >>> selfdestruct(s, old.address, heir.address, cancun=False)
    {'transferred': 3, 'deleted': True, 'beneficiary': '0x0000000000000000000000000000000000000002'}
    >>> old.address in s.accounts
    False

    A contract created and destroyed in the same transaction *is* deleted,
    even after Cancun:

    >>> s = State()
    >>> funder = s.create_account(balance=100)
    >>> c = s.create_contract(funder.address, code=b"CODE", value=40)
    >>> selfdestruct(s, c.address, funder.address)
    {'transferred': 40, 'deleted': True, 'beneficiary': '0x0000000000000000000000000000000000000001'}
    >>> funder.balance
    100

    ...but once the transaction ends, the same contract survives:

    >>> s = State()
    >>> funder = s.create_account(balance=100)
    >>> c = s.create_contract(funder.address, code=b"CODE", value=40)
    >>> s.end_tx()
    >>> selfdestruct(s, c.address, funder.address)
    {'transferred': 40, 'deleted': False, 'beneficiary': '0x0000000000000000000000000000000000000001'}
    >>> c.address in s.accounts
    True
    >>> s.accounts[c.address].code
    b'CODE'
    """
    caller_acct = state.accounts.get(caller)
    if caller_acct is None:
        raise ValueError(f"unknown caller account {caller}")
    ben = state.accounts.get(beneficiary)
    if ben is None:
        ben = Account(beneficiary)
        state.accounts[beneficiary] = ben
    value = caller_acct.balance
    ben.balance += value
    caller_acct.balance = 0
    deleted = False
    if cancun:
        if caller_acct.created_in_tx:
            del state.accounts[caller]
            deleted = True
    else:
        del state.accounts[caller]
        deleted = True
    return {"transferred": value, "deleted": deleted, "beneficiary": beneficiary}


def demo():
    """Run the three headline scenarios and print what happens."""
    print("EIP-6780 SELFDESTRUCT demo")
    print("=" * 40)

    # 1. Pre-Cancun: an old contract is fully deleted.
    s = State()
    old = s.create_account(balance=3, code=b"CODE")
    heir = s.create_account()
    print("\n1. Pre-Cancun, old contract self-destructs:")
    print("  ", selfdestruct(s, old.address, heir.address, cancun=False))
    print("   contract still in state:", old.address in s.accounts)

    # 2. Cancun: an old contract keeps its code, only the balance moves.
    s = State()
    old = s.create_account(balance=7, code=b"CODE", storage={"slot0": 42})
    heir = s.create_account()
    print("\n2. Cancun, old contract self-destructs:")
    print("  ", selfdestruct(s, old.address, heir.address, cancun=True))
    print("   contract still in state:", old.address in s.accounts)
    print("   code intact:", s.accounts[old.address].code)
    print("   storage intact:", s.accounts[old.address].storage)

    # 3. Cancun: created and destroyed in the same tx -> deleted.
    s = State()
    funder = s.create_account(balance=100)
    c = s.create_contract(funder.address, code=b"CODE", value=40)
    print("\n3. Cancun, contract created and destroyed in the same tx:")
    print("  ", selfdestruct(s, c.address, funder.address, cancun=True))
    print("   contract still in state:", c.address in s.accounts)
    print("   funder balance back to:", funder.balance)

    print("\nGas examples:")
    print("  warm existing beneficiary:",
          selfdestruct_gas(beneficiary_warm=True, value=10))
    print("  cold existing beneficiary:",
          selfdestruct_gas(beneficiary_warm=False, value=10))
    print("  cold new beneficiary, non-zero value:",
          selfdestruct_gas(beneficiary_warm=False, beneficiary_exists=False,
                            value=10))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true", help="run the demo")
    parser.add_argument("--test", action="store_true", help="run the doctests")
    args = parser.parse_args()
    if args.test:
        failures, total = doctest.testmod(verbose=False)
        print(f"{total - failures}/{total} doctests passed")
        raise SystemExit(1 if failures else 0)
    demo()


if __name__ == "__main__":
    main()
