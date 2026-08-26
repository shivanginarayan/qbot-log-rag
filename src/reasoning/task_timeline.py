#!/usr/bin/env python3

import json


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(
    value,
):
    if value is None:
        return None

    value = str(
        value
    ).strip()

    if not value:
        return None

    return value.casefold()


# ============================================================
# COMMAND TYPES
# ============================================================

def command_event_types():
    return {
        "NAVIGATION_COMMAND",
        "LOCALIZE_COMMAND",
        "STOP_COMMAND",
    }


# ============================================================
# TASK IDENTITY
# ============================================================

def same_task_identity(
    command,
    event,
):
    """
    Decide whether a later event belongs to a command.

    Rules:

    1. Events must be from the same session.
    2. task_type must match.
    3. For navigate_to_location, label must also match
       when both labels are available.
    4. For localization, labels are NOT compared because:

           command label:
               __localize__

           runtime label:
               localize (AMCL global localization)

       These represent the same task.
    """

    # --------------------------------------------------------
    # Session boundary is absolute.
    # Never pair events across sessions.
    # --------------------------------------------------------

    if (
        command.get(
            "session_id"
        )
        != event.get(
            "session_id"
        )
    ):
        return False

    command_task = (
        normalize_text(
            command.get(
                "task_type"
            )
        )
    )

    event_task = (
        normalize_text(
            event.get(
                "task_type"
            )
        )
    )

    if (
        command_task
        != event_task
    ):
        return False

    # --------------------------------------------------------
    # Navigation-to-label needs label identity.
    # --------------------------------------------------------

    if (
        command_task
        == "navigate_to_location"
    ):

        command_label = (
            normalize_text(
                command.get(
                    "label_name"
                )
            )
        )

        event_label = (
            normalize_text(
                event.get(
                    "label_name"
                )
            )
        )

        if (
            command_label
            and event_label
            and command_label
            != event_label
        ):
            return False

    # --------------------------------------------------------
    # Localization deliberately ignores label differences.
    #
    # __localize__
    #
    # and
    #
    # localize (AMCL global localization)
    #
    # are the same task semantically.
    # --------------------------------------------------------

    return True


# ============================================================
# STATUS → OUTCOME
# ============================================================

def status_to_outcome(
    status,
):
    status = str(
        status
    )

    if status == "4":
        return "succeeded"

    if status == "5":
        return "canceled"

    if status == "6":
        return "failed"

    return "finished_unknown"


# ============================================================
# BUILD TASK LIFECYCLES
# ============================================================

def build_task_lifecycles(
    events,
):
    """
    Convert structured task events into task lifecycles.

    Examples:

        NAVIGATION_COMMAND
            → NAVIGATION_STARTED
            → NAVIGATION_FINISHED

        LOCALIZE_COMMAND
            → NAVIGATION_STARTED
                task_type=localization
            → NAVIGATION_FINISHED
                task_type=localization

    Important:

    - lifecycle relationships are based on structured
      task/session identity and chronology.

    - lifecycle relationships do NOT establish causality.

    - a missing STARTED event means only that no matching
      STARTED event was recorded for that command.

    - in an active session, missing FINISHED must not
      automatically be called interruption/failure.
    """

    events = sorted(
        events,
        key=lambda event: (
            str(
                event.get(
                    "session_id"
                )
            ),
            int(
                event.get(
                    "event_time_ns",
                    0,
                )
            ),
        ),
    )

    lifecycles = []

    for index, command in enumerate(
        events
    ):

        command_type = (
            command.get(
                "event_type"
            )
        )

        if (
            command_type
            not in command_event_types()
        ):
            continue

        session_id = (
            command.get(
                "session_id"
            )
        )

        task_type = (
            command.get(
                "task_type"
            )
        )

        lifecycle = {
            "command":
                command,

            "execution_started":
                None,

            "completion":
                None,

            "status_events":
                [],

            "session_id":
                session_id,

            "task_type":
                task_type,

            "map":
                command.get(
                    "map"
                ),

            "map_source":
                command.get(
                    "map_source"
                ),

            "label_name":
                command.get(
                    "label_name"
                ),

            "command_time_ns":
                command.get(
                    "event_time_ns"
                ),

            "execution_start_ns":
                None,

            "finish_ns":
                None,

            "outcome":
                None,
        }

        # ----------------------------------------------------
        # Search forward only in this command's session.
        # ----------------------------------------------------

        for later in events[
            index + 1:
        ]:

            later_session = (
                later.get(
                    "session_id"
                )
            )

            # ------------------------------------------------
            # Since events are sorted by session then time,
            # reaching another session means we're done.
            # ------------------------------------------------

            if (
                later_session
                != session_id
            ):
                break

            later_type = (
                later.get(
                    "event_type"
                )
            )

            later_task_type = (
                normalize_text(
                    later.get(
                        "task_type"
                    )
                )
            )

            command_task_type = (
                normalize_text(
                    task_type
                )
            )

            # ------------------------------------------------
            # A newer command for the SAME task family ends
            # this command's matching window.
            #
            # Example:
            #
            # LOCALIZE_COMMAND #1
            # LOCALIZE_COMMAND #2
            # STARTED
            #
            # STARTED belongs to #2, not #1.
            # ------------------------------------------------

            if (
                later_type
                in command_event_types()
                and later_task_type
                == command_task_type
            ):
                break

            if not same_task_identity(
                command,
                later,
            ):
                continue

            # ------------------------------------------------
            # START EVENT
            # ------------------------------------------------

            if (
                lifecycle[
                    "execution_started"
                ]
                is None
                and later_type
                == "NAVIGATION_STARTED"
            ):

                lifecycle[
                    "execution_started"
                ] = later

                lifecycle[
                    "execution_start_ns"
                ] = later.get(
                    "event_time_ns"
                )

                # --------------------------------------------
                # Runtime event may contain better map
                # information than the original command.
                # --------------------------------------------

                if (
                    lifecycle.get(
                        "map"
                    )
                    is None
                    and later.get(
                        "map"
                    )
                    is not None
                ):

                    lifecycle[
                        "map"
                    ] = later.get(
                        "map"
                    )

                    lifecycle[
                        "map_source"
                    ] = later.get(
                        "map_source"
                    )

                continue

            # ------------------------------------------------
            # FINISH EVENT
            # ------------------------------------------------

            if (
                later_type
                == "NAVIGATION_FINISHED"
            ):

                lifecycle[
                    "completion"
                ] = later

                lifecycle[
                    "finish_ns"
                ] = later.get(
                    "event_time_ns"
                )

                lifecycle[
                    "outcome"
                ] = status_to_outcome(
                    later.get(
                        "status"
                    )
                )

                if (
                    lifecycle.get(
                        "map"
                    )
                    is None
                    and later.get(
                        "map"
                    )
                    is not None
                ):

                    lifecycle[
                        "map"
                    ] = later.get(
                        "map"
                    )

                    lifecycle[
                        "map_source"
                    ] = later.get(
                        "map_source"
                    )

                break

            # ------------------------------------------------
            # OTHER STATUS EVENTS
            # ------------------------------------------------

            if (
                later_type
                in {
                    "NAVIGATION_STATUS",
                    "NAVIGATION_STATUS_RAW",
                }
            ):

                lifecycle[
                    "status_events"
                ].append(
                    later
                )

        # ----------------------------------------------------
        # DERIVE NON-COMPLETED STATE
        # ----------------------------------------------------

        if (
            lifecycle[
                "completion"
            ]
            is None
        ):

            if (
                lifecycle[
                    "execution_started"
                ]
                is not None
            ):

                lifecycle[
                    "outcome"
                ] = (
                    "started_no_completion_recorded"
                )

            else:

                lifecycle[
                    "outcome"
                ] = (
                    "no_execution_start_recorded"
                )

        lifecycles.append(
            lifecycle
        )

    return lifecycles


