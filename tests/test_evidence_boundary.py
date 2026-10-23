import json

from langgraph.checkpoint.sqlite import SqliteSaver

from triager.agent import TriageAgent
from triager.config import Settings
from triager.db import Database


def test_sensitive_evidence_and_model_echo_never_enter_new_checkpoints(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/test.db")
    db.initialize(seed=True)
    agent = TriageAgent(db, Settings(ai_provider="gemini"))
    agent.inspect = lambda _: [
        {
            "event_id": "event",
            "at": "2026-10-23T00:00:00+00:00",
            "log": "api_key=private-log-secret operator@example.com",
        }
    ]
    seen = []

    def model(state):
        seen.append(json.dumps(state))
        if state["rounds"] == 0:
            return {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "name": "get_service_metrics",
                            "args": {"password": "private-model-secret"},
                        }
                    }
                ],
            }
        return {
            "role": "model",
            "parts": [
                {
                    "text": json.dumps(
                        {
                            "severity": "unknown",
                            "category": "unknown",
                            "confidence": 0,
                            "abstained": True,
                            "missing_information": ["api_key=private-output-secret"],
                        }
                    )
                }
            ],
        }

    agent.model_turn = model
    result = agent.diagnose({"service": "execution-gateway"})
    serialized = json.dumps(result) + "".join(seen)
    with SqliteSaver.from_conn_string(agent.checkpoint_path) as saver:
        for checkpoint in saver.list(agent.run_config(result["run_id"])):
            serialized += json.dumps(checkpoint.checkpoint, default=str)
    for secret in [
        "private-log-secret",
        "operator@example.com",
        "private-model-secret",
        "private-output-secret",
    ]:
        assert secret not in serialized
    db.engine.dispose()
