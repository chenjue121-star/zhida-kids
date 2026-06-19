import httpx
import respx

ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"


@respx.mock
def test_recognize_clothing_parses_ark_response(client, monkeypatch):
    monkeypatch.setattr("app.routers.clothing.settings.dev_ai_mock", False)
    monkeypatch.setattr("app.routers.clothing.settings.ark_api_key", "test-key")
    monkeypatch.setattr(
        "app.routers.clothing._ark_image_url_or_data_url",
        lambda photo_url: "https://example.com/a.jpg",
    )

    ark_payload = {
        "output_text": '{"type": "上衣", "main_color": "白色", "thickness": "薄"}'
    }
    route = respx.post(ARK_URL).mock(
        return_value=httpx.Response(200, json=ark_payload)
    )

    resp = client.post("/clothing/recognize", json={"photo_url": "https://example.com/a.jpg"})
    assert route.called
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "top"
    assert body["main_color"] == "white"
    assert body["thickness"] == "thin"


def test_recognize_clothing_mock_mode(client, monkeypatch):
    monkeypatch.setattr("app.routers.clothing.settings.dev_ai_mock", True)
    resp = client.post("/clothing/recognize", json={"photo_url": "x"})
    assert resp.status_code == 200
    assert resp.json()["type"] == "accessory"
