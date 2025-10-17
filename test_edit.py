import sublime, sublime_plugin
from sublime import Region

class TestEditCommand(sublime_plugin.TextCommand):
    def run(self, edit, **kwargs):
        action = kwargs.get('action')
        if action == 'init':
            self.view.set_scratch(True)
            self.view.settings().set('foc_test_edit_view', True)
            self.view.settings().set('source_view_id', kwargs['source_view_id'])
            self.view.settings().set('test_id', kwargs['test_id'])

            input_data = kwargs.get('test', '')
            correct_answer = kwargs.get('correct_answer', '')

            header = "--- INPUT --- (Do not delete this line)\n"
            separator = "\n--- EXPECTED OUTPUT --- (Do not delete this line)\n"

            full_content = header + input_data + separator + correct_answer

            self.view.set_name("Edit Test Case #{}".format(kwargs['test_id']))
            self.view.insert(edit, 0, full_content)


class TestEditListener(sublime_plugin.EventListener):
    def on_pre_close(self, view):
        if not view.settings().get('foc_test_edit_view', False):
            return

        try:
            content = view.substr(Region(0, view.size()))
            source_view_id = view.settings().get('source_view_id')
            test_id = view.settings().get('test_id')

            parts = content.split("\n--- EXPECTED OUTPUT --- (Do not delete this line)\n")
            input_part = parts[0]
            expected_output = parts[1] if len(parts) > 1 else ''

            input_data = input_part.split("--- INPUT --- (Do not delete this line)\n", 1)[1]

            for window in sublime.windows():
                for v in window.views():
                    if v.id() == source_view_id:
                        v.run_command('test_manager', {
                            'action': 'set_test_data',
                            'id': test_id,
                            'test': input_data,
                            'correct_answer': expected_output
                        })
                        return
        except Exception as e:
            print("[FastOlympicCoding] Error saving edited test case: {}".format(e))