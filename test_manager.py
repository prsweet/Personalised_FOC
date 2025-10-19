import sublime, sublime_plugin
import os
from subprocess import Popen, PIPE
from sublime import Region, Phantom, PhantomSet
import time
import re

from .Modules.ProcessManager import ProcessManager
from .settings import base_name, get_settings, get_tests_file_path, root_dir


class TestManagerCommand(sublime_plugin.TextCommand):
    def __init__(self, view):
        self.view = view
        self.tester = None
        self.session = None
        self.test_phantoms = []
        self.is_running_all = False
        self.run_all_index = 0

    class Test(object):
        def __init__(self, prop):
            if isinstance(prop, str):
                self.test_string = prop
                self.correct_answers = set()
            else:
                self.test_string = prop.get('test', '')
                self.correct_answers = set(prop.get('correct_answers', []))

            self.fold = True
            self.runtime = '-'
            self.rtcode = None
            self.timed_out = False 

        def is_correct_answer(self, answer):
            def normalize(text):
                return '\n'.join(line.strip() for line in text.strip().splitlines())

            if not self.correct_answers:
                return None
            
            normalized_answer = normalize(answer)
            return any(normalize(ans) == normalized_answer for ans in self.correct_answers)

        def set_cur_runtime(self, runtime): self.runtime = runtime
        def set_cur_rtcode(self, rtcode): self.rtcode = rtcode

        def get_nice_runtime(self):
            if isinstance(self.runtime, str): return self.runtime
            return "{}ms".format(self.runtime)

        def memorize(self):
            return {'test': self.test_string, 'correct_answers': list(self.correct_answers)}

    class Tester(object):
        def __init__(self, process_manager, on_stop, sync_out=False, tests=[]):
            self.process_manager = process_manager
            self.sync_out = sync_out
            self.tests = tests
            self.running_test = None
            self.on_stop = on_stop
            self.proc_run = False
            self.prog_out = [''] * len(tests)
            self.user_initiated_stop = False

        def __on_stop(self, rtcode, runtime=-1, crash_line=None, timed_out=False):
            if not self.proc_run: return
            if self.running_test is None or self.running_test >= len(self.prog_out): return
            
            try:
                s = self.process_manager.read()
                if s: self.__on_out(s)
            except: pass
            
            self.prog_out[self.running_test] = self.prog_out[self.running_test].rstrip()
            self.proc_run = False
            self.on_stop(rtcode, runtime, crash_line=crash_line, timed_out=timed_out)

        def __on_out(self, s):
            n = self.running_test
            if n is None or n >= len(self.prog_out): return
            self.prog_out[n] += s

        def __process_listener(self):
            proc = self.process_manager
            start_time = time.time()
            timed_out = False
            
            timeout_duration = get_settings().get('stress_time_limit_seconds', 4.0)
            
            while proc.is_stopped() is None:
                if time.time() - start_time > timeout_duration:
                    proc.terminate()
                    timed_out = True
                    break

                s = proc.read(bfsize=4096)
                if s:
                    self.__on_out(s)
                else:
                    time.sleep(0.01)

            if self.user_initiated_stop:
                return

            runtime = int((time.time() - start_time) * 1000)
            self.__on_stop(proc.is_stopped(), runtime, timed_out=timed_out)

        # In Tester.run_test, ensure newline and close stdin after writing
        def run_test(self, id, compile_first=True):
            if compile_first:
                cmp_data = self.process_manager.compile()
                if cmp_data and cmp_data[0] != 0:
                    self.__on_stop(cmp_data[0])
                    return

            self.running_test = id
            self.prog_out[id] = ''
            self.proc_run = True
            self.process_manager.run()
            
            inp = self.tests[id].test_string or ""
            if not inp.endswith("\n"):
                inp += "\n"
            self.process_manager.write(inp)
            # important: finish input so program knows no more data coming
            self.process_manager.finish_input()

            sublime.set_timeout_async(self.__process_listener, 0)

        def get_tests(self):
            return self.tests
            
        def terminate(self): 
            if not self.proc_run: return
            
            self.user_initiated_stop = True
            self.process_manager.terminate()
            self.__on_stop(rtcode='ABORTED', runtime=-1)
            self.user_initiated_stop = False

    def on_test_action(self, i, event):
        tester = self.tester
        is_busy = tester.proc_run or self.is_running_all
        
        if event == 'test-stop':
            tester.terminate()
            return
            
        if is_busy and event in {'test-edit', 'test-run', 'test-delete', 'new-test', 'run-all-tests'}:
            sublime.status_message('Cannot perform action while a process is running')
            return

        if event == 'test-click':
            tester.tests[i].fold = not tester.tests[i].fold
            self.update_configs()
        elif event == 'test-edit':
            v = self.view
            edit_view = v.window().new_file()
            edit_view.run_command('test_edit', {
                'action': 'init', 'test_id': i, 'test': tester.tests[i].test_string,
                'correct_answer': next(iter(tester.tests[i].correct_answers), ""),
                'source_view_id': v.id()
            })
        elif event == 'test-delete':
            if sublime.ok_cancel_dialog("Are you sure you want to delete Case {}?".format(i + 1)):
                del self.tester.tests[i]
                del self.tester.prog_out[i]
                self.memorize_tests()
                self.update_configs()
        elif event == 'test-run': self.run_single_test(i)
        elif event == 'new-test': self.new_test(self.view.window().active_view().id())
        elif event == 'run-all-tests': self.run_all_tests()

    def stop_all_tests(self):
        if not self.is_running_all:
            return

        self.is_running_all = False
        if self.tester and self.tester.proc_run:
            self.tester.terminate()
        else:
            self.update_configs()

    def on_footer_action(self, event):
        if event == 'stop-all-tests':
            self.stop_all_tests()
        else:
            self.on_test_action(i=-1, event=event)

    def _execute_test(self, i, compile_first):
        test = self.tester.tests[i]
        test.fold = False
        test.timed_out = False 
        self.tester.run_test(i, compile_first=compile_first)

    def run_single_test(self, i):
        self.prepare_code_view()
        self._execute_test(i, compile_first=True)

    def set_test_data(self, id=None, test=None, correct_answer=None):
        if test is not None: self.tester.tests[id].test_string = test
        if correct_answer is not None: self.tester.tests[id].correct_answers = {correct_answer}
        self.update_configs()
        self.memorize_tests()

    def get_footer_buttons(self):
        has_tests = len(self.tester.tests) > 0
        is_any_process_running = self.is_running_all or (self.tester and self.tester.proc_run)
        
        run_all_button = ''
        if has_tests:
            if self.is_running_all:
                run_all_button = '<a href="stop-all-tests" class="button stop">Stop</a>'
            else:
                disabled_class = "disabled" if is_any_process_running else ""
                run_all_button = '<a href="run-all-tests" class="button {0}">Run All</a>'.format(disabled_class)

        new_case_disabled_class = "disabled" if is_any_process_running else ""
        
        styles = """
        .footer-buttons { display: flex; gap: 10px; margin-top: 10px; padding: 5px 0; }
        .footer-buttons .button { flex-grow: 1; text-align: center; background-color: color(var(--foreground) a(0.1)); border-radius: 3px; padding: 8px; text-decoration: none; color: var(--foreground); }
        .footer-buttons .button:hover { background-color: color(var(--foreground) a(0.2)); }
        .footer-buttons .button.disabled { background-color: color(var(--bluish) a(0.3)) !important; color: color(var(--foreground) a(0.8)) !important; pointer-events: none; }
        .footer-buttons .button.stop { background-color: color(var(--redish) a(0.7)); }
        .footer-buttons .button.stop:hover { background-color: color(var(--redish) a(0.9)); color: white; }
        """
        html = """
        <body id="foc-body">
            <div class="footer-buttons">
                <a href="new-test" class="button {0}">New Case</a>
                {1}
            </div>
        </body>
        """.format(new_case_disabled_class, run_all_button)
        full_content = '<style>' + styles + '</style>' + html
        return Phantom(Region(self.view.size()), full_content, sublime.LAYOUT_BLOCK, self.on_footer_action)

    def update_configs(self):
        v = self.view
        tester = self.tester
        
        if v.settings().get('edit_mode') or not tester: return
        
        styles = """
        body#foc-body { background-color: transparent; margin: 0; padding: 2px 0; font-family: var(--font_face); }
        .test-config { 
            border: 1px solid color(var(--foreground) a(0.2)); 
            border-radius: 5px; 
            padding: 10px; 
            margin-bottom: 8px; 
            background-color: color(var(--foreground) a(0.05)); 
        }
        .test-config.passed { background-color: color(var(--greenish) a(0.1)); border-color: color(var(--greenish) a(0.4)); }
        .test-config.wrong { background-color: color(var(--redish) a(0.1)); border-color: color(var(--redish) a(0.4)); }
        .test-config.error { background-color: color(var(--orangish) a(0.1)); border-color: color(var(--orangish) a(0.4)); }
        .header { display: flex; align-items: center; gap: 10px; }
        .test-name { font-weight: bold; margin-right: auto; }
        .toggle-arrow { text-decoration: none; color: var(--foreground); font-weight: bold; }
        .icon-button { background-color: color(var(--foreground) a(0.1)); border-radius: 3px; padding: 2px 8px; text-decoration: none; color: var(--foreground); }
        .icon-button:hover { background-color: color(var(--foreground) a(0.2)); }
        .icon-button.delete:hover { background-color: color(var(--redish) a(0.8)); color: white; }
        .icon-button.stop { background-color: color(var(--redish) a(0.7)); }
        .icon-button.stop:hover { background-color: color(var(--redish) a(0.9)); color: white; }
        .icon-button.disabled { background-color: color(var(--bluish) a(0.3)) !important; color: color(var(--foreground) a(0.8)) !important; pointer-events: none; }
        .runtime { font-style: italic; color: color(var(--foreground) a(0.6)); }
        .data-block { margin-top: 12px; }
        .data-block label { font-weight: bold; color: color(var(--foreground) a(0.7)); display: block; margin-bottom: 4px;}
        .data-block pre { background-color: color(var(--background) a(0.5)); padding: 8px; border-radius: 3px; margin: 0; white-space: pre-wrap; word-wrap: break-word; font-family: var(--font_face); font-size: 0.9rem;}
        .status-text { font-weight: bold; }
        """

        configs = []
        pt = 0
        is_busy = tester.proc_run or self.is_running_all
        disabled_class = "disabled" if is_busy else ""

        for i in range(len(tester.tests)):
            test = tester.tests[i]
            running_this_test = tester.proc_run and i == tester.running_test
            
            status_text, status_color = "", "var(--foreground)"
            container_class = "" 

            if i >= len(tester.prog_out):
                is_correct = None
            else:
                is_correct = test.is_correct_answer(tester.prog_out[i])

            if running_this_test:
                status_text, status_color = "Running...", "var(--bluish)"
            elif self.is_running_all and test.rtcode is None:
                status_text, status_color = "Queued...", "var(--foreground)"
            elif test.timed_out:
                status_text, status_color = "Time Limit Exceeded", "var(--orangish)"
                container_class = "error" 
            elif test.rtcode is not None:
                if str(test.rtcode) == 'ABORTED':
                    status_text, status_color = "Stopped by user", "var(--orangish)"
                elif str(test.rtcode) != '0':
                    status_text, status_color = "Runtime Error", "var(--orangish)"
                    container_class = "error" 
                elif is_correct is True:
                    status_text, status_color = "Passed", "var(--greenish)"
                    container_class = "passed" 
                elif is_correct is False:
                    status_text, status_color = "Wrong Answer", "var(--redish)"
                    container_class = "wrong" 

            action_buttons = ''
            if running_this_test:
                action_buttons = '<a href="test-stop" class="icon-button stop">Stop</a>'
            else:
                action_buttons = """
                    <a href="test-run" class="icon-button {disabled_class}">Run</a>
                    <a href="test-edit" class="icon-button {disabled_class}">Edit</a>
                    <a href="test-delete" class="icon-button delete {disabled_class}">Delete</a>
                """.format(disabled_class=disabled_class)

            my_output_text = tester.prog_out[i] if i < len(tester.prog_out) else ""

            html_data = {
                'container_class': container_class,
                'test_id': i + 1, 'status_text': status_text, 'status_color': status_color,
                'runtime': test.get_nice_runtime(),
                'input_data': (sublime.html.escape(test.test_string, quote=False) or "&nbsp;").replace('\n', '<br>'),
                'my_output': (sublime.html.escape(my_output_text, quote=False) or "&nbsp;").replace('\n', '<br>'),
                'expected_output': (sublime.html.escape(next(iter(test.correct_answers), ""), quote=False) or "&nbsp;").replace('\n', '<br>'),
                'action_buttons': action_buttons
            }

            if test.fold and status_text:
                html_template = """
                <body id="foc-body">
                    <div class="test-config {container_class}">
                        <div class="header">
                            <a href="test-click" class="toggle-arrow">▶</a>
                            <span class="test-name">Case {test_id}</span>
                            <span class="status-text" style="color: {status_color};">{status_text}</span>
                            <span class="runtime">({runtime})</span>
                            {action_buttons}
                        </div>
                    </div>
                </body>"""
            else:
                html_template = """
                <body id="foc-body">
                    <div class="test-config {container_class}">
                        <div class="header">
                            <a href="test-click" class="toggle-arrow">▼</a>
                            <span class="test-name">Case {test_id}</span>
                            <span class="status-text" style="color: {status_color};">{status_text}</span>
                            <span class="runtime">({runtime})</span>
                            {action_buttons}
                        </div>
                        <div class="body">
                            <div class="data-block"><label>Input:</label><br><pre>{input_data}</pre><br></div>
                            <div class="data-block"><label>Expected Output:</label><br><pre>{expected_output}</pre><br></div>
                            <div class="data-block"><label>Your Output:</label><br><pre>{my_output}</pre><br></div>
                        </div>
                    </div>
                </body>"""
            
            content = html_template.format(**html_data)
            full_content = '<style>' + styles + '</style>' + content
            configs.append(Phantom(Region(pt), full_content, sublime.LAYOUT_BLOCK, lambda event, i=i: self.on_test_action(i, event)))
            pt += 1

        configs.append(self.get_footer_buttons())

        v.run_command('test_manager', {'action': 'erase_all'})
        v.run_command('append', {'characters': '\n' * (len(tester.tests) + 1)})

        while len(self.test_phantoms) < len(configs):
            self.test_phantoms.append(PhantomSet(v, 'test-phantom-' + str(len(self.test_phantoms))))
        
        for i in range(len(configs)):
            self.test_phantoms[i].update([configs[i]])
        for i in range(len(configs), len(self.test_phantoms)):
            self.test_phantoms[i].update([])

    def new_test(self, edit):
        self.tester.tests.append(self.Test(''))
        self.tester.prog_out.append('')
        self.memorize_tests() 
        self.update_configs()
        self.on_test_action(len(self.tester.tests) - 1, 'test-edit')
    
    def memorize_tests(self):
        if not hasattr(self, 'dbg_file'): return
        with open(get_tests_file_path(self.dbg_file), 'w') as f:
            f.write(sublime.encode_value([x.memorize() for x in self.tester.get_tests()], True))

    def on_stop(self, rtcode, runtime, crash_line=None, timed_out=False):
        test_id = self.tester.running_test
        if test_id is None or test_id >= len(self.tester.tests):
            if not self.is_running_all:
                self.update_configs()
            return 

        test = self.tester.tests[test_id]
        test.set_cur_runtime(runtime)
        test.set_cur_rtcode(rtcode)
        test.timed_out = timed_out
        
        is_correct = test.is_correct_answer(self.tester.prog_out[test_id])
        if not timed_out and str(rtcode) == '0' and is_correct is True:
            test.fold = True
        
        self.memorize_tests()

        if self.is_running_all:
            self.run_all_index += 1
            if self.run_all_index < len(self.tester.tests):
                self.update_configs()
                self._execute_test(self.run_all_index, compile_first=False)
            else:
                self.is_running_all = False
                self.update_configs()
        else:
             self.update_configs()
        
        if crash_line is not None:
            code_view = self.get_view_by_id(self.code_view_id)
            if code_view:
                code_view.run_command('view_tester', {'action': 'show_crash_line', 'crash_line': crash_line})

    def clear_all(self):
        v = self.view
        v.run_command('test_manager', {'action': 'erase_all'})
        v.sel().clear()
        v.sel().add(Region(v.size(), v.size()))
        for phs in self.test_phantoms: phs.update([])

    def prepare_code_view(self):
        code_view = self.get_view_by_id(self.code_view_id)
        if code_view and code_view.is_dirty(): code_view.run_command('save')

    def get_view_by_id(self, view_id):
        for window in sublime.windows():
            for view in window.views():
                if view.id() == view_id: return view
        return None

    def make_opd(self, edit, run_file=None, build_sys=None, clr_tests=False, \
        sync_out=False, code_view_id=None, use_debugger=False, load_session=False):
        v = self.view
        if hasattr(self, 'tester') and self.tester and self.tester.proc_run:
            self.tester.terminate()
            kwargs = {'action': 'make_opd', 'run_file': run_file, 'build_sys': build_sys, 'clr_tests': clr_tests, 'sync_out': sync_out, 'code_view_id': code_view_id, 'use_debugger': use_debugger, 'load_session': load_session}
            sublime.set_timeout_async(lambda: v.run_command('test_manager', kwargs), 30)
            return

        v.set_scratch(True)
        v.set_status('opd_info', 'opdebugger-file')
        self.clear_all()

        self.session = {'run_file': run_file, 'build_sys': build_sys, 'clr_tests': clr_tests, 'sync_out': sync_out, 'code_view_id': code_view_id, 'use_debugger': use_debugger}
        self.dbg_file = run_file
        self.code_view_id = code_view_id

        self.prepare_code_view()
        if not v.settings().get('word_wrap'): v.run_command('toggle_setting', {'setting': 'word_wrap'})

        try:
            tests_path = get_tests_file_path(run_file)
            if not clr_tests and os.path.exists(tests_path):
                with open(tests_path) as f:
                    tests_data = f.read()
                    tests = [self.Test(x) for x in sublime.decode_value(tests_data)] if tests_data else []
            else:
                if clr_tests and os.path.exists(tests_path):
                    os.remove(tests_path)
                tests = []
        except:
            tests = []

        process_manager = ProcessManager(run_file, build_sys, run_settings=get_settings().get('run_settings'))
        
        def compile_and_run():
            cmp_data = process_manager.compile()
            if cmp_data is None or cmp_data[0] == 0:
                self.tester = self.Tester(process_manager, self.on_stop, tests=tests, sync_out=sync_out)
                self.update_configs()
            else:
                v.run_command('test_manager', {'action': 'erase_all'})
                v.run_command('append', {'characters': '\nCompilation Error:\n' + cmp_data[1]})

        sublime.set_timeout_async(compile_and_run, 10)

    def run_all_tests(self):
        if not self.tester or self.tester.proc_run or self.is_running_all: return
        
        self.prepare_code_view()

        self.tester.prog_out = [''] * len(self.tester.tests)
        
        for test in self.tester.tests:
            test.set_cur_rtcode(None)
            test.set_cur_runtime('-')
            test.timed_out = False
        
        self.is_running_all = True
        self.update_configs()

        def start_test_sequence():
            cmp_data = self.tester.process_manager.compile()
            if cmp_data and cmp_data[0] != 0:
                self.is_running_all = False
                self.update_configs()
                sublime.error_message("Compilation Failed:\n" + cmp_data[1])
                return

            self.run_all_index = 0
            if self.run_all_index < len(self.tester.tests):
                self._execute_test(self.run_all_index, compile_first=False)
            else:
                self.is_running_all = False
                self.update_configs()
        
        sublime.set_timeout_async(start_test_sequence, 50)

    def run(self, edit, **kwargs):
        action = kwargs.get('action')
        self.view.set_read_only(False)
        
        if action == 'make_opd': self.make_opd(edit, **{k:v for k,v in kwargs.items() if k!='action'})
        elif action == 'new_test': self.new_test(edit)
        elif action == 'run_all_tests': self.run_all_tests()
        elif action == 'set_test_data': self.set_test_data(id=kwargs['id'], test=kwargs.get('test'), correct_answer=kwargs.get('correct_answer'))
        elif action == 'erase_all': self.view.replace(edit, Region(0, self.view.size()), '')
        
