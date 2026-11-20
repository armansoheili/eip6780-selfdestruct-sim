# eip6780-selfdestruct-sim

EIP-6780 `SELFDESTRUCT` semantics simulator in pure Python — no dependencies.

## The rule

Before Cancun, `SELFDESTRUCT` (opcode `0xFF`) always deleted the calling
contract: its balance went to a beneficiary and its code and storage were
wiped. EIP-6780 changed that. Since Cancun, a contract's code and storage
are only removed when the contract was **created in the same transaction**
as the `SELFDESTRUCT`. An older contract that self-destructs keeps its code
and storage — only its balance moves to the beneficiary.

| Scenario | Balance moves? | Code/storage removed? |
| --- | --- | --- |
| Pre-Cancun, any contract | Yes | Yes |
| Cancun, contract created in the same tx | Yes | Yes |
| Cancun, older contract | Yes | **No** |

## Usage

```python
from selfdestruct import State, selfdestruct, selfdestruct_gas

s = State()
funder = s.create_account(balance=100)
contract = s.create_contract(funder.address, code=b"CODE", value=40)

# Created and destroyed in the same transaction -> deleted (Cancun).
selfdestruct(s, contract.address, funder.address)
# {'transferred': 40, 'deleted': True, 'beneficiary': '0x...0001'}

# Once the transaction ends, the same contract survives self-destruct.
s.end_tx()
selfdestruct(s, contract.address, funder.address)
# {'transferred': 40, 'deleted': False, ...}  -- code intact, balance drained
```

Gas follows EIP-2929: 5000 base, +2600 for a cold beneficiary, +25000 when
the beneficiary is a new account receiving a non-zero balance:

```python
selfdestruct_gas(beneficiary_warm=False, beneficiary_exists=False, value=10)
# 32600
```

## Run it

```bash
python selfdestruct.py --demo   # the three headline scenarios
python selfdestruct.py --test   # doctests
```

## What's inside

- `selfdestruct.py` — `State` (accounts + per-transaction creation
  tracking), `selfdestruct` (pre-Cancun vs Cancun semantics),
  `selfdestruct_gas` (EIP-2929 cost), plus a `demo()` and doctests.
- `README.md` — this file.
