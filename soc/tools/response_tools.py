"""Fixed set of safe, reversible response actions - the only actions the system can
take. Executed only for actions the policy engine has approved (auto_execute=True) or
an operator has approved manually. No handler accepts or runs an arbitrary command.
"""

from gateway.trusted_data_gateway import TrustedDataGateway
from schemas.models import ResponseAction


def _stop_trusting(gateway: TrustedDataGateway, action: ResponseAction) -> bool:
    gateway.quarantine(action.target)
    return True


def _enable_estimation(gateway: TrustedDataGateway, action: ResponseAction) -> bool:
    """Succeeds only if the sensor was actually reconstructable. A failed attempt
    leaves the sensor QUARANTINED and the action unexecuted, so the incident record
    reflects what really happened instead of a rubber-stamped success.
    """
    return gateway.enable_estimation(action.target).success


def _noop(gateway: TrustedDataGateway, action: ResponseAction) -> bool:
    """INCREASE_MONITORING and RECALCULATE_DISPATCH are dashboard/caller-driven signals
    with no gateway state of their own; CREATE_OPERATOR_APPROVAL and CLOSE_INCIDENT are
    handled by the incident manager, not the gateway.
    """
    return True


_HANDLERS = {
    "QUARANTINE_SENSOR": _stop_trusting,
    "MARK_DATA_UNTRUSTED": _stop_trusting,
    "FREEZE_OPTIMIZATION_INPUT": _stop_trusting,
    "ISOLATE_SUBSTATION": _stop_trusting,
    "ENABLE_ESTIMATION_FALLBACK": _enable_estimation,
    "INCREASE_MONITORING": _noop,
    "RECALCULATE_DISPATCH": _noop,
    "CREATE_OPERATOR_APPROVAL": _noop,
    "CLOSE_INCIDENT": _noop,
}


def execute(gateway: TrustedDataGateway, action: ResponseAction) -> None:
    """Executes exactly one approved action against the gateway and sets executed to
    whatever the handler actually accomplished. Callers must only pass actions with
    auto_execute=True or explicit operator approval.
    """
    action.executed = _HANDLERS[action.type](gateway, action)


_PRIORITY = {_stop_trusting: 0, _enable_estimation: 1, _noop: 2}


def execute_all(gateway: TrustedDataGateway, actions: list[ResponseAction]) -> None:
    """Executes every auto-approved action for an incident, quarantine-type actions
    before ENABLE_ESTIMATION_FALLBACK - so a sensor's own quarantine always lands
    before an estimation attempt on it, no matter what order the response agent (an
    LLM, whose output ordering is not guaranteed) or a correlated re-proposal (built
    from a set, see soc/orchestrator.py) happened to list them in. Without this, an
    out-of-order ENABLE_ESTIMATION_FALLBACK would no-op against a still-TRUSTED sensor
    and get marked executed, leaving nothing to retry estimation once the quarantine
    that follows it actually lands.
    """
    for action in sorted(actions, key=lambda a: _PRIORITY[_HANDLERS[a.type]]):
        if action.auto_execute and not action.executed:
            execute(gateway, action)