class ViewTesterCommand(sublime_plugin.TextCommand):
    def create_opd(self, clr_tests=False, sync_out=True, use_debugger=False):
        v = self.view
        if v.is_dirty(): v.run_command('save')
        file_syntax = v.scope_name(v.sel()[0].begin()).rstrip().split()[0]
        window = v.window()
        
        dbg_view = next((view for view in window.views() if view.settings().get('is_opd_view')), None)

        if not dbg_view:
            dbg_view = window.new_file()
            dbg_view.settings().set('is_opd_view', True)
            if get_settings().get('close_sidebar'):
                try: sublime.set_timeout_async(lambda: window.set_sidebar_visible(False), 50)
                except: pass
            dbg_view.run_command('toggle_setting', {'setting': 'word_wrap'})

        if len(window.get_layout().get('cols', [])) < 2:
            window.set_layout({'cols': [0, 0.6, 1], 'rows': [0, 1], 'cells': [[0, 0, 1, 1], [1, 0, 2, 1]]})
        
        window.set_view_index(dbg_view, window.get_view_index(v)[0] + 1, 0)
        window.focus_view(v)
        window.focus_view(dbg_view)

        dbg_view.set_name(os.path.basename(v.file_name()) + ' - run')
        dbg_view.run_command('test_manager', {
            'action': 'make_opd', 'build_sys': file_syntax, 'run_file': v.file_name(),
            'clr_tests': clr_tests, 'sync_out': sync_out, 'code_view_id': v.id(),
            'use_debugger': use_debugger
        })
    
    def run(self, edit, **kwargs):
        action = kwargs.get('action')
        if action == 'make_opd':
            self.create_opd(clr_tests=kwargs.get('clr_tests', False), sync_out=kwargs.get('sync_out', True), use_debugger=kwargs.get('use_debugger', False))
        elif action == 'show_crash_line':
            pt = self.view.text_point(kwargs['crash_line'] - 1, 0)
            self.view.erase_regions('crash_line')
            self.view.add_regions('crash_line', [sublime.Region(pt, pt)], 'string', 'dot', sublime.DRAW_SOLID_UNDERLINE | sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE)
            sublime.set_timeout_async(lambda pt=pt: self.view.show_at_center(pt), 50)

