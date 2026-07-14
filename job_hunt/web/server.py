"""Launch the web UI: `autopilot web [--host H] [--port P]`.

Defaults to 127.0.0.1:8000 — local-only, no auth. Override the bind with flags
or the AUTOPILOT_WEB_HOST / AUTOPILOT_WEB_PORT env vars (the Docker image sets
the host to 0.0.0.0 inside the container and you publish it to 127.0.0.1).
"""
import argparse
import os
import sys


def run_server(argv: list[str] | None = None) -> None:
    try:
        import uvicorn
    except ImportError:
        sys.exit("Web UI needs extra deps. Run: pip install 'autopilot-jobhunt[web]'")

    parser = argparse.ArgumentParser(prog="autopilot web")
    parser.add_argument("--host", default=os.getenv("AUTOPILOT_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("AUTOPILOT_WEB_PORT", "8000")))
    args = parser.parse_args(argv or [])

    print(f"autopilot web → http://{args.host}:{args.port}")
    uvicorn.run("job_hunt.web.app:app", host=args.host, port=args.port, log_level="info")
