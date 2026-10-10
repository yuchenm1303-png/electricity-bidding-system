"""Independent physics regressions on entirely synthetic, public test grids."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from powerbid.joint_solution_integrity import JointPhysicsError, audit_joint_schedule
from powerbid.network_dispatch import network_from_dict
from powerbid.network_integrity import DcPhysicsError, audit_dc_solution
from powerbid.unit_commitment import ThermalConstraints


def _grid():
    return {
        "buses": ["A", "B", "C"],
        "lines": [
            {"lineId": "AB", "fromBus": "A", "toBus": "B",
             "reactancePu": 0.1, "limitMw": 50},
            {"lineId": "BC", "fromBus": "B", "toBus": "C",
             "reactancePu": 0.1, "limitMw": 50},
            {"lineId": "AC", "fromBus": "A", "toBus": "C",
             "reactancePu": 0.2, "limitMw": 50},
        ],
        "unitBus": {"G1": "A"},
        "hourlyDemandMw": {
            "A": [0] * 24, "B": [0] * 24, "C": [20] * 24,
        },
        "slackBus": "A",
        "baseMva": 100,
        "topologySource": "synthetic 3-node cycle",
        "demandSource": "synthetic 24h demand",
    }


def test_dc_valid_cycle_has_zero_kcl_and_kvl_error():
    net = network_from_dict(_grid())
    # AC path impedance 0.2; A-B-C path impedance 0.2.
    report = audit_dc_solution(
        net, {"G1": 20}, {"AB": 10, "BC": 10, "AC": 10}, 1
    )
    assert report.max_balance_error_mw == pytest.approx(0)
    assert report.max_flow_equation_error_mw == pytest.approx(0)


def test_dc_circulating_flow_caught_even_when_kcl_and_ratings_pass():
    net = network_from_dict(_grid())
    # 5 MW around the loop changes no nodal injection, but violates KVL.
    with pytest.raises(DcPhysicsError, match="loop consistency"):
        audit_dc_solution(net, {"G1": 20}, {"AB": 15, "BC": 15, "AC": 5}, 1)


def test_dc_independent_limits_balance_and_ids():
    net = network_from_dict(_grid())
    with pytest.raises(DcPhysicsError, match="thermal"):
        audit_dc_solution(net, {"G1": 20}, {"AB": 60, "BC": 60, "AC": -40}, 1)
    with pytest.raises(DcPhysicsError, match="power balance"):
        audit_dc_solution(net, {"G1": 20}, {"AB": 11, "BC": 10, "AC": 10}, 1)
    with pytest.raises(DcPhysicsError, match="Line IDs"):
        audit_dc_solution(net, {"G1": 20}, {"AB": 10, "BC": 10}, 1)


@pytest.mark.parametrize("field,bad", [
    ("reactancePu", "0.1"),
    ("reactancePu", True),
    ("limitMw", "50"),
    ("limitMw", float("nan")),
])
def test_dc_canonical_import_rejects_untyped_or_nonfinite_physical_fields(field, bad):
    raw = _grid()
    raw["lines"][0][field] = bad
    with pytest.raises(ValueError, match=field):
        network_from_dict(raw)


def test_dc_canonical_import_rejects_boolean_hourly_mw():
    raw = _grid()
    raw["hourlyDemandMw"]["B"][0] = False
    with pytest.raises(ValueError, match="hourlyDemandMw"):
        network_from_dict(raw)


def _unit():
    return ThermalConstraints(
        unit_id="G1", min_mw=0, max_mw=30,
        ramp_up_mw=5, ramp_down_mw=5,
        startup_ramp_mw=10, shutdown_ramp_mw=10,
        min_up_hours=2, min_down_hours=2,
        startup_cost=0, shutdown_cost=0,
        initial_on=True, initial_mw=0, initial_state_hours=4,
    )


def _hour(mw=0.0, on=True, started=False, stopped=False):
    return SimpleNamespace(
        accepted_by_unit={"G1": mw},
        unit_online={"G1": on},
        unit_started={"G1": started},
        unit_stopped={"G1": stopped},
    )


def test_joint_zero_minimum_online_zero_dispatch_is_a_valid_status():
    audit_joint_schedule({"G1": _unit()}, [_hour()] * 24, terminal_mode="complete")


def test_joint_independent_audit_rejects_interhour_ramp_errors():
    hours = [_hour()] * 24
    hours[1] = _hour(mw=20)
    with pytest.raises(JointPhysicsError, match="upward ramp"):
        audit_joint_schedule({"G1": _unit()}, hours, terminal_mode="complete")


def test_joint_independent_audit_rejects_false_start_stop_status():
    spec = replace(_unit(), initial_on=False, initial_state_hours=5)
    with pytest.raises(JointPhysicsError, match="transition"):
        audit_joint_schedule({"G1": spec}, [_hour()] * 24, terminal_mode="carryover")
