# Third-party notices

The prebuilt frontend includes code from the locked production dependencies below.
This list conservatively includes their transitive dependencies and required peers, even when tree-shaking removes some code.
License and notice texts are copied verbatim from the exact installed npm package versions; upstream terms apply.
Pako also includes the full zlib notice from `lib/zlib/README`.

isarray stores its complete MIT license in its README; that file is included verbatim.

Reproduce from the source repository: `npm ci`, then `python scripts/build_release.py --refresh-licenses`.
The machine-readable file `licenses/frontend/manifest.json` records package versions, npm integrity, source paths, and text SHA256 hashes.

| Package | Version | Declared license | Full text |
| --- | --- | --- | --- |
| core-util-is | 1.0.3 | MIT | [LICENSE](licenses/frontend/core-util-is-1.0.3/LICENSE) |
| docx-preview | 0.3.7 | Apache-2.0 | [LICENSE](licenses/frontend/docx-preview-0.3.7/LICENSE) |
| immediate | 3.0.6 | MIT | [LICENSE.txt](licenses/frontend/immediate-3.0.6/LICENSE.txt) |
| inherits | 2.0.4 | ISC | [LICENSE](licenses/frontend/inherits-2.0.4/LICENSE) |
| isarray | 1.0.0 | MIT | [README.md](licenses/frontend/isarray-1.0.0/README.md) |
| jszip | 3.10.2 | (MIT OR GPL-3.0-or-later) | [LICENSE.markdown](licenses/frontend/jszip-3.10.2/LICENSE.markdown) |
| lie | 3.3.0 | MIT | [license.md](licenses/frontend/lie-3.3.0/license.md) |
| lucide-react | 0.468.0 | ISC | [LICENSE](licenses/frontend/lucide-react-0.468.0/LICENSE) |
| pako | 1.0.11 | (MIT AND Zlib) | [lib__zlib__README](licenses/frontend/pako-1.0.11/lib__zlib__README), [LICENSE](licenses/frontend/pako-1.0.11/LICENSE) |
| process-nextick-args | 2.0.1 | MIT | [license.md](licenses/frontend/process-nextick-args-2.0.1/license.md) |
| react | 19.3.1 | MIT | [LICENSE](licenses/frontend/react-19.3.1/LICENSE) |
| react-dom | 19.3.1 | MIT | [LICENSE](licenses/frontend/react-dom-19.3.1/LICENSE) |
| readable-stream | 2.3.8 | MIT | [LICENSE](licenses/frontend/readable-stream-2.3.8/LICENSE) |
| safe-buffer | 5.1.2 | MIT | [LICENSE](licenses/frontend/safe-buffer-5.1.2/LICENSE) |
| scheduler | 0.28.0 | MIT | [LICENSE](licenses/frontend/scheduler-0.28.0/LICENSE) |
| setimmediate | 1.0.5 | MIT | [LICENSE.txt](licenses/frontend/setimmediate-1.0.5/LICENSE.txt) |
| string_decoder | 1.1.1 | MIT | [LICENSE](licenses/frontend/string_decoder-1.1.1/LICENSE) |
| util-deprecate | 1.0.2 | MIT | [LICENSE](licenses/frontend/util-deprecate-1.0.2/LICENSE) |

Python and its dependencies are installed separately by pip and are not vendored in the ZIP.
Their distributions retain their own licenses. The Python requirements are listed in `requirements.txt`.
