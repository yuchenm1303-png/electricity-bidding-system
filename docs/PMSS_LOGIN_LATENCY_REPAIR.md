# PMSS login relay repair — 2026-10-18

Production host: VM-0-2-ubuntu. Site: https://power.smirel.com/app.

Observed school authorization response T000 (expired), despite an old rendered
school workbench. Initial authorization probe took 5.94s; the app probe has a
3.5s timeout. The bridge recreated ChromeDriver on every T000 retry and let
Selenium Manager resolve a driver each time. Screenshots/actions share a lock;
unbounded renderer commands could keep it held after the outer 10s HTTP timeout.

Applied on the host:

- Copied the existing matching cached ChromeDriver to
  `/opt/powerbid-platform-browser/chromedriver`.
- Configured `POWERBID_CHROMEDRIVER` through `driver.conf` systemd drop-ins for
  `powerbid-platform-bridge` and `powerbid-school-browser-login`.
- Both adapters use explicit Selenium Service and page load strategy `none`.
- Login adapter bounds command transport to 3s and page loads to 4s.
- Restarted these two adapters; the Chrome profile and VPN were preserved.
- Navigated the expired school tab to its fixed login URL. Verified the live
  login form and a real remote input-focus acknowledgment, without credentials.

Bridge backup: `/opt/powerbid-platform-bridge/bridge.py.before-latency-1792334408`.
Login adapter backup:
`/srv/powerbid-platform/private-cases/.browser-login/pmss_browser_operator.py.before-latency-1792334408`.
Rollback requires restoring both backups and removing the two driver.conf
drop-ins, followed by daemon-reload and restart of those two services only.

Measurements after repair: authorization probes 1.653/1.986/2.222s (T000);
frames 0.178/0.522/0.098s; subsequent login-page frame 0.326s.
One navigation still exceeded the outer timeout before transport bounds were
added; do not interpret these frame measurements as end-to-end login timings.

Frontend safeguards (12s fetch deadline, queue invalidation on failure,
single in-flight status check) were deployed after user authorization.
Server production build and 27 frontend workflow tests passed; all 8 public
assets match the release files. 12 targeted Python tests pass.

Frontend release image: `powerbid-studio:login-latency-3c3dc96`.
Previous image: `powerbid-studio:before-login-latency-3c3dc96`.
The existing runtime image tag also points to the repaired image so recreating
the existing deployment retains the repair. Frontend resources were copied
first, then the HTML entry point was replaced atomically; old hashed assets
were retained for already-open browser sessions.
Deployment manifest and original frontend backup are under
`/var/lib/sentinelx/uploads/powerbid-login-latency-3c3dc96/`.

Successful school authentication remains untested and requires the user's
school credentials.
