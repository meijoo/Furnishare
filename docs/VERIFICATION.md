# Verification — October 10, 2026

- Xcode 26.6 simulator build: passed, code signing disabled.
- Xcode 26.6 iOS device build: passed, code signing disabled.
- Five domain tests: passed (stale approvals, limits, exact totals, duplicate approval, confirmed-purchase prerequisite, unequal reimbursements).
- Local API /health and /products: HTTP 200 smoke checks passed.
- Python syntax compilation: passed for backend, ML, and Blender scripts.
- Physical iPad AR, measured scale, gestures, and camera permission flow: awaiting device test.
- Simulator launch was initiated; UI verification was not yet completed during initial simulator setup.
- ML training and Blender execution: not run; their runtime dependencies/data are not installed or bundled.
- Sponsor integrations: not implemented or tested.

Unsigned device compilation does not install the app on an iPad. Select a development team in Xcode and run on the connected device.
