from fastapi.testclient import TestClient

from bot.app import create_app
from bot.brokers import PaperBroker
from conftest import SECRET


def client(settings, executor):
    app = create_app(settings, PaperBroker(commission_per_side=0))
    app.state.executor.risk = executor.risk  # use frozen clock
    return TestClient(app), app


def test_webhook_auth_and_flow(settings, executor):
    c, app = client(settings, executor)
    assert c.post("/webhook", json={"secret": "nope", "action": "long"}).status_code == 401
    assert c.post("/webhook", content=b"not json").status_code == 400
    r = c.post("/webhook", json={"secret": SECRET, "action": "long", "price": 20000})
    assert r.status_code == 200 and r.json()["status"] == "filled"


def test_admin_endpoints(settings, executor):
    c, app = client(settings, executor)
    c.post("/webhook", json={"secret": SECRET, "action": "long", "price": 20000})
    assert c.get("/status").status_code == 401
    assert c.get("/status", headers={"x-admin-token": "admin-tok"}).json()["position"] == 1
    assert c.post("/kill", headers={"x-admin-token": "admin-tok"}).json()["killed"]
    st = c.get("/status", headers={"x-admin-token": "admin-tok"}).json()
    assert st["position"] == 0 and st["killed"]
    r = c.post("/webhook", json={"secret": SECRET, "action": "long", "price": 20000})
    assert r.json()["status"] == "rejected"
    c.post("/resume", headers={"x-admin-token": "admin-tok"})
    r = c.post("/webhook", json={"secret": SECRET, "action": "long", "price": 20000})
    assert r.json()["status"] == "filled"
