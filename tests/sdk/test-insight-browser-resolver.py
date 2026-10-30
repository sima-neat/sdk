#!/usr/bin/env python3
"""Exercise the patched resolver, including the actual installed bundle if supplied."""
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("resolver_patch", ROOT / "tools/patch_insight_browser_resolver.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
BUNDLE = Path(sys.argv.pop()).read_text() if len(sys.argv) > 1 else None


class ResolverTest(unittest.TestCase):
    def test_layout_drift_fails_and_patch_is_idempotent(self):
        for source in ["", "resolveExternalUri:x=>{};resolveExternalUri:y=>{}"]:
            with self.assertRaises(ValueError):
                module.patch(source)
        patched = module.patch("resolveExternalUri:x=>{return Promise.resolve(x)}")
        self.assertEqual(module.patch(patched), patched)

    def test_browser_resolution(self):
        source = BUNDLE or ('resolveExternalUri:n=>{let r=n,a=Jnt(r);'
            'if(a&&r.authority!==location.host)if(e.productConfiguration&&e.productConfiguration.proxyEndpointTemplate)'
            '{let c=e.productConfiguration.proxyEndpointTemplate.replace("{{port}}",a.port.toString()).replace("{{host}}",window.location.host),'
            'l=P.parse(new URL(c,window.location.href).toString());'
            'r=l.with({path:l.path.replace(/\\/$/,"")+n.path,query:n.query,fragment:n.fragment})}'
            'else throw new Error("missing template");return Promise.resolve(r)},tunnelProvider:')
        patched = module.patch(source)
        match = re.search(r'resolveExternalUri:(.*?),tunnelProvider:', patched)
        self.assertIsNotNone(match)
        script = '''
const assert = require("node:assert/strict");
const uri = (value) => {
  const u = new URL(value);
  return {scheme:u.protocol.slice(0,-1), authority:u.host, path:u.pathname,
    query:u.search.slice(1), fragment:u.hash.slice(1),
    with(parts) {return {...this,...parts};}};
};
const location = {host:"sdk.example.test:10000"};
const window = {location:{host:location.host,href:"https://sdk.example.test:10000/"}};
const e = {productConfiguration:{proxyEndpointTemplate:"https://{{host}}/proxy/{{port}}"}};
const Jnt = (u) => { const p=Number(u.authority.split(":").pop()); return p ? {port:p} : undefined; };
const P = {parse:uri};
const resolve = RESOLVER;
(async () => {
 for (const host of ["127.0.0.1", "192.168.76.60", "remote.example.test"]) {
  const result = await resolve(uri(`https://${host}:19900/view?launch-source=host-override&palette-insight-direct=1#viewer`));
  assert.equal(result.authority,`${host}:19900`);
  assert.equal(result.scheme,"https");
  assert.equal(result.path,"/view");
  assert.equal(result.query,"launch-source=host-override");
  assert.equal(result.fragment,"viewer");
 }
 for (const value of ["http://127.0.0.1:3000/", "https://127.0.0.1:9900/",
                       "http://127.0.0.1:9900/?palette-insight-direct=1"]) {
  const result=await resolve(uri(value));
  assert.equal(result.authority,location.host);
  assert.match(result.path,/^\\/proxy\\//);
 }
})().catch(e=>{console.error(e);process.exitCode=1});
'''.replace("RESOLVER", match[1])
        subprocess.run(["node", "-e", script], check=True)


if __name__ == "__main__":
    unittest.main()
