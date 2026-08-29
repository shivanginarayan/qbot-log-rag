#!/usr/bin/env python3

CAUSAL_EVENTS = {
    "localization_started": {
        "event_label": "localization started",
        "effect": "the robot started localization",
        "default_cause": "a localization execution-start event was reported",
        "question_examples": [
            "Why did localization start?",
            "Why did you start locating yourself?",
            "What caused the robot to begin localization?",
            "Why did the robot begin determining its position?",
        ],
    },
    "localization_succeeded": {
        "event_label": "localization succeeded",
        "effect": "the robot successfully determined its pose in the map",
        "default_cause": "the localization subsystem reported a successful completion",
        "question_examples": [
            "Why did localization succeed?",
            "How did the robot know localization worked?",
            "Why were you able to localize?",
            "How did the robot determine where it was?",
            "How did you successfully determine your position?",
            "Why was the robot able to establish its pose in the map?",
        ],
    },
    # "localization_failed_low_confidence": {
    #     "event_label": "localization failed because pose confidence was insufficient",
    #     "effect": "the robot failed to determine a sufficiently confident pose",
    #     "default_cause": "AMCL did not produce the required consecutive confident pose estimates",
    #     "question_examples": [
    #         "Why did localization fail?",
    #         "Why couldn't you figure out where you were?",
    #         "Why was the robot unable to localize?",
    #         "What went wrong with localization?",
    #         "Why couldn't you determine your position?",
    #         "Why couldn't the robot establish a confident pose?",
    #     ],
    # },
    "localization_failed": {
        "event_label": "localization failed",
        "effect": "the robot failed to determine its pose",
        "default_cause": "the localization subsystem reported a failure",
        "question_examples": [
            "Why did localization fail?",
            "What went wrong during localization?",
            "Why were you unable to localize?",
            "Why couldn't the robot determine its position?",
        ],
    },
    "navigation_started": {
        "event_label": "navigation started",
        "effect": "the robot started traveling toward a navigation destination",
        "default_cause": "a navigation execution-start event was reported",
        "question_examples": [
            "Why did navigation start?",
            "Why did the robot start traveling to the destination?",
            "Why did you begin navigating?",
            "Why did the robot start going to the target?",
        ],
    },
    "navigation_succeeded": {
        "event_label": "navigation succeeded",
        "effect": "the robot successfully completed travel to a navigation destination",
        "default_cause": "the navigation subsystem reported a successful completion",
        "question_examples": [
            "Why did navigation succeed?",
            "How did the robot know it reached the destination?",
            "Why was the navigation successful?",
            "How did the robot successfully get to the target?",
            "Why was the robot able to reach its destination?",
        ],
    },
    "navigation_failed": {
        "event_label": "navigation failed",
        "effect": "the robot failed to complete travel to the navigation destination",
        "default_cause": "the navigation subsystem reported a failure",
        "question_examples": [
            "Why did navigation fail?",
            "Why couldn't you reach the destination?",
            "What went wrong with navigation?",
            "Why did the robot fail to get there?",
            "Why couldn't the robot reach the target?",
        ],
    },
    "navigation_canceled": {
        "event_label": "navigation was canceled",
        "effect": "the active navigation task was canceled",
        "default_cause": "the navigation subsystem reported a cancellation",
        "question_examples": [
            "Why was navigation canceled?",
            "Why did you stop the navigation task?",
            "Why was the trip canceled?",
        ],
    },
    "map_transform_unavailable": {
        "event_label": "map transform was unavailable",
        "effect": "a component could not transform robot data into the map frame",
        "default_cause": "the required base_link-to-map transform was unavailable",
        "question_examples": [
            "Why couldn't the robot transform into the map frame?",
            "Why was the map transform unavailable?",
            "What was wrong with the transform?",
            "Why couldn't the costmap get the map transform?",
        ],
    },
}


def get_event_definition(event_name):
    return CAUSAL_EVENTS.get(event_name)
