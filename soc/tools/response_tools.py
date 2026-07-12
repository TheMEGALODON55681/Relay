"""Fixed set of safe, reversible response actions - the only actions the system can
take. Executed only for actions the policy engine has approved (auto_execute=True) or
an operator has approved manually. No handler accepts or runs an arbitrary command.
"""

from gateway.trusted_data_gateway import TrustedDataGateway
from schemas.models import ResponseAction


def _stop_trusting(gateway: TrustedDataGateway, action: ResponseAction) -> None:
    gateway.quarantine(action.target)


def _enable_estimation(gateway: TrustedDataGateway, action: ResponseAction) -> None:
    gateway.enable_estimation(action.target)


def _noop(gateway: TrustedDataGateway, action: ResponseAction) -> None:
    """INCREASE_MONITORING and RECALCULATE_DISPATCH are dashboard/caller-driven signals
    with no gateway state of their own; CREATE_OPERATOR_APPROVAL and CLOSE_INCIDENT are
    handled by the incident manager, not the gateway.
    """


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
    """Executes exactly one approved action against the gateway and marks it executed.
    Callers must only pass actions with auto_execute=True or explicit operator approval.
    """
    _HANDLERS[action.type](gateway, action)
    action.executed = True