class TestEditCommand(sublime_plugin.TextCommand):
    def run(self, edit, **kwargs):
        action = kwargs.get('action')
        if action == 'init':
            self.view.settings().set('test_id', kwargs['test_id'])
            self.view.settings().set('source_view_id', kwargs['source_view_id'])
            
            test_input = kwargs.get('test', '')
            correct_answer = kwargs.get('correct_answer', '')
            content = "--- INPUT ---\n{0}\n\n--- EXPECTED OUTPUT ---\n{1}".format(test_input, correct_answer)
            
            self.view.insert(edit, 0, content)
            self.view.set_name("Edit Test Case {}".format(kwargs['test_id'] + 1))
            self.view.set_scratch(True)

class TestEvents(sublime_plugin.EventListener):
    def on_close(self, view):
        if not view.name().startswith("Edit Test Case"): return

        test_id = view.settings().get('test_id')
        source_view_id = view.settings().get('source_view_id')
        
        if test_id is None or source_view_id is None: return

        source_view = next((v for w in sublime.windows() for v in w.views() if v.id() == source_view_id), None)
        if not source_view: return

        content = view.substr(sublime.Region(0, view.size()))

        # Allow flexible spacing around separators
        m = re.split(r'\n\s*---\s*EXPECTED\s+OUTPUT\s*---\s*\n', content, maxsplit=1)
        input_part = m[0].lstrip()
        # Remove leading marker if present
        if input_part.startswith("--- INPUT ---"):
            input_part = input_part.replace("--- INPUT ---", "", 1).lstrip('\n')
        output_part = m[1] if len(m) > 1 else ""
        # strip only trailing single newline but preserve intentional formatting
        input_part = input_part.rstrip('\n')
        output_part = output_part.rstrip('\n')

        source_view.run_command('test_manager', {
            'action': 'set_test_data',
            'id': test_id,
            'test': input_part,
            'correct_answer': output_part
        })