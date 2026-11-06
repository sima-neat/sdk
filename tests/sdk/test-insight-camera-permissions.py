#!/usr/bin/env python3
import importlib.util
import base64
import hashlib
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('camera_patch', ROOT / 'tools/patch_insight_camera_permissions.py')
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


class CameraPolicyTest(unittest.TestCase):
    def test_outer_policy_is_scoped_to_palette(self):
        source = '_createElement(e,t){let i=document.createElement("iframe");let n=["autoplay"];i.setAttribute("allow",n.join("; "));return i}'
        updated = patch.patch_workbench(source)
        self.assertEqual(updated, patch.patch_workbench(updated))
        script = '''
const assert = require('node:assert/strict');
const document = {createElement: () => ({setAttribute(key, value) { this[key] = value; }})};
const view = {METHOD};
// _createElement receives options and contentOptions, not extension metadata.
view.extension = {id:{value:'sima-neat.sima-neat'}};
assert.equal(view._createElement({}, {}).allow, 'autoplay; camera *');
assert.equal(view._createElement({}, {enableScripts:true}).allow, 'autoplay; camera *');
view.extension = {id:{value:'other.extension'}};
assert.equal(view._createElement({}, {id:{value:'sima-neat.sima-neat'}}).allow, 'autoplay');
view.extension = undefined;
assert.equal(view._createElement({}, {}).allow, 'autoplay');
assert.equal(view._createElement({}, undefined).allow, 'autoplay');
view.extension = {};
assert.equal(view._createElement({}, {}).allow, 'autoplay');
'''.replace('METHOD', updated)
        subprocess.run(['node', '-e', script], check=True)

    def test_existing_guard_is_upgraded(self):
        source = ('_createElement(e,t){let i=document.createElement("iframe");'
                  'let n=["autoplay"];/* palette-insight-camera-outer */'
                  't?.id.value==="sima-neat.sima-neat"&&n.push("camera *"),'
                  'i.setAttribute("allow",n.join("; "));return i}')
        updated = patch.patch_workbench(source)
        self.assertNotIn('t?.id.value', updated)
        self.assertIn('this.extension?.id?.value', updated)
        self.assertEqual(updated, patch.patch_workbench(updated))
        self.assertEqual(updated.count('camera *'), 1)

    def test_unknown_existing_guard_fails_closed(self):
        with self.assertRaises(ValueError):
            patch.patch_workbench('/* palette-insight-camera-outer */unknown')

    def test_inner_policy_is_scoped_to_palette(self):
        source = "const searchParams = new URLSearchParams(query); const allowRules = ['autoplay;']; newFrame.setAttribute('allow', allowRules.join(' '));"
        page = '<meta content="script-src sha256-old"><script async type="module">' + source + '</script>'
        page = patch.patch_preload(page)
        self.assertEqual(page, patch.patch_preload(page))
        self.assertNotIn('sha256-old', page)
        updated = page.split('<script async type="module">')[1].split('</script>')[0]
        digest = base64.b64encode(hashlib.sha256(updated.encode()).digest()).decode()
        self.assertIn('sha256-' + digest, page)
        script = '''
const assert = require('node:assert/strict');
function policy(query) {
 const newFrame = {setAttribute(key, value) {this[key] = value;}};
 SOURCE
 return newFrame.allow;
}
assert.equal(policy('extensionId=sima-neat.sima-neat'), 'autoplay; camera *;');
assert.equal(policy('extensionId=other.extension'), 'autoplay;');
assert.equal(policy(''), 'autoplay;');
'''.replace('SOURCE', updated)
        subprocess.run(['node', '-e', script], check=True)

    def test_drift_fails_before_patching(self):
        for fn in [patch.patch_workbench, patch.patch_preload]:
            with self.assertRaises(ValueError):
                fn('unrecognized upstream layout')


if __name__ == '__main__':
    unittest.main()
