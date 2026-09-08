"""The contract and the implementation must not drift.

`contracts/openapi.yaml` is hand-written and is the artefact four other lanes code against.
The generated spec is what the running service actually does. If those two disagree, someone's
client breaks on integration day - so the disagreement fails here instead, on every push.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "openapi.yaml"
API_PREFIX = "/api/v1"
#: Served for the load balancer, deliberately outside the versioned surface.
UNVERSIONED = {"/healthz", "/readyz", "/metrics"}


@pytest.fixture(scope="module")
def contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text())


def _implemented(client) -> dict[str, set[str]]:
    spec = client.get("/openapi.json").json()
    out: dict[str, set[str]] = {}
    for path, ops in spec["paths"].items():
        key = path[len(API_PREFIX) :] if path.startswith(API_PREFIX) else path
        out[key] = {m.lower() for m in ops if m.lower() != "parameters"}
    return out


def test_every_documented_operation_is_implemented(contract, client):
    impl = _implemented(client)
    missing = [
        f"{method.upper()} {path}"
        for path, ops in contract["paths"].items()
        for method in ops
        if method not in impl.get(path, set())
    ]
    assert not missing, f"documented but not implemented: {missing}"


def test_every_implemented_operation_is_documented(contract, client):
    documented = {p: set(ops) for p, ops in contract["paths"].items()}
    undocumented = [
        f"{method.upper()} {path}"
        for path, methods in _implemented(client).items()
        for method in methods
        if method not in documented.get(path, set())
    ]
    assert not undocumented, f"implemented but not in the contract: {undocumented}"


def test_contract_declares_the_202_invariant(contract):
    responses = contract["paths"]["/documents/{document_id}/complete"]["post"]["responses"]
    assert "202" in responses
    assert "200" not in responses, "a 200 here invites someone to parse inline"


def test_contract_has_no_offset_parameter_anywhere(contract):
    names = {
        p["name"]
        for ops in contract["paths"].values()
        for op in ops.values()
        for p in op.get("parameters", [])
        if isinstance(p, dict) and "name" in p
    }
    assert "offset" not in names
    assert "cursor" in names


def test_manager_only_paths_are_marked_in_the_contract(contract):
    for path, method in (("/reports/{report_id}/assign", "patch"), ("/queue/stats", "get")):
        op = contract["paths"][path][method]
        text = (op.get("description", "") + op.get("summary", "")).lower()
        assert "manager" in text, f"{method.upper()} {path} does not state its role"


def test_unversioned_ops_paths_are_documented_unprefixed(contract):
    assert set(contract["paths"]) >= UNVERSIONED