# ============================================================
# COMPACT REPRESENTATION
# ============================================================

def compact_lifecycle(
    lifecycle,
):
    command = (
        lifecycle.get(
            "command"
        )
        or {}
    )

    started = (
        lifecycle.get(
            "execution_started"
        )
        or {}
    )

    completion = (
        lifecycle.get(
            "completion"
        )
        or {}
    )

    return {
        "session_id":
            lifecycle.get(
                "session_id"
            ),

        "task_event_id":
            command.get(
                "task_event_id"
            ),

        "task_type":
            lifecycle.get(
                "task_type"
            ),

        "map":
            lifecycle.get(
                "map"
            ),

        "map_source":
            lifecycle.get(
                "map_source"
            ),

        "label_name":
            lifecycle.get(
                "label_name"
            ),

        "command_event_type":
            command.get(
                "event_type"
            ),

        "command_time_ns":
            lifecycle.get(
                "command_time_ns"
            ),

        "execution_start_ns":
            lifecycle.get(
                "execution_start_ns"
            ),

        "finish_ns":
            lifecycle.get(
                "finish_ns"
            ),

        "outcome":
            lifecycle.get(
                "outcome"
            ),

        "start_status":
            started.get(
                "status"
            ),

        "final_status":
            completion.get(
                "status"
            ),

        "completion_message":
            (
                completion.get(
                    "payload",
                    {}
                )
                .get(
                    "message"
                )
            ),

        "status_event_count":
            len(
                lifecycle.get(
                    "status_events",
                    []
                )
            ),
    }


# ============================================================
# FIND ONE COMMAND LIFECYCLE
# ============================================================

def find_lifecycle_for_event(
    events,
    task_event_id,
    session_id=None,
):
    """
    Find a lifecycle by its command task_event_id.

    session_id should be supplied when possible because
    task_event_id values restart in each session database.
    """

    for lifecycle in build_task_lifecycles(
        events
    ):

        command = (
            lifecycle.get(
                "command"
            )
            or {}
        )

        if (
            command.get(
                "task_event_id"
            )
            != task_event_id
        ):
            continue

        if (
            session_id is not None
            and command.get(
                "session_id"
            )
            != session_id
        ):
            continue

        return lifecycle

    return None


# ============================================================
# CLI
# ============================================================

def main():
    import argparse

    try:
        from .generic_event_query import (
            load_all_events,
        )

    except ImportError:
        from generic_event_query import (
            load_all_events,
        )

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--session-id",
    )

    args = parser.parse_args()

    events = load_all_events(
        current_session_id=(
            args.session_id
        )
    )

    if args.session_id:

        events = [
            event
            for event in events
            if event.get(
                "session_id"
            )
            == args.session_id
        ]

    lifecycles = (
        build_task_lifecycles(
            events
        )
    )

    print(
        json.dumps(
            [
                compact_lifecycle(
                    lifecycle
                )
                for lifecycle
                in lifecycles
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()