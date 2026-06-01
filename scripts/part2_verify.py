#!/usr/bin/env python3

import argparse
import asyncio
import random
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import asyncpg


DEFAULT_MASTER_DSN = "postgresql://postgres:postgres_password@127.0.0.1:5432/musicdb"
DEFAULT_STANDBY_DSN = "postgresql://postgres:postgres_password@127.0.0.1:5433/musicdb"

VALID_SYNC_MODES = {"off", "local", "remote_write", "on", "remote_apply"}

VALID_FAULTS = {
    "master_crash",
    "master_network_partition",
    "standby_network_partition",
    "arbiter_network_partition",
}


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+ " + " ".join(cmd), flush=True)

    result = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.stdout.strip():
        print(result.stdout.strip(), flush=True)

    if result.stderr.strip():
        print(result.stderr.strip(), flush=True)

    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")

    return result


def require_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required binary not found: {name}")


def docker_compose(*args: str) -> None:
    run(["docker", "compose", *args])


async def wait_for_pg(
    dsn: str,
    *,
    writable: Optional[bool] = None,
    timeout: int = 90,
) -> None:
    deadline = time.time() + timeout
    last_error: Optional[Exception] = None

    while time.time() < deadline:
        try:
            conn = await asyncpg.connect(dsn, timeout=5)
            try:
                await conn.execute("SELECT 1;")

                if writable is not None:
                    in_recovery = await conn.fetchval("SELECT pg_is_in_recovery();")
                    is_writable = not bool(in_recovery)

                    if is_writable != writable:
                        await asyncio.sleep(1)
                        continue

                return
            finally:
                await conn.close()

        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1)

    raise TimeoutError(f"PostgreSQL was not ready: {last_error}")


async def wait_for_sync_replication(master_dsn: str, timeout: int = 90) -> None:
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            conn = await asyncpg.connect(master_dsn, timeout=5)
            try:
                row = await conn.fetchrow(
                    """
                    SELECT application_name, state, sync_state
                    FROM pg_stat_replication
                    WHERE application_name = 'pg_standby';
                    """
                )

                if row:
                    print(
                        f"Replication status: application={row['application_name']} "
                        f"state={row['state']} sync_state={row['sync_state']}",
                        flush=True,
                    )

                    if row["state"] == "streaming" and row["sync_state"] in {"sync", "quorum"}:
                        return

            finally:
                await conn.close()

        except Exception:
            pass

        await asyncio.sleep(1)

    raise TimeoutError("Synchronous replication was not ready.")


