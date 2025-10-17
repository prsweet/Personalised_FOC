# File: test_manager.py
# This is the final, complete, and correct file with all functions restored.

import sublime, sublime_plugin
import os
from os.path import dirname
import sys
from subprocess import Popen, PIPE
import subprocess
import shlex
from sublime import Region, Phantom, PhantomSet
from os import path
from importlib import import_module
from time import time
import threading

from .Modules.ProcessManager import ProcessManager
from .settings import base_name, get_settings, root_dir, get_tests_file_path
from .debuggers import debugger_info
from .ContestHandlers import handler_info
from .Highlight.CppVarHighlight import highlight
from .Highlight.test_interface import get_test_styles


class TestManagerCommand(sublime_plugin.TextCommand):
	BEGIN_TEST_STRING = 'Test %d {'
	OUT_TEST_STRING = ''
	END_TEST_STRING = '} rtcode %s'
	REGION_BEGIN_KEY = 'test_begin_%d'
	REGION_OUT_KEY = 'test_out_%d'
	REGION_END_KEY = 'test_end_%d'
	REGION_POS_PROP = ['', '', sublime.HIDDEN]
	REGION_ACCEPT_PROP = ['string', 'dot', sublime.HIDDEN]
	REGION_DECLINE_PROP = ['variable.c++', 'dot', sublime.HIDDEN]
	REGION_UNKNOWN_PROP = ['text.plain', 'dot', sublime.HIDDEN]
	REGION_OUT_PROP = ['entity.name.function.opd', 'bookmark', sublime.HIDDEN]
	REGION_BEGIN_PROP = ['string', 'Packages/' + base_name + '/icons/arrow_right.png', \
				sublime.DRAW_NO_FILL | sublime.DRAW_STIPPLED_UNDERLINE | \
					sublime.DRAW_NO_OUTLINE | sublime.DRAW_EMPTY_AS_OVERWRITE]
	REGION_END_PROP = ['variable.c++', 'Packages/' + base_name + '/icons/arrow_left.png', sublime.HIDDEN]
	REGION_LINE_PROP = ['string', 'dot', \
				sublime.DRAW_NO_FILL | sublime.DRAW_STIPPLED_UNDERLINE | \
					sublime.DRAW_NO_OUTLINE | sublime.DRAW_EMPTY_AS_OVERWRITE]

	def __init__(self, view):
		self.view = view
		self.use_debugger = False
		self.delta_input = 0
		self.tester = None
		self.session = None
		self.phantoms = PhantomSet(view, 'test-phantoms')
		self.test_phantoms = [PhantomSet(view, 'test-phantoms-' + str(i)) for i in range(20)]
		self.out_region_set = False
		self.is_running_all = False
		self.run_all_index = 0

	class Test(object):
		def __init__(self, prop, start=None, end=None):
			super(TestManagerCommand.Test, self).__init__()
			if type(prop) == str:
				self.test_string = prop
				self.correct_answers = set()
				self.uncorrect_answers = set()
			else:
				self.test_string = prop['test']
				self.correct_answers = set(prop.get('correct_answers', set()))
				self.uncorrect_answers = set(prop.get('uncorrect_answers', set()))

			self.start = start
			self.fold = True
			self.shrunk = bool(self.correct_answers) 
			self.end = end
			self.runtime = '-'
			self.rtcode = None 
			self.tie_pos = 0

		def add_correct_answer(self, answer):
			self.correct_answers.add(answer.lstrip().rstrip())

		def add_uncorrect_answer(self, answer):
			self.uncorrect_answers.add(answer.lstrip().rstrip())

		def remove_correct_answer(self, answer):
			answer = answer.lstrip().rstrip()
			if answer in self.correct_answers:
				self.correct_answers.remove(answer)

		def remove_uncorrect_answer(self, answer):
			answer = answer.lstrip().rstrip()
			if answer in self.uncorrect_answers:
				self.uncorrect_answers.remove(answer)

		def is_correct_answer(self, answer):
			answer = answer.rstrip().lstrip()
			if not self.correct_answers: 
				return None
			if answer in self.correct_answers:
				return True
			if answer in self.uncorrect_answers:
				return False
			return False 

		def append_string(self, s):
			self.test_string += s

		def set_inner_range(self, start, end):
			self.start = start
			self.end = end

		def set_tie_pos(self, pos):
			self.tie_pos = pos

		def set_cur_runtime(self, runtime):
			self.runtime = runtime

		def set_cur_rtcode(self, rtcode):
			self.rtcode = rtcode

		def get_nice_runtime(self):
			if isinstance(self.runtime, str):
				return self.runtime
			runtime = self.runtime
			if runtime < 5000:
				return '&nbsp;' * (2 - len(str(self.runtime))) + str(runtime) + 'ms'
			else:
				return str(runtime // 1000) + 's'

		def get_config(self, i, pt, _cb_act, _out, view, running=False):	
			styles = get_test_styles(view)
			is_passed = self.is_correct_answer(_out) and str(self.rtcode) == '0'
			
			def onclick(event, cb=_cb_act, i=i):
				_cb_act(i, event)

			if is_passed and self.shrunk:
				html_template = """
				<body id="foc-body" class="passed shrunk">
					<div class="test-config test-accept">
						<a href="test-click" class="test-name">Test {test_id} Passed ✅</a>
						<span class="runtime">{runtime}</span>
						<a href="test-run" class="icon">⟳</a>
						<a href="test-edit" class="icon">✎</a>
					</div>
				</body>
				"""
				content = html_template.format(test_id=i, runtime=self.get_nice_runtime())
				content = '<style>' + styles + '</style>' + content
				return Phantom(Region(pt), content, sublime.LAYOUT_BLOCK, onclick)

			if not running and not self.fold:
				is_correct = self.is_correct_answer(_out)
				status_class = "test-unknown"
				status_text = "Status Unknown"

				if str(self.rtcode) != '0' and self.rtcode is not None:
					status_class = "test-decline"
					status_text = "Runtime Error"
				elif is_correct is True:
					status_class = "test-accept"
					status_text = "Passed"
				elif is_correct is False:
					status_class = "test-decline"
					status_text = "Wrong Answer"
				
				expected_output = next(iter(self.correct_answers), "N/A")
				
				html_template = open(root_dir + '/Highlight/test_display.html').read()
				content = html_template.format(
					status_class=status_class,
					status_text=status_text,
					runtime=self.get_nice_runtime(),
					input_data=_out.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'),
					my_output=_out.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'),
					expected_output=expected_output.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
				)
				return Phantom(Region(pt), content, sublime.LAYOUT_BLOCK, onclick)

			if not running:
				content = open(root_dir + '/Highlight/test_config.html').read()
				test_type = ''
				if is_passed:
					test_type = 'test-accept'
				elif str(self.rtcode) != '0' and self.rtcode is not None:
					test_type = 'test-decline'
				elif self.is_correct_answer(_out) is False:
					test_type = 'test-decline'

				content = content.format(
					test_id=i,
					runtime=self.get_nice_runtime(),
					test_type=test_type
				)
				content = '<style>' + styles + '</style>' + content
				return Phantom(Region(pt), content, sublime.LAYOUT_BLOCK, onclick)
			else:
				content = open(root_dir + '/Highlight/test_running.html').read()
				content = content.format(test_id=i)
				content = '<style>' + styles + '</style>' + content
				return Phantom(Region(pt), content, sublime.LAYOUT_BLOCK, onclick)

		def memorize(self):
			d = {'test': self.test_string}
			if self.correct_answers:
				d['correct_answers'] = list(self.correct_answers)
			if self.uncorrect_answers:
				d['uncorrect_answers'] = list(self.uncorrect_answers)
			return d

		def __str__(self):
			return self.test_string

	class Tester(object):
		def __init__(self, process_manager, \
			on_insert, on_out, on_stop, on_status_change, \
			sync_out=False, tests=[]):
			super(TestManagerCommand.Tester, self).__init__()
			self.process_manager = process_manager
			self.sync_out = sync_out
			self.tests = tests
			self.test_iter = 0
			self.running_test = None
			self.running_new = None
			self.on_insert = on_insert
			self.on_out = on_out
			self.on_stop = on_stop
			self.proc_run = False
			self.prog_out = [''] * len(self.tests)
			self.on_status_change = on_status_change
			if type(self.process_manager) != ProcessManager:
				self.process_manager.set_calls(self.__on_out, self.__on_stop, on_status_change)

		def __on_stop(self, rtcode, runtime=-1, crash_line=None):
			if self.running_test is None or self.running_test >= len(self.prog_out): return
			self.prog_out[self.running_test] = self.prog_out[self.running_test].rstrip()
			self.proc_run = False

			if self.running_new:
				self.test_iter += 1

			if type(self.process_manager) == ProcessManager:
				self.on_status_change('STOPPED')

			self.on_stop(rtcode, runtime, crash_line=crash_line)

		def __on_out(self, s):
			n = self.running_test
			if n is None or n >= len(self.prog_out): return
			self.prog_out[n] += s
			self.on_out(s)

		def __process_listener(self):
			proc = self.process_manager
			start_time = time()
			while proc.is_stopped() is None:
				if self.sync_out:
					s = proc.read(bfsize=1)
				else:
					s = proc.read()
				self.__on_out(s)
			try:
				s = proc.read()
				self.__on_out(s)
			except:
				'output already putted'
			runtime = int((time() - start_time) * 1000)
			self.__on_stop(proc.is_stopped(), runtime)

		def insert(self, s, call_on_insert=False):
			n = self.running_test
			if self.proc_run:
				self.tests[n].append_string(s)
				self.process_manager.write(s)
				if call_on_insert:
					self.on_insert(s)

		def insert_test(self, id=None):
			if id is None:
				id = self.test_iter
			tests = self.tests

			if type(self.process_manager) == ProcessManager:
				self.on_status_change('RUNNING')
				
			self.proc_run = True
			self.process_manager.run()
			self.process_manager.write(tests[id].test_string)
			self.on_insert(tests[id].test_string)

		def next_test(self, tie_pos, cb):
			n = self.test_iter
			tests = self.tests
			prog_out = self.prog_out

			if self.proc_run:
				sublime.status_message('process already running')
				return

			if n >= len(tests):
				tests.append(TestManagerCommand.Test(''))
			if n >= len(prog_out):
				prog_out.append('')
			tests[n].set_tie_pos(tie_pos)
			self.running_test = n
			self.running_new = True

			def go(self=self, cb=cb):
				self.insert_test()
				if type(self.process_manager) == ProcessManager:
					sublime.set_timeout_async(self.__process_listener)
				cb()

			sublime.set_timeout_async(go, 10)

		def run_test(self, id):
			tests = self.tests
			process_manager = self.process_manager
			self.on_status_change('COMPILE')
			process_manager.compile()
			self.running_test = id
			self.running_new = False
			self.prog_out[id] = ''
			self.insert_test(id)
			if type(self.process_manager) == ProcessManager:
				sublime.set_timeout_async(self.__process_listener)

		def have_pretests(self):
			n = self.test_iter
			tests = self.tests
			return n < len(tests)

		def get_tests(self):
			return self.tests
			
		def terminate(self):
			self.process_manager.terminate()

	def open_test_edit(self, i):
		v = self.view
		tester = self.tester
		v.window().focus_group(1)
		edit_view = v.window().new_file()
		v.window().set_view_index(edit_view, 1, 1)
		edit_view.run_command('test_edit', {
			'action': 'init',
			'test_id': i,
			'test': tester.tests[i].test_string,
			'source_view_id': v.id()
		})

	def on_test_action(self, i, event):
		v = self.view
		tester = self.tester
		
		is_passed = tester.tests[i].is_correct_answer(tester.prog_out[i]) and str(tester.tests[i].rtcode) == '0'

		if event == 'test-click':
			if is_passed:
				tester.tests[i].shrunk = not tester.tests[i].shrunk
			
			tester.tests[i].fold = not tester.tests[i].fold
			self.update_configs()
			return
		
		if (tester.proc_run or self.is_running_all) and event in {'test-edit', 'test-run'}:
			sublime.status_message('can not {action} while process running'.format(action=event))
			return

		if event == 'test-edit':
			self.open_test_edit(i)
		elif event == 'test-stop':
			tester.terminate()
		elif event == 'test-run':
			self.run_single_test(i)

	def run_single_test(self, i):
		tester = self.tester
		
		self.input_start = self.tester.tests[i].tie_pos + 1
		self.delta_input = self.input_start

		self.view.add_regions('type', [Region(self.input_start)], *self.REGION_BEGIN_PROP)
		self.view.sel().clear()
		self.view.sel().add(Region(self.input_start))
		self.prepare_code_view()
		tester.run_test(i)

	def set_test_input(self, test=None, id=None):
		self.tester.tests[id].test_string = test
		self.update_configs()
		self.memorize_tests()

	def get_next_title(self):
		v = self.view
		styles = get_test_styles(v) 
		content = open(root_dir + '/Highlight/test_next.html').read()
		content = '<style>' + styles + '</style>' + content

		def onclick(event, v=v):
			if event == 'run-all-tests':
				v.run_command('test_manager', {'action': 'run_all_tests'})
			else:
				v.run_command('test_manager', {'action': 'new_test'})

		phantom_content = content
		if get_settings().get('run_all_button_enabled', True):
			run_all_content = open(root_dir + '/Highlight/test_run_all.html').read()
			phantom_content += '<style>' + styles + '</style>' + run_all_content
		
		return Phantom(Region(self.view.size() - 1), phantom_content, sublime.LAYOUT_BLOCK, onclick)

	def update_configs(self):
		v = self.view
		tester = self.tester
		
		if v.settings().get('edit_mode'): return

		configs = []
		if not tester: return
		
		k = len(tester.tests)
		
		for i in range(k):
			running = (tester.proc_run or self.is_running_all) and i == tester.running_test
			
			pt = tester.tests[i].tie_pos

			config = tester.tests[i].get_config(
				i, pt, self.on_test_action, tester.prog_out[i], self.view, running=running
			)
			configs.append(config)

		if not tester.proc_run and not self.is_running_all:
			configs.append(self.get_next_title())

		while len(self.test_phantoms) < len(configs):
			self.test_phantoms.append(PhantomSet(v, 'test-phantom-' + str(len(self.test_phantoms))))

		hide_phantoms = v.settings().get('hide_phantoms')
		for i in range(len(configs)):
			self.test_phantoms[i].update([configs[i]] if not hide_phantoms else [])
		for i in range(len(configs), len(self.test_phantoms)):
			self.test_phantoms[i].update([])


	def new_test(self, edit):
		v = self.view
		self.tester.tests.append(self.Test(''))
		self.tester.prog_out.append('')
		self.tester.test_iter = len(self.tester.tests)
		self.update_configs()
		
		self.open_test_edit(len(self.tester.tests) - 1)
	
	def memorize_tests(self):
		if not hasattr(self, 'dbg_file'): return
		with open(get_tests_file_path(self.dbg_file), 'w') as f:
			f.write(sublime.encode_value([x.memorize() for x in (self.tester.get_tests())], True))

	def on_insert(self, s):
		self.view.run_command('test_manager', {'action': 'insert_opd_input', 'text': s})

	def on_out(self, s):
		self.view.run_command('test_manager', {'action': 'insert_opd_out', 'text': s})
		if not self.out_region_set:
			self.out_region_set = True
	
	def on_stop(self, rtcode, runtime, crash_line=None):
		v = self.view
		tester = self.tester

		test_id = self.tester.running_test
		self.tester.tests[test_id].set_cur_runtime(runtime)
		self.tester.tests[test_id].set_cur_rtcode(rtcode)
		v.erase_regions('type')

		is_passed_now = self.tester.tests[test_id].is_correct_answer(self.tester.prog_out[test_id]) and str(rtcode) == '0'
		if is_passed_now:
			self.tester.tests[test_id].shrunk = True
			self.tester.tests[test_id].fold = True
		else:
			self.tester.tests[test_id].shrunk = False
			self.tester.tests[test_id].fold = False
		
		self.update_configs()
		self.memorize_tests()

		if self.is_running_all:
			self.run_all_index += 1
			if self.run_all_index < len(tester.tests):
				sublime.set_timeout(lambda: self.run_single_test(self.run_all_index), 10)
			else:
				self.is_running_all = False
				self.update_configs()
		
		if crash_line is not None:
			for x in v.window().views():
				if x.id() == self.code_view_id:
					x.run_command('view_tester', {'action': 'show_crash_line', 'crash_line': crash_line})

	def clear_all(self):
		v = self.view
		v.run_command('test_manager', {'action': 'erase_all'})
		v.sel().clear()
		v.sel().add(Region(v.size(), v.size()))
		self.phantoms.update([])
		for phs in self.test_phantoms:
			phs.update([])

	def set_compile_bar(self, cmd, type=''):
		view = self.view
		if type == 'error':
			type = 'config-stop'

		styles = get_test_styles(view)
		content = open(root_dir + '/Highlight/compile.html').read().format(cmd=cmd, type=type)
		content = '<style>' + styles + '</style>' + content
		phantom = Phantom(Region(0), content, sublime.LAYOUT_BLOCK)
		self.test_phantoms[0].update([phantom])

	def get_view_by_id(self, id):
		for view in self.view.window().views():
			if view.id() == id:
				return view

	def prepare_code_view(self):
		code_view = self.get_view_by_id(self.code_view_id)
		if code_view:
			if code_view.is_dirty():
				code_view.run_command('save')

	def sync_read_only(self):
		view = self.view
		tester = self.tester

		err = True
		if tester and tester.proc_run:
			err = False
		
		view.set_read_only(err)

	def change_process_status(self, status):
		self.view.set_status('process_status', status)

	def make_opd(self, edit, run_file=None, build_sys=None, clr_tests=False, \
		sync_out=False, code_view_id=None, use_debugger=False, load_session=False):

		self.use_debugger = use_debugger
		v = self.view

		if v.get_status('process_status') == 'COMPILING': return
		if v.get_status('process_status') == 'RUNNING':
			self.tester.terminate()
			kwargs = {
				'run_file': run_file, 'build_sys': build_sys, 'clr_tests': clr_tests,
				'sync_out': sync_out, 'code_view_id': code_view_id,
				'use_debugger': use_debugger, 'load_session': load_session, 'action': 'make_opd'
			}
			sublime.set_timeout_async(lambda: v.run_command('test_manager', kwargs), 30)
			return

		v.set_scratch(True)
		v.run_command('set_setting', {'setting': 'fold_buttons', 'value': False})
		v.run_command('set_setting', {'setting': 'line_numbers', 'value': False})
		v.set_status('opd_info', 'opdebugger-file')
		self.clear_all()
		if load_session:
			if self.session is None:
				v.run_command('test_manager', {'action': 'insert_opd_out', 'text': 'Can\'t restore session'})
			else:
				run_file, build_sys, clr_tests, sync_out, code_view_id, use_debugger = (
					self.session['run_file'], self.session['build_sys'], self.session['clr_tests'],
					self.session['sync_out'], self.session['code_view_id'], self.session['use_debugger']
				)
		else:
			print('[FastOlympicCoding] session saved')
			self.session = {
				'run_file': run_file, 'build_sys': build_sys, 'clr_tests': clr_tests,
				'sync_out': sync_out, 'code_view_id': code_view_id, 'use_debugger': use_debugger
			}
			self.dbg_file = run_file
			self.code_view_id = code_view_id

		self.prepare_code_view()
		if not v.settings().get('word_wrap'): v.run_command('toggle_setting', {'setting': 'word_wrap'})

		try:
			if not clr_tests:
				with open(get_tests_file_path(run_file)) as f:
					tests = [self.Test(x) for x in sublime.decode_value(f.read())]
			else: raise FileNotFoundError
		except (FileNotFoundError, ValueError):
			if clr_tests:
				with open(get_tests_file_path(run_file), 'w') as f: f.write('[]')
			tests = []

		file_ext = path.splitext(run_file)[1][1:]
		self.change_process_status('COMPILING')
		DebugModule = debugger_info.get_best_debug_module(file_ext)
		if not self.use_debugger or DebugModule is None:
			process_manager = ProcessManager(
				run_file, build_sys, run_settings=get_settings().get('run_settings')
			)
		else:
			process_manager = DebugModule(run_file)

		def compile_and_run(self=self, v=v):
			cmp_data = process_manager.compile()
			self.change_process_status('COMPILED')
			self.delta_input = 0
			if cmp_data is None or cmp_data[0] == 0:
				self.tester = self.Tester(
					process_manager, self.on_insert, self.on_out, self.on_stop,
					self.change_process_status, tests=tests, sync_out=sync_out
				)
				v.settings().set('edit_mode', False)
				self.tester.test_iter = len(tests)
				self.update_configs()
			else:
				v.run_command('test_manager', {'action': 'insert_opd_out', 'text': '\n' + cmp_data[1]})
				self.set_compile_bar('compilation error', type='error')

		self.set_compile_bar('compiling')
		sublime.set_timeout_async(compile_and_run, 10)

	def delete_test(self, edit, id):
		if id < len(self.tester.tests):
			del self.tester.tests[id]
			if id < len(self.tester.prog_out):
				del self.tester.prog_out[id]
			self.tester.test_iter -= 1
			self.update_configs()
			self.memorize_tests()

	def run_all_tests(self):
		if self.tester.proc_run or self.is_running_all:
			sublime.status_message('process already running')
			return
		self.is_running_all = True
		self.run_all_index = 0
		if self.run_all_index < len(self.tester.tests):
			self.run_single_test(self.run_all_index)
		else:
			self.is_running_all = False

	def run(self, edit, **kwargs):
		v = self.view
		action = kwargs.get('action')
		v.set_read_only(False)
		
		if action == 'replace': v.replace(edit, Region(kwargs['region'][0], kwargs['region'][1]), kwargs['text'])
		elif action == 'erase': v.erase(edit, Region(kwargs['region'][0], kwargs['region'][1]))
		elif action == 'insert_opd_out':
			v.insert(edit, self.delta_input, kwargs['text'])
			self.delta_input += len(kwargs['text'])
		elif action == 'make_opd':
			opd_kwargs = kwargs.copy()
			opd_kwargs.pop('action', None)
			self.make_opd(edit, **opd_kwargs)
		elif action == 'new_test': self.new_test(edit)
		elif action == 'run_all_tests': self.run_all_tests()
		elif action == 'set_test_input': self.set_test_input(id=kwargs['id'], test=kwargs['data'])
		elif action == 'delete_test': self.delete_test(edit, kwargs['id'])
		elif action == 'erase_all': v.replace(edit, Region(0, v.size()), '\n')
		elif action == 'set_cursor_to_end':
			v.sel().clear()
			v.sel().add(Region(v.size(), v.size()))
		elif action == 'insert_opd_input':
			v.insert(edit, self.delta_input, kwargs['text'])
			self.delta_input += len(kwargs['text'])
		
		if hasattr(self, 'sync_read_only'):
			self.sync_read_only()

class ModifiedListener(sublime_plugin.EventListener):
	def on_selection_modified(self, view):
		if view.get_status('opd_info') == 'opdebugger-file' and not view.settings().get('edit_mode'):
			view.run_command('test_manager', { 'action': 'sync_read_only' })
	def on_hover(self, view, point, hover_zone):
		if hover_zone == sublime.HOVER_TEXT:
			view.run_command('view_tester', { 'action': 'get_var_value', 'pos': point })

class CloseListener(sublime_plugin.EventListener):
	def on_pre_close(self, view):
		if view.get_status('opd_info') == 'opdebugger-file':
			view.run_command('test_manager', {'action': 'close'})

class ViewTesterCommand(sublime_plugin.TextCommand):
	ROOT = dirname(__file__)
	ruler_opd_panel = 0.68
	have_tied_dbg = False
	use_debugger = False

	def create_opd(self, clr_tests=False, sync_out=True, use_debugger=False):
		v = self.view
		if v.is_dirty(): v.run_command('save')
		file_syntax = v.scope_name(v.sel()[0].begin()).rstrip().split()[0]
		file_name = v.file_name()
		window = v.window()
		v.erase_regions('crash_line')

		need_new = not (hasattr(self, 'have_tied_dbg') and self.have_tied_dbg and window.get_view_index(self.tied_dbg) != (-1, -1))

		if not need_new:
			dbg_view = self.tied_dbg
		else:
			dbg_view = window.new_file()
			self.tied_dbg = dbg_view
			self.have_tied_dbg = True
			if get_settings().get('close_sidebar'):
				try: sublime.set_timeout_async(lambda: window.set_sidebar_visible(False), 50)
				except: pass
			dbg_view.run_command('toggle_setting', {'setting': 'word_wrap'})

		if len(window.get_layout()['cols']) != 3 or window.get_layout()['cols'][1] >= 0.89:
			window.set_layout({'cols': [0, self.ruler_opd_panel, 1], 'rows': [0, 1], 'cells': [[0, 0, 1, 1], [1, 0, 2, 1]]})
		
		window.set_view_index(dbg_view, 1, 0)
		window.focus_view(v)
		window.focus_view(dbg_view)

		dbg_view.set_syntax_file('Packages/%s/TestSyntax.tmLanguage' % base_name)
		dbg_view.set_name(os.path.split(v.file_name())[-1] + ' -run')
		dbg_view.run_command('set_setting', {'setting': 'fold_buttons', 'value': False})
		dbg_view.run_command('test_manager', {
			'action': 'make_opd', 'build_sys': file_syntax, 'run_file': v.file_name(),
			'clr_tests': clr_tests, 'sync_out': sync_out, 'code_view_id': v.id(),
			'use_debugger': use_debugger
		})
	
	def run(self, edit, **kwargs):
		action = kwargs.get('action')
		if action == 'make_opd':
			if self.view.settings().get('syntax') == 'Packages/FastOlympicCoding/OPDebugger.tmLanguage':
				self.view.run_command('test_manager', {'action': 'make_opd', 'load_session': True, 'use_debugger': kwargs.get('use_debugger', False)})
			else:
				self.create_opd(clr_tests=kwargs.get('clr_tests', False), sync_out=kwargs.get('sync_out', True), use_debugger=kwargs.get('use_debugger', False))
		elif action == 'show_crash_line':
			pt = self.view.text_point(kwargs['crash_line'] - 1, 0)
			self.view.erase_regions('crash_line')
			self.view.add_regions('crash_line', [sublime.Region(pt, pt)],
				'variable.language.python', 'Packages/FastOlympicCoding/icons/arrow_right.png',
				sublime.DRAW_SOLID_UNDERLINE)
			sublime.set_timeout_async(lambda pt=pt: self.view.show_at_center(pt), 39)
		elif action == 'show_var_value':
			self.view.show_popup(highlight(kwargs['value']), sublime.HIDE_ON_MOUSE_MOVE_AWAY, kwargs['pos'])
		elif action == 'get_var_value':
			if hasattr(self, 'have_tied_dbg') and self.have_tied_dbg:
				pt = kwargs['pos']
				var_name = self.view.substr(self.view.word(pt))
				self.tied_dbg.run_command('test_manager', {'action': 'redirect_var_value', 'var_name': var_name, 'pos': pt})

class LayoutListener(sublime_plugin.EventListener):
	def on_new(self, view): self.move_syncer(view)
	def on_load(self, view): self.move_syncer(view)
	def move_syncer(self, view):
		try:
			w = view.window()
			if not w: return
			if view.name()[-4:] == '-run': w.set_view_index(view, 1, 0)
			elif w.get_view_index(view)[0] == 1:
				active_view_index = w.get_view_index(w.active_view_in_group(0))[1]
				w.set_view_index(view, 0, active_view_index + 1)
		except: pass