# Missing Keyboard Handlers

Several inline keyboard buttons are defined across plugins without registered callback handlers. Clicking them results in no response. This issue summarizes the modules and callbacks that currently lack handling logic.

## Unhandled Callbacks

- **test_part**: `detailed_report`, `export_csv`, `work_mistakes`, `check_subscription`
- **task24**: `show_detailed_progress`, `show_completed`, `show_remaining`
- **task20**: `t20_achievement_ok`
- **task25**: `t25_example_nav:<idx>`, `t25_noop`, `t25_try_topic:<id>`

## Suggested Fix

Implement callback query handlers for all defined callbacks or remove unused buttons. Ensure each keyboard button triggers appropriate behavior.