async def wait_for_table(dsn: str, table_name: str, timeout: int = 60) -> None:
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            conn = await asyncpg.connect(dsn, timeout=5)
            try:
                exists = await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                          AND table_name = $1
                    );
                    """,
                    table_name,
                )

                if exists:
                    return

            finally:
                await conn.close()

        except Exception:
            pass

        await asyncio.sleep(1)

    raise TimeoutError(f"Table {table_name} did not appear on standby in time.")


async def create_pool(
    dsn: str,
    sync_mode: str,
    pool_size: int,
    command_timeout: int,
) -> asyncpg.Pool:
    async def init_connection(conn: asyncpg.Connection) -> None:
        await conn.execute(f"SET synchronous_commit = '{sync_mode}';")
        await conn.execute(f"SET statement_timeout = '{command_timeout * 1000}ms';")
        await conn.execute("SET lock_timeout = '3000ms';")

    return await asyncpg.create_pool(
        dsn=dsn,
        min_size=1,
        max_size=pool_size,
        init=init_connection,
        command_timeout=command_timeout,
        timeout=command_timeout,
    )


async def prepare_test_table(pool: asyncpg.Pool) -> None:
    async with pool.acquire(timeout=5) as conn:
        await conn.execute("DROP TABLE IF EXISTS part2_numbers;")
        await conn.execute("CREATE TABLE part2_numbers(id BIGINT PRIMARY KEY);")


async def fetch_actual_rows(dsn: str) -> set[int]:
    conn = await asyncpg.connect(dsn, timeout=10)
    try:
        rows = await conn.fetch("SELECT id FROM part2_numbers;")
        return {int(row["id"]) for row in rows}
    finally:
        await conn.close()


def get_container_network(container_name: str) -> str:
    result = run(
        [
            "docker",
            "inspect",
            "-f",
            "{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}",
            container_name,
        ]
    )

    networks = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    if not networks:
        raise RuntimeError(f"No Docker networks found for container {container_name}")

    return networks[0]


def disconnect_container(container_name: str) -> None:
    network = get_container_network(container_name)
    run(["docker", "network", "disconnect", network, container_name], check=False)


def inject_fault(fault: str) -> None:
    print(f"\n=== Injecting fault: {fault} ===", flush=True)

    if fault == "master_crash":
        run(["docker", "kill", "--signal=SIGKILL", "pg_master"], check=False)

    elif fault == "master_network_partition":
        disconnect_container("pg_master")

    elif fault == "standby_network_partition":
        disconnect_container("pg_standby")

    elif fault == "arbiter_network_partition":
        disconnect_container("pg_arbiter")

    else:
        raise ValueError(f"Unsupported fault: {fault}")


def run_failover_agent_once(args: argparse.Namespace) -> None:
    run(
        [
            sys.executable,
            "agent/agent.py",
            "standby",
            "--once",
            "--master-host",
            "127.0.0.1",
            "--master-port",
            "5432",
            "--arbiter-master-host",
            "postgres-master",
            "--arbiter-url",
            "http://127.0.0.1:8000",
            "--standby-container",
            "pg_standby",
        ],
        check=False,
    )


@dataclass
class TestState:
    pool: asyncpg.Pool
    target_dsn: str
    pool_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    success_ids: set[int] = field(default_factory=set)
    failed_count: int = 0
    duplicate_count: int = 0

    async def switch_pool(self, new_pool: asyncpg.Pool, new_dsn: str) -> None:
        async with self.pool_lock:
            old_pool = self.pool
            self.pool = new_pool
            self.target_dsn = new_dsn

        # Important:
        # After master crash/network failure, old connections can hang.
        # terminate() closes them immediately instead of waiting forever.
        old_pool.terminate()


async def insert_one(
    state: TestState,
    value: int,
    max_delay_ms: int,
    insert_timeout: int,
) -> None:
    await asyncio.sleep(random.uniform(0, max_delay_ms) / 1000.0)

    async with state.pool_lock:
        pool = state.pool

    try:
        async with pool.acquire(timeout=insert_timeout) as conn:
            await asyncio.wait_for(
                conn.execute(
                    "INSERT INTO part2_numbers(id) VALUES($1);",
                    value,
                ),
                timeout=insert_timeout,
            )

        state.success_ids.add(value)

    except asyncpg.UniqueViolationError:
        state.duplicate_count += 1

    except Exception:
        state.failed_count += 1


async def worker(
    name: int,
    queue: asyncio.Queue,
    state: TestState,
    max_delay_ms: int,
    insert_timeout: int,
) -> None:
    while True:
        value = await queue.get()

        try:
            if value is None:
                return

            await insert_one(
                state=state,
                value=value,
                max_delay_ms=max_delay_ms,
                insert_timeout=insert_timeout,
            )

        finally:
            queue.task_done()


async def fault_controller(
    trigger_event: asyncio.Event,
    state: TestState,
    args: argparse.Namespace,
) -> None:
    await trigger_event.wait()

    inject_fault(args.fault)

    if args.fault in {"master_crash", "master_network_partition"}:
        await asyncio.sleep(args.failover_delay_seconds)

        run_failover_agent_once(args)

        await wait_for_pg(
            args.standby_dsn,
            writable=True,
            timeout=args.pg_ready_timeout,
        )

        standby_pool = await create_pool(
            dsn=args.standby_dsn,
            sync_mode=args.synchronous_commit,
            pool_size=args.pool_size,
            command_timeout=args.insert_timeout,
        )

        await state.switch_pool(standby_pool, args.standby_dsn)

        print("Client target switched to promoted standby.", flush=True)

    else:
        print(
            "Fault does not require promotion. Client continues using current target.",
            flush=True,
        )


async def run_test(args: argparse.Namespace) -> int:
    require_binary("docker")

    if args.synchronous_commit not in VALID_SYNC_MODES:
        raise ValueError(f"Invalid synchronous_commit mode: {args.synchronous_commit}")

    if args.fault not in VALID_FAULTS:
        raise ValueError(f"Invalid fault: {args.fault}")

    if args.reset_cluster:
        print("\n=== Deploying empty cluster ===", flush=True)
        docker_compose("down", "-v")
        docker_compose("up", "-d")

    print("\n=== Waiting for PostgreSQL nodes ===", flush=True)

    await wait_for_pg(
        args.master_dsn,
        writable=True,
        timeout=args.pg_ready_timeout,
    )

    await wait_for_pg(
        args.standby_dsn,
        writable=False,
        timeout=args.pg_ready_timeout,
    )

    await wait_for_sync_replication(
        args.master_dsn,
        timeout=args.pg_ready_timeout,
    )

    master_pool = await create_pool(
        dsn=args.master_dsn,
        sync_mode=args.synchronous_commit,
        pool_size=args.pool_size,
        command_timeout=args.insert_timeout,
    )

    state = TestState(
        pool=master_pool,
        target_dsn=args.master_dsn,
    )

    print("\n=== Preparing one-column primary-key table ===", flush=True)

    await prepare_test_table(master_pool)

    # Ensure that the initial table exists on standby before failure testing.
    # This prevents false failures caused by DDL not being visible yet.
    await wait_for_table(
        args.standby_dsn,
        "part2_numbers",
        timeout=args.pg_ready_timeout,
    )

    queue: asyncio.Queue = asyncio.Queue(maxsize=args.queue_size)
    fault_trigger = asyncio.Event()

    workers = [
        asyncio.create_task(
            worker(
                name=i,
                queue=queue,
                state=state,
                max_delay_ms=args.max_delay_ms,
                insert_timeout=args.insert_timeout,
            )
        )
        for i in range(args.concurrency)
    ]

    fault_task = asyncio.create_task(
        fault_controller(
            trigger_event=fault_trigger,
            state=state,
            args=args,
        )
    )

    print(
        "\n=== Starting workload ===\n"
        f"requests={args.requests}, "
        f"concurrency={args.concurrency}, "
        f"synchronous_commit={args.synchronous_commit}, "
        f"fault={args.fault}",
        flush=True,
    )

    fault_at = max(1, args.requests // 2)

    for value in range(1, args.requests + 1):
        await queue.put(value)

        if value == fault_at:
            print(f"\n=== Middle of test reached at request {value} ===", flush=True)
            fault_trigger.set()

            # Give the fault controller a chance to inject failure while
            # requests are still in progress.
            await asyncio.sleep(args.fault_start_pause_seconds)

    for _ in workers:
        await queue.put(None)

    await queue.join()
    await asyncio.gather(*workers, return_exceptions=True)
    await fault_task

    print("\n=== Reading final database state ===", flush=True)

    actual_rows = await fetch_actual_rows(state.target_dsn)

    acknowledged = state.success_ids
    missing = acknowledged - actual_rows
    extra = actual_rows - acknowledged

    print("\n=== Verification result ===", flush=True)
    print(f"acknowledged_successes={len(acknowledged)}", flush=True)
    print(f"actual_rows={len(actual_rows)}", flush=True)
    print(f"failed_requests={state.failed_count}", flush=True)
    print(f"duplicate_requests={state.duplicate_count}", flush=True)
    print(f"extra_rows_allowed={len(extra)}", flush=True)
    print(f"missing_acknowledged_rows={len(missing)}", flush=True)

    state.pool.terminate()

    if missing:
        sample = sorted(list(missing))[:20]
        print(f"FAILED: acknowledged rows were lost. sample={sample}", flush=True)
        return 1

    print("PASSED: no acknowledged committed rows were lost.", flush=True)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Part 2 PostgreSQL failover verification stress test"
    )

    parser.add_argument(
        "--requests",
        type=int,
        default=1_000_000,
        help="Total number of asynchronous insert requests.",
    )

    parser.add_argument(
        "--concurrency",
        type=int,
        default=200,
        help="Number of concurrent async workers.",
    )

    parser.add_argument(
        "--pool-size",
        type=int,
        default=50,
        help="Async PostgreSQL connection pool size.",
    )

    parser.add_argument(
        "--queue-size",
        type=int,
        default=10_000,
        help="Internal async queue size.",
    )

    parser.add_argument(
        "--max-delay-ms",
        type=int,
        default=20,
        help="Maximum random delay before each insert.",
    )

    parser.add_argument(
        "--insert-timeout",
        type=int,
        default=5,
        help="Timeout in seconds for one insert/acquire operation.",
    )

    parser.add_argument(
        "--pg-ready-timeout",
        type=int,
        default=90,
        help="Timeout in seconds for PostgreSQL readiness checks.",
    )

    parser.add_argument(
        "--fault-start-pause-seconds",
        type=float,
        default=0.2,
        help="Small pause after triggering the fault in the middle of workload.",
    )

    parser.add_argument(
        "--synchronous-commit",
        choices=sorted(VALID_SYNC_MODES),
        default="on",
        help="PostgreSQL synchronous_commit mode for client sessions.",
    )

    parser.add_argument(
        "--fault",
        choices=sorted(VALID_FAULTS),
        default="master_crash",
        help="Failure scenario to inject in the middle of the workload.",
    )

    parser.add_argument(
        "--failover-delay-seconds",
        type=int,
        default=3,
        help="Delay before running failover agent after master failure.",
    )

    parser.add_argument(
        "--reset-cluster",
        action="store_true",
        help="Redeploy an empty cluster before running the test.",
    )

    parser.add_argument(
        "--master-dsn",
        default=DEFAULT_MASTER_DSN,
        help="Connection string for master PostgreSQL.",
    )

    parser.add_argument(
        "--standby-dsn",
        default=DEFAULT_STANDBY_DSN,
        help="Connection string for standby PostgreSQL.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        exit_code = asyncio.run(run_test(args))
    except KeyboardInterrupt:
        print("Interrupted.", flush=True)
        exit_code = 130
    except Exception as exc:
        print(f"ERROR: {exc}", flush=True)
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

