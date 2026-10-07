import json

import pytest
from conftest import managed_request


@pytest.mark.parametrize("original", [
    '{"theme":"dark",}',
    '{"theme":"dark" // retain comment\n}',
    '{"theme":"dark", "mcp":{"other":{"type":"remote","url":"https://example.test/,}"},}}',
])
def test_registration_preserves_valid_jsonc_and_unrelated_values(load_source, tmp_path, original):
    adapter = load_source.opencode
    config = tmp_path / "opencode.jsonc"
    config.write_text(original)
    layout = load_source.ManagedLayout.from_request(managed_request(tmp_path))
    before = json.loads(adapter._strip_jsonc(original))
    rendered = adapter.render_config(config, layout)
    actual = json.loads(adapter._strip_jsonc(rendered.decode()))
    assert actual["theme"] == before["theme"]
    if "other" in before.get("mcp", {}):
        assert actual["mcp"]["other"] == before["mcp"]["other"]
        assert actual["mcp"]["other"]["url"] == "https://example.test/,}"
    assert actual["mcp"]["lingxi-advisor"] == adapter._desired(layout)
    assert actual["mcp"]["lingxi-advisor-operator"] == adapter._operator_desired(layout)
    if "// retain comment" in original:
        assert "// retain comment" in rendered.decode()
    config.write_bytes(rendered)
    assert adapter.render_config(config, layout) == rendered


def test_jsonc_stripping_never_changes_string_literals(load_source):
    text = '{"url":"https://example.test/,}","value":"comma,] // /* literal */",}'
    assert json.loads(load_source.opencode._strip_jsonc(text)) == {
        "url": "https://example.test/,}", "value": "comma,] // /* literal */",
    }


@pytest.mark.parametrize("text", ['{"theme":"dark",,}', '{"mcp":1}', '{"theme":"a","theme":"b"}', '{"value":1/* comment */2}'])
def test_invalid_or_ambiguous_config_rejected_before_write(load_source, tmp_path, text):
    path = tmp_path / "opencode.jsonc"
    path.write_text(text)
    with pytest.raises((ValueError, load_source.InstallError)):
        load_source.opencode.render_config(path, load_source.ManagedLayout.from_request(managed_request(tmp_path)))
    assert path.read_text() == text
