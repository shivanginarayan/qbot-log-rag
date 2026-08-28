#!/usr/bin/env python3

import argparse
import queue
import threading
import time
import sys
from pathlib import Path


HERE = Path(__file__).resolve()
COMPARISON_ROOT = HERE.parents[1]

if str(COMPARISON_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(COMPARISON_ROOT),
    )


from common.embedding_client import (
    embed,
)

from common.session_utils import (
    resolve_session_id,
)

from explaining_autonomy.persistent_memory import (
    upsert_records,
)


class LiveRosoutMemory:
    def __init__(
        self,
        session_id,
        flush_every=10,
        flush_interval_s=2.0,
    ):
        self.session_id = (
            session_id
        )

        self.flush_every = max(
            1,
            int(
                flush_every
            ),
        )

        self.flush_interval_s = max(
            0.1,
            float(
                flush_interval_s
            ),
        )

        self.queue = queue.Queue()

        self.pending = []

        self.lock = threading.Lock()

        self.previous_signature = None

        self.received = 0

        self.skipped = 0

        self.embedded = 0

        self.running = True

        self.last_flush = (
            time.monotonic()
        )

        self.worker = threading.Thread(
            target=self._worker,
            daemon=True,
        )

        self.worker.start()

    def add_message(
        self,
        message,
        timestamp_ns,
    ):
        level = getattr(
            message,
            "level",
            None,
        )

        name = getattr(
            message,
            "name",
            "",
        )

        if name == "rosbag2_recorder":
            return

        msg = getattr(
            message,
            "msg",
            "",
        )

        file_name = getattr(
            message,
            "file",
            "",
        )

        function_name = getattr(
            message,
            "function",
            "",
        )

        line = getattr(
            message,
            "line",
            None,
        )

        signature = (
            level,
            name,
            msg,
            file_name,
            function_name,
            line,
        )

        with self.lock:
            self.received += 1

            if (
                signature
                == self.previous_signature
            ):
                self.skipped += 1
                return

            self.previous_signature = (
                signature
            )

        self.queue.put(
            {
                "session_id":
                    self.session_id,

                "timestamp_ns":
                    int(
                        timestamp_ns
                    ),

                "level":
                    level,

                "name":
                    name,

                "message":
                    msg,

                "file":
                    file_name,

                "function":
                    function_name,

                "line":
                    line,

                "text":
                    f"[{level}] [{name}] {msg}",
            }
        )

    def _flush(
        self,
        force=False,
    ):
        now = time.monotonic()

        with self.lock:
            should_flush = (
                force
                or len(
                    self.pending
                )
                >= self.flush_every
                or (
                    self.pending
                    and (
                        now
                        - self.last_flush
                    )
                    >= self.flush_interval_s
                )
            )

            if not should_flush:
                return

            batch = list(
                self.pending
            )

            self.pending.clear()

            self.last_flush = (
                now
            )

        if not batch:
            return

        stats = upsert_records(
            batch
        )

        print(
            "Persistent /rosout memory:"
            f" +{stats['added']} records,"
            f" total={stats['total']},"
            f" sessions={stats['session_count']}"
        )

    def _worker(
        self,
    ):
        while (
            self.running
            or not self.queue.empty()
        ):
            try:
                record = self.queue.get(
                    timeout=0.25
                )

            except queue.Empty:
                self._flush()
                continue

            try:
                vector = embed(
                    record[
                        "text"
                    ]
                )

                indexed = {
                    "record_id":
                        None,

                    **record,

                    "embedding":
                        vector,
                }

                with self.lock:
                    indexed[
                        "record_id"
                    ] = self.embedded

                    self.embedded += 1

                    self.pending.append(
                        indexed
                    )

                self._flush()

            except Exception as exc:
                print(
                    "WARNING: Could not embed live /rosout record:"
                )

                print(
                    f"  node={record.get('name')}"
                )

                print(
                    f"  message={record.get('message', '')[:300]}"
                )

                print(
                    f"  error={exc}"
                )

            finally:
                self.queue.task_done()

        self._flush(
            force=True
        )

    def stop(
        self,
    ):
        self.running = False

        self.queue.join()

        self.worker.join(
            timeout=10.0
        )

        self._flush(
            force=True
        )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--session-id",
        default="latest",
        help=(
            "Session ID stored as metadata on incoming live logs. "
            "Default resolves the current latest runtime session."
        ),
    )

    parser.add_argument(
        "--flush-every",
        type=int,
        default=10,
    )

    parser.add_argument(
        "--flush-interval-s",
        type=float,
        default=2.0,
    )

    args = parser.parse_args()

    session_id = resolve_session_id(
        args.session_id
    )

    import rclpy

    from rcl_interfaces.msg import (
        Log,
    )

    try:
        from rclpy.qos import (
            qos_profile_rosout_default,
        )

        qos = (
            qos_profile_rosout_default
        )

    except Exception:
        from rclpy.qos import (
            QoSProfile,
        )

        qos = QoSProfile(
            depth=1000
        )

    memory = LiveRosoutMemory(
        session_id=(
            session_id
        ),
        flush_every=(
            args.flush_every
        ),
        flush_interval_s=(
            args.flush_interval_s
        ),
    )

    rclpy.init()

    node = rclpy.create_node(
        "explaining_autonomy_live_memory"
    )

    def callback(
        message,
    ):
        stamp = getattr(
            message,
            "stamp",
            None,
        )

        if stamp is not None:
            timestamp_ns = (
                int(
                    stamp.sec
                )
                * 1_000_000_000
                + int(
                    stamp.nanosec
                )
            )

        else:
            timestamp_ns = (
                node.get_clock()
                .now()
                .nanoseconds
            )

        memory.add_message(
            message,
            timestamp_ns,
        )

    node.create_subscription(
        Log,
        "/rosout",
        callback,
        qos,
    )

    print()
    print(
        "Explaining-Autonomy-style persistent /rosout memory is running."
    )

    print(
        "Current live session metadata:",
        session_id,
    )

    print()
    print(
        "Current /rosout messages are being embedded and appended "
        "to the same cumulative corpus used for prior sessions."
    )

    print()
    print(
        "Ask from another terminal:"
    )

    print(
        '  ./comparison_experiments/run_comparison.sh rosout '
        '--memory --question "What is happening?" --show-retrieval'
    )

    print()
    print(
        "Press Ctrl+C to stop."
    )

    try:
        rclpy.spin(
            node
        )

    except KeyboardInterrupt:
        pass

    finally:
        memory.stop()

        node.destroy_node()

        rclpy.shutdown()


if __name__ == "__main__":
    main()
