"""API and frontend smoke tests for task service."""

from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from task_service.main import create_app


class APITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        db = Path(self.temp.name) / "tasks.json"
        app = create_app(storage_path=db)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_root_serves_frontend(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("<title>Task Service</title>", response.text)

    def test_task_lifecycle(self) -> None:
        create_response = self.client.post(
            "/api/tasks",
            json={"title": "Build feature", "priority": "high"},
        )
        self.assertEqual(create_response.status_code, 200)
        task = create_response.json()
        self.assertEqual(task["title"], "Build feature")
        self.assertFalse(task["completed"])

        list_response = self.client.get("/api/tasks")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)

        patched = self.client.patch(f"/api/tasks/{task['id']}", json={"completed": True})
        self.assertEqual(patched.status_code, 200)
        self.assertTrue(patched.json()["completed"])

        report = self.client.get("/api/report").json()
        self.assertEqual(report["total"], 1)
        self.assertEqual(report["completed"], 1)

    def test_duplicate_title_rejected(self) -> None:
        self.client.post("/api/tasks", json={"title": "Same task", "priority": "low"})
        duplicate = self.client.post("/api/tasks", json={"title": "Same task", "priority": "medium"})
        self.assertEqual(duplicate.status_code, 400)


if __name__ == "__main__":
    unittest.main()
