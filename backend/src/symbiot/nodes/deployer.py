from langgraph.config import get_stream_writer

from symbiot.schemas import DeployResult
from symbiot.state import LoopState


def _writer():
    try:
        return get_stream_writer()
    except RuntimeError:
        return lambda _data: None


def deployer(state: LoopState) -> dict:
    writer = _writer()
    writer({"agent": "deployer", "msg": "Deploy step is disabled — native execution mode."})
    return {
        "deploy_result": DeployResult(
            image="",
            tag="",
            smoke_test_passed=False,
            smoke_test_output="deployer is disabled in native execution mode",
        ).model_dump(),
        "status": "passed",
    }
