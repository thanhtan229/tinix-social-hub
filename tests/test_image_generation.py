from __future__ import annotations

import unittest

from app.services.ai import AIError
from app.services.image_generation import ImageGenerationService


class FakeGenerations:
    def __init__(self) -> None:
        self.started: list[tuple[str, str, str, dict, object, object]] = []

    def start(self, provider, model, operation, request, brief_id, brand_id):
        self.started.append((provider, model, operation, request, brief_id, brand_id))
        return "image-job"

    def update_image_job(self, *args, **kwargs):
        pass


class FakeMediaCreator:
    def __init__(self) -> None:
        self.create_run_options: dict = {}

    async def providers(self):
        return [{
            "id": "google-flow",
            "capabilities": {
                "outputTypes": ["image", "video"],
                "imageModels": ["Nano Banana 2", "Nano Banana Pro"],
            },
        }]

    async def create_run(self, **kwargs):
        self.create_run_options = kwargs
        return kwargs["run_id"]

    async def run_status(self, run_id):
        return {"terminal": True, "status": "failed", "results": []}


class ImageGenerationModelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.generations = FakeGenerations()
        self.media_creator = FakeMediaCreator()
        self.service = ImageGenerationService(
            self.generations, None, self.media_creator, timeout_seconds=1,
        )

    async def test_selected_model_is_saved_and_sent_to_media_creator(self) -> None:
        result = await self.service.create_job({
            "prompt": "A product photo", "provider": "google-flow", "model": "Nano Banana Pro",
        })
        self.assertEqual(result["model"], "Nano Banana Pro")
        await self.service._tasks[result["job_id"]]
        self.assertEqual(self.generations.started[0][1], "Nano Banana Pro")
        self.assertEqual(self.media_creator.create_run_options["model"], "Nano Banana Pro")

    async def test_unknown_model_is_rejected_before_a_job_is_created(self) -> None:
        with self.assertRaises(AIError) as error:
            await self.service.create_job({
                "prompt": "A product photo", "provider": "google-flow", "model": "Unknown model",
            })
        self.assertEqual(error.exception.code, "invalid_image_model")
        self.assertEqual(self.generations.started, [])

    async def test_auto_model_keeps_provider_default(self) -> None:
        result = await self.service.create_job({"prompt": "A product photo", "provider": "google-flow"})
        self.assertEqual(result["model"], "auto")
        await self.service._tasks[result["job_id"]]
        self.assertEqual(self.media_creator.create_run_options["model"], "")


if __name__ == "__main__":
    unittest.main()
