# three.js (vendored)

- Package: `three` 0.169.0 from the npm registry
  (`https://registry.npmjs.org/three/-/three-0.169.0.tgz`,
  sha256 `c86d0937570fb425d981e156ddf919c43dbc45d4e91fd7c8dd0de56723b3ec71`).
- Licence: MIT (see `LICENSE`, copied unchanged from the package).
- Contents: `build/three.module.min.js` as `three.module.min.js`, and an
  unmodified subset of `examples/jsm` under `addons/` (post-processing with
  bloom, glTF loader, room environment, rounded box geometry).

Recipes load it with an import map, so they work offline from the virtual origin:

~~~html
<script type="importmap">
{"imports": {"three": "../../_lib/three/three.module.min.js",
             "three/addons/": "../../_lib/three/addons/"}}
</script>
~~~

Upgrade by replacing these files from a newer tarball and updating the version
and checksum above; every recipe that lists `three` in `libraries` gets a new
provenance hash automatically.
