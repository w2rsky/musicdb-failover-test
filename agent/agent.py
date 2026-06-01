#!/usr/bin/env python3

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer


def tcp_reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class ArbiterHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/health":
            json_response(self, 200, {"status": "ok"})
            return

        if parsed.path == "/master-status":
            query = urllib.parse.parse_qs(parsed.query)
            host = query.get("host", ["postgres-master"])[0]
            port = int(query.get("port", ["5432"])[0])
            reachable = tcp_reachable(host, port)
            json_response(
                self,
                200,
                {
                    "role": "arbiter",
                    "checked_host": host,
                    "checked_port": port,
                    "reachable": reachable,
                },
            )
            return

        json_response(self, 404, {"error": "not found"})


def run_arbiter(args):
    server = HTTPServer((args.bind, args.port), ArbiterHandler)
    print(f"Arbiter listening on {args.bind}:{args.port}", flush=True)
    server.serve_forever()


def run_command(command, check=True):
    print("+ " + " ".join(command), flush=True)
    return subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def standby_is_in_recovery(container: str) -> bool:
    result = run_command(
        [
            "docker",
            "exec",
            "-u",
            "postgres",
            container,
            "psql",
            "-U",
            "postgres",
            "-d",
            "musicdb",
            "-tAc",
            "SELECT pg_is_in_recovery();",
        ],
        check=False,
    )

    if result.returncode != 0:
        print(result.stderr.strip(), flush=True)
        return False

    return result.stdout.strip().lower() == "t"


def promote_standby(container: str):
    if not standby_is_in_recovery(container):
        print("Standby is already promoted or not available.", flush=True)
        return

    result = run_command(
        [
            "docker",
            "exec",
            "-u",
            "postgres",
            container,
            "pg_ctl",
            "-D",
            "/var/lib/postgresql/data",
            "promote",
        ],
        check=False,
    )

    if result.stdout.strip():
        print(result.stdout.strip(), flush=True)

    if result.returncode != 0:
        print(result.stderr.strip(), flush=True)
        sys.exit(result.returncode)

    print("Standby promotion command executed.", flush=True)


def ask_arbiter(arbiter_url: str, master_host: str, master_port: int) -> bool:
    query = urllib.parse.urlencode({"host": master_host, "port": master_port})
    url = f"{arbiter_url.rstrip('/')}/master-status?{query}"

    with urllib.request.urlopen(url, timeout=3) as response:
        payload = json.loads(response.read().decode("utf-8"))

    return bool(payload["reachable"])


def run_standby_agent(args):
    print("Standby failover agent started.", flush=True)
    print(f"Local master check: {args.master_host}:{args.master_port}", flush=True)
    print(f"Arbiter URL: {args.arbiter_url}", flush=True)
    print(f"Standby container: {args.standby_container}", flush=True)

    while True:
        master_seen_by_standby = tcp_reachable(
            args.master_host,
            args.master_port,
            timeout=args.timeout,
        )

        if master_seen_by_standby:
            print("Master is reachable from standby agent. No failover.", flush=True)
        else:
            print("Master is NOT reachable from standby agent. Asking arbiter...", flush=True)

            try:
                master_seen_by_arbiter = ask_arbiter(
                    args.arbiter_url,
                    args.arbiter_master_host,
                    args.master_port,
              )
            except Exception as exc:
                print(f"Arbiter unavailable or error: {exc}", flush=True)
                print("No promotion. This prevents split-brain.", flush=True)
                master_seen_by_arbiter = True

            if not master_seen_by_arbiter:
                print("Arbiter also cannot reach master. Promotion is safe.", flush=True)
                promote_standby(args.standby_container)
            else:
                print("Arbiter can still reach master. No promotion.", flush=True)

        if args.once:
            break

        time.sleep(args.interval)


def main():
    parser = argparse.ArgumentParser(description="PostgreSQL failover agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    arbiter = subparsers.add_parser("arbiter")
    arbiter.add_argument("--bind", default="0.0.0.0")
    arbiter.add_argument("--port", type=int, default=8000)
    arbiter.set_defaults(func=run_arbiter)

    standby = subparsers.add_parser("standby")
    standby.add_argument("--master-host", default="127.0.0.1")
    standby.add_argument("--master-port", type=int, default=5432)
    standby.add_argument("--arbiter-master-host", default="postgres-master")
    standby.add_argument("--arbiter-url", default="http://127.0.0.1:8000")
    standby.add_argument("--standby-container", default="pg_standby")
    standby.add_argument("--interval", type=int, default=3)
    standby.add_argument("--timeout", type=float, default=1.5)
    standby.add_argument("--once", action="store_true")
    standby.set_defaults(func=run_standby_agent)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
