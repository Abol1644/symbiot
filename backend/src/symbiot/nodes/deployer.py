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
    writer({"agent": "deployer", "msg": "Deploy is disabled — Docker is not used."})
    return {
        "deploy_result": DeployResult(
            image="",
            tag="",
            smoke_test_passed=False,
            smoke_test_output="docker deployment has been removed from symbiot",
        ).model_dump(),
        "status": "passed",
    }
