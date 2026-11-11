"""Owner-provided vectors and production integration. No paid provider calls."""
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from gobot.device_contract import DeviceProfile, DeviceSkin
from gobot.device_store import DeviceStore

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'design/visual-language'


def test_imported_sources_match_manifest_and_do_not_claim_services():
    manifest = json.loads((PACK / 'import-manifest.json').read_text(encoding='utf-8'))
    assert (manifest['screen_count'], manifest['face_count'], manifest['icon_count'], manifest['layout_count']) == (192, 72, 109, 34)
    assert manifest['demo_data_is_not_capability'] and not manifest['figma_import_verified']
    for record in manifest['files']:
        assert hashlib.sha256((PACK / record['path']).read_bytes()).hexdigest() == record['sha256']
    for p in PACK.rglob('*.svg'):
        for element in ET.fromstring(p.read_bytes()).iter():
            assert element.tag.split('}')[-1] not in {'script', 'foreignObject', 'image'}
            assert not any(k.lower().startswith('on') or 'href' in k.lower() for k in element.attrib)


def test_profile_migration_preserves_existing_settings_and_safe_expression():
    original = DeviceProfile().model_dump()
    original['display']['safe_inset'] = 35
    original['skin']['face_color'] = '#123456'
    original['skin'].pop('expression')
    restored = DeviceProfile.model_validate(original)
    assert restored.skin.expression == 'auto'
    assert restored.display.safe_inset == 35 and restored.skin.face_color == '#123456'
    assert restored.voice.engine == 'legacy'  # visual settings do not change voice routing
    for expression in ['love', 'sparkle', 'happy', 'uncertain']:
        assert DeviceSkin(expression=expression).expression == expression
    with pytest.raises(ValueError):
        DeviceSkin(expression='identity_confirmed')


def test_expression_persistence_is_atomic_and_does_not_change_another_device(tmp_path):
    store = DeviceStore(tmp_path / 'devices')
    owner = store.update('owner-phone', {'skin': {'expression': 'love', 'skin_id': 'soft'}})
    other = store.update('other-phone', {'skin': {'expression': 'sparkle', 'skin_id': 'minimal'}})
    with pytest.raises(ValueError):
        store.update('owner-phone', {'skin': {'expression': 'identity_confirmed', 'skin_id': 'classic'}})
    fresh = DeviceStore(tmp_path / 'devices')
    assert fresh.profile('owner-phone').skin == owner.skin
    assert fresh.profile('other-phone').skin == other.skin
    assert fresh.profile('owner-phone').client_id != other.client_id
    assert fresh.profile('owner-phone').voice == owner.voice


def test_assets_obey_existing_https_perimeter_and_csp(settings):
    from fastapi.testclient import TestClient
    from gobot.browser import ORIGIN, create_browser_app
    app = create_browser_app(settings)
    with TestClient(app, base_url=ORIGIN, client=('100.120.201.115', 200)) as client:
        for asset, mime in [('visual-atlas.html', 'text/html'), ('visual-atlas.css', 'text/css'), ('design.css', 'text/css'),
                            ('design-data.js', 'text/javascript'), ('design-reference.js', 'text/javascript'),
                            ('design-primitives.js', 'text/javascript'), ('noto-sans.ttf', 'font/ttf')]:
            response = client.get('/' + asset)
            assert response.status_code == 200 and response.headers['content-type'].startswith(mime)
            assert "script-src 'self'" in response.headers['content-security-policy']
            assert "img-src 'self' blob:" in response.headers['content-security-policy']
            assert 'unsafe-inline' not in response.headers['content-security-policy']
        assert client.get('/design-data.json').status_code == 404  # no arbitrary source file server
        assert client.post('/api/device/profile', json={'skin': {'expression': 'love'}}).status_code == 403
    with TestClient(app, base_url=ORIGIN, client=('203.0.113.2', 200)) as outsider:
        assert outsider.get('/design-data.js').status_code == 403


def test_production_pages_use_shared_vectors_and_local_font_before_renderers():
    for page in ['browser.html', 'device.html']:
        html = (ROOT / 'services/phone/dist' / page).read_text(encoding='utf-8')
        assert html.index('/design-data.js') < html.index('/design-primitives.js') < html.index('/visual.js')
        assert html.index('/design-primitives.js') < html.index('/device-renderer.js')
        assert '/design.css' in html
    for record in json.loads((PACK / 'font-source.json').read_text()):
        assert hashlib.sha256((ROOT / record['file']).read_bytes()).hexdigest() == record['sha256']


def test_read_only_reference_has_no_audio_or_provider_actions():
    script = (ROOT / 'services/phone/dist/visual-atlas.js').read_text(encoding='utf-8')
    for forbidden in ['fetch(', 'getUserMedia', 'RTCPeerConnection', 'WebSocket(', 'innerHTML', 'eval(']:
        assert forbidden not in script
    html = (ROOT / 'services/phone/dist/visual-atlas.html').read_text(encoding='utf-8')
    assert '<style>' not in html and 'style=' not in html
    assert 'URL.revokeObjectURL' in script


def test_production_reference_search_sections_faces_icons_and_blob_cleanup():
    result = subprocess.run(['node', 'tests/visual_atlas.cjs'], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_offline_real_canvas_vectors_and_widget_lifecycle():
    tool = ROOT / 'tools/visual-qa/node_modules/@napi-rs/canvas'
    if not tool.exists():
        pytest.skip('Install pinned optional offline QA dependency: npm ci --prefix tools/visual-qa')
    result = subprocess.run(['node', 'tools/visual-qa/render.cjs'], cwd=ROOT, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['face_variants'] == 72 and report['vector_icons'] == 109
    assert report['expired_timer_latch'] and report['scope_clear']
    assert not report['physical_iphone'] and report['paid_api_calls'] == 0
