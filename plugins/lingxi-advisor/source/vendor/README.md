# Delivery Node dependencies

`npm/` contains the five production packages pinned in `source/package-lock.json`, with their original license files. Their bytes were compared with the npm registry tarballs after checking each lockfile SHA-512 integrity value.

`build-delivery` copies them into `kit/node_modules/`; these nested files are included in the Delivery lock. A local-directory `npx --package` invocation can symlink the bin into the npm cache while worker modules resolve from the original directory. Shipping the dependencies makes both the interactive CLI and managed workers independent of npm cache module resolution. Top-level `node_modules/` created by `npm ci` remains local installation state, outside the Delivery payload.

When updating dependencies, update `package.json` and its lock, replace all five pinned package payloads, verify the registry integrity and bytes, then rebuild both Deliveries. Do not hand-edit vendored package code.
