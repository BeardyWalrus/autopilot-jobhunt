"""Launch the web UI: `autopilot web [--host H] [--port P]`.

Binds 0.0.0.0:8000 by default — reachable from other machines on your network.
There is NO authentication, so pin it to 127.0.0.1 (`--host 127.0.0.1`) if you
only want local access. Override with flags or the AUTOPILOT_WEB_HOST /
AUTOPILOT_WEB_PORT env vars.
"""
import argparse
import os
import sys

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def run_server(argv: list[str] | None = None) -> None:
    try:
        import uvicorn
    except ImportError:
        sys.exit("Web UI needs extra deps. Run: pip install 'autopilot-jobhunt[web]'")

    parser = argparse.ArgumentParser(prog="autopilot web")
    parser.add_argument("--host", default=os.getenv("AUTOPILOT_WEB_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("AUTOPILOT_WEB_PORT", "8000")))
    args = parser.parse_args(argv or [])

    if args.host not in _LOOPBACK:
        print(
            "⚠  Serving on all interfaces with NO authentication — anyone who can\n"
            "   reach this host can view and edit your config, including API keys.\n"
            "   Use --host 127.0.0.1 for local-only, or keep it behind a trusted network.\n"
        )
    print(f"autopilot web → http://{args.host}:{args.port}")
    uvicorn.run("job_hunt.web.app:app", host=args.host, port=args.port, log_level="info")
