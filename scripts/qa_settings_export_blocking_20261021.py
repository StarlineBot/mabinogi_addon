"""Historical QA command; shared regression uses the real SettingsTab worker lifecycle."""
from test_support.regressions.settings_export import (
    test_bundle_compression_does_not_run_on_ui_thread,
    test_automatic_recovery_backup_does_not_export_secrets,
)
