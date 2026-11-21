# Custom image example

This is a complete sample image specification and its inputs. The same files are
shipped in the container and consumed by CI on both builder architectures.

After [installing the pib launcher](../../../docs/palette-image-builder.md), run:

```bash
pib init my-example --example custom-image
cd my-example
pib keys init --cn 'My Company Development'
pib shell -c 'dpkg-deb --root-owner-group --build package-root custom-debs/pib-example-app_1.0.0_all.deb'
pib sign-debs
pib build --sign
pib verify
```

Move `keys/ca.key` to secure offline storage after key creation.

`image.yaml` adds the example Debian package, copies `overlay/` into the image,
and runs `hooks/enable-example.sh` to enable a systemd service and record a build
marker. The application prints a greeting and its configuration. Nothing needs
to be fetched from the source repository to use the example: `pib init --example`
copies the packaged inputs and release board configuration into your project.

Expected artifacts include `out/*.swu`, `out/*.img.gz`, an SBOM, a package manifest,
and checksums. CI verifies the signed SWU, then extracts its rootfs to check the
application, configuration, service enablement, hook marker, and trusted CA.

This recipe uses development keys and leaves board accounts locked. It exercises
artifact generation; it does not qualify physical boot or update installation.
Increment `version` in `image.yaml` before another build to retain the old outputs.
