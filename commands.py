import sublime
import sublime_plugin
import os
from .settings import get_settings, get_tests_file_path

# Run all tests command
class CpRunAllTestsCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        window = self.view.window()
        opd_view = next(
            (v for v in window.views() if v.settings().get("is_opd_view")), None
        )
        if opd_view:
            opd_view.run_command("test_manager", {"action": "run_all_tests"})
        else:
            sublime.status_message("No active run view found")

# Open problem (shows current test file if available)
class CpOpenProblemCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        window = self.view.window()
        opd_view = next(
            (v for v in window.views() if v.settings().get("is_opd_view")), None
        )
        if not opd_view:
            sublime.status_message("No run view found")
            return

        run_file = getattr(opd_view, "dbg_file", None)
        if not run_file:
            session = getattr(opd_view.run_command("test_manager", {}), "session", None)
            if session:
                run_file = session.get("run_file")

        if run_file and os.path.exists(run_file):
            window.open_file(run_file)
        else:
            sublime.status_message("No source file linked to this session")