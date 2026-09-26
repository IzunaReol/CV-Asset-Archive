from app.main import app


def test_upload_batch_routes_are_exposed_in_openapi():
    paths = app.openapi()["paths"]
    assert "post" in paths["/api/v1/assets/upload-sessions/batch"]
    assert "post" in paths["/api/v1/assets/upload-sessions/complete-batch"]
    assert "post" in paths["/api/v1/assets/upload-conflicts"]
    assert "get" in paths["/api/v1/datasets/options"]
