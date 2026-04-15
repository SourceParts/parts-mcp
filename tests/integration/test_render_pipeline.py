"""
End-to-end test for the Blender render pipeline.

Requires:
- Running API server (api.source.parts or localhost:9900)
- Running database proxy
- Running Blender worker (or mock)
- SOURCE_PARTS_API_KEY set

Run with: python -m pytest tests/integration/test_render_pipeline.py -v -s
"""
import os
import time

import pytest

from parts_mcp.utils.api_client import SourcePartsClient

YAGEO_SKU = "SP-YAGEO-471KD20TR"
POLL_TIMEOUT = 120  # seconds
POLL_INTERVAL = 3   # seconds


@pytest.fixture
def client():
    api_key = os.environ.get("SOURCE_PARTS_API_KEY")
    if not api_key:
        pytest.skip("SOURCE_PARTS_API_KEY not set")
    return SourcePartsClient(api_key=api_key)


@pytest.mark.integration
class TestRenderPipeline:

    def test_trigger_render(self, client):
        """Trigger a render for YAGEO 471KD20-TR and verify it queues."""
        result = client._make_request("POST", "/renders/trigger", json_data={
            "part_id": None,  # Will need real part_id
            "template": "varistor_disc.blend",
            "blender_params": {"diameter_mm": 20, "voltage_label": "470V"},
            "force": True,
        })
        assert result.get("success") is True
        assert result.get("render_status") == "queued"
        assert result.get("job_id") is not None
        return result["job_id"]

    def test_check_render_status_poll(self, client):
        """Poll check_render_status until complete or timeout."""
        # First trigger a render
        trigger = client._make_request("POST", "/renders/trigger", json_data={
            "part_id": None,
            "template": "varistor_disc.blend",
            "blender_params": {"diameter_mm": 20, "voltage_label": "470V"},
            "force": True,
        })
        job_id = trigger.get("job_id")
        if not job_id:
            pytest.skip("Could not create render job")

        # Poll until done
        start = time.time()
        while time.time() - start < POLL_TIMEOUT:
            status = client._make_request("GET", f"/renders/status/{job_id}")
            render_status = status.get("render_status")

            if render_status == "complete":
                assert status.get("render_url") is not None
                assert status["render_url"].endswith(".webp")
                return
            elif render_status == "failed":
                pytest.fail(f"Render failed: {status.get('error')}")

            time.sleep(POLL_INTERVAL)

        pytest.fail(f"Render did not complete within {POLL_TIMEOUT}s")

    def test_short_circuit_no_rerender(self, client):
        """Verify force=false returns existing render without creating a new job."""
        # Resolve the part first
        resolve = client._make_request("GET", "/renders/resolve", params={"sku": YAGEO_SKU})
        if not resolve.get("part_id"):
            pytest.skip(f"Part {YAGEO_SKU} not found in database")

        part_id = resolve["part_id"]

        # Only test if render already exists
        if resolve.get("render_status") != "complete":
            pytest.skip("No existing render to short-circuit against")

        result = client._make_request("POST", "/renders/trigger", json_data={
            "part_id": part_id,
            "template": "varistor_disc.blend",
            "blender_params": {},
            "force": False,
        })

        assert result.get("job_id") is None
        assert result.get("render_status") == "complete"
        assert result.get("render_url") is not None
        assert "already exists" in result.get("message", "").lower()
