# File: test_manager.py
# This is the final, complete, and corrected file.

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
			self.shrunk = True 
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
						<a href="test-click" class="test-name">Test {test_id} Passed</a>
						<span class="runtime">{runtime}</span>
						<a href="test-run" class="icon">⟳</a>
						<a href="test-edit" class="icon">✎</a>
					</div>
				</body>
				"""
				content = html_template.format(test_id=i, runtime=self.get_nice_runtime())
				content = '<style>' + styles + '</style>' + content
				return Phantom(Region(pt), content, sublime.LAYOUT_BLOCK, onclick)

			if not running:
				content = open(root_dir + '/Highlight/test_config.html').read()
				test_type = ''
				if is_passed:
					test_type = 'test-accept'
				elif str(self.rtcode) != '0' and self.rtcode is not None:
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
				content = content.format(
					test_id=i
				)
				content = '<style>' + styles + '</style>' + content
				return Phantom(Region(pt), content, sublime.LAYOUT_BLOCK, onclick)

		def get_accdec(self, i, pt, _cb_act, type, _view):	
			styles = get_test_styles(_view)
			content = open(root_dir + '/Highlight/test_accdec.html').read()
			content = content.format(
				test_id=i,
				type=type,
				runtime='&nbsp;' * (2 - len(str(self.runtime))) + str(self.runtime)
			)
			content = '<style>' + styles + '</style>' + content

			def onclick(event, cb=_cb_act, i=i):
				_cb_act(i, event)

			phantom = Phantom(Region(pt), content, sublime.LAYOUT_BLOCK, onclick)
			return phantom

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

		def __pipe_listener(self, pipe, on_out, bfsize=None):
			return "!INDEV\n"

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

		def del_test(self, nth):
			self.test_iter -= 1
			self.tests.pop(nth)
			self.prog_out.pop(nth)

		def set_tests(self, tests):
			self.tests.clear()
			for test in tests:	
				self.tests.append(TestManagerCommand.Test(test))

		def del_tests(self, to_del):
			dont_add = set(to_del)
			tests = self.tests
			out = self.prog_out
			new_tests = []
			new_out = []
			for i in range(len(tests)):
				if not i in dont_add:
					new_tests.append(tests[i])
					new_out.append(out[i])

			self.prog_out = new_out
			self.tests = new_tests
			self.test_iter -= len(to_del)

		def accept_out(self, nth):
			outs = self.prog_out
			tests = self.tests
			if nth >= len(outs):
				return None
			tests[nth].add_correct_answer(outs[nth].rstrip().lstrip())
			tests[nth].remove_uncorrect_answer(outs[nth].rstrip().lstrip())

		def decline_out(self, nth):
			outs = self.prog_out
			tests = self.tests
			if nth >= len(outs):
				return None
			tests[nth].remove_correct_answer(outs[nth].rstrip().lstrip())
			tests[nth].add_uncorrect_answer(outs[nth].rstrip().lstrip())

		def check_test(self, nth):
			return self.tests[nth].is_correct_answer(self.prog_out[nth])

		def terminate(self):
			self.process_manager.terminate()

	def insert_text(self, edit, text=None):
		v = self.view
		expected = v.line(self.delta_input).end()
		if len(v.sel()) > 1: return
		if v.sel()[0].a != expected or v.sel()[0].b != expected: return
		if text is None:
			if not self.tester.proc_run:
				return None
			to_shove = v.substr(Region(self.delta_input, v.sel()[0].b))
			v.insert(edit, v.sel()[0].b, '\n')
		else:
			to_shove = text
			v.insert(edit, v.sel()[0].b, to_shove + '\n')
		self.delta_input = v.sel()[0].b 
		self.tester.insert(to_shove + '\n')

	def insert_cb(self, edit):
		v = self.view
		s = sublime.get_clipboard()
		lst = s.split('\n')
		for i in range(len(lst) - 1):
			self.tester.insert(lst[i] + '\n', call_on_insert=True)
		self.tester.insert(lst[-1], call_on_insert=True)

	def toggle_fold(self, i):
		v = self.view
		tester = self.tester

		_inp = self.tester.tests[i].test_string
		_outp = self.tester.prog_out[i]
		text = _inp + '\n' + _outp.rstrip() + '\n' + '\n'
		tie_pos = self.get_tie_pos(i)

		if tester.tests[i].fold:
			v.run_command('test_manager', {
				'action': 'replace',
				'region': (tie_pos + 1, tie_pos + 1),
				'text': text
			})

			d = len(text)
			for j in range(i + 1, tester.test_iter):
				self.tester.tests[j].tie_pos += d

			tester.tests[i].fold = False
		else:
			v.run_command('test_manager', {
				'action': 'replace',
				'region': (tie_pos + 1, tie_pos + 1 + len(text)),
				'text': ''
			})

			d = len(text)
			for j in range(i + 1, tester.test_iter):
				tester.tests[j].tie_pos -= d

			tester.tests[i].fold = True
		v.sel().clear()
		v.sel().add(Region(v.size()))
		self.update_configs()

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

	def get_tie_pos(self, i):
		v = self.view
		tester = self.tester
		pt = 0
		for j in range(i):
			running = tester.proc_run and j == tester.running_test

			if running:
				pt += len(tester.tests[j].test_string) + len(tester.prog_out[j]) + 2
			elif not tester.tests[j].fold:
				pt += len(tester.tests[j].test_string) + len(tester.prog_out[j]) + 1
				if not running and str(tester.tests[j].rtcode) == '0' and tester.prog_out[j]:
					pt += 2

		return pt

	def on_test_action(self, i, event):
		v = self.view
		tester = self.tester
		
		is_passed = tester.tests[i].is_correct_answer(tester.prog_out[i]) and str(tester.tests[i].rtcode) == '0'

		if event == 'test-click':
			if is_passed:
				tester.tests[i].shrunk = not tester.tests[i].shrunk
			
			self.toggle_fold(i)
			return
		
		if tester.proc_run and event in {'test-edit', 'test-run'}:
			sublime.status_message('can not {action} while process running'.format(action=event))
			return

		if event == 'test-edit':
			self.open_test_edit(i)
		elif event == 'test-stop':
			tester.terminate()
		elif event == 'test-run':
			if not tester.tests[i].fold:
				self.toggle_fold(i)
			tie_pos = self.get_tie_pos(i)
			v.run_command('test_manager', {
				'action': 'replace',
				'region': (tie_pos, tie_pos),
				'text': '\n\n'
			})
			v.add_regions('type', \
				[Region(tie_pos + 1)], *self.REGION_BEGIN_PROP)

			self.input_start = tie_pos + 1
			self.delta_input = tie_pos + 1

			v.sel().clear()
			v.sel().add(Region(tie_pos + 1))

			self.prepare_code_view()
			tester.run_test(i)

	def on_accdec_action(self, i, event):
		v = self.view
		tester = self.tester
		if event == 'click-accept':
			tester.accept_out(i)
		elif event == 'click-decline':
			tester.decline_out(i)
		self.update_configs()
		self.memorize_tests()

	def set_test_input(self, test=None, id=None):
		v = self.view
		tester = self.tester
		unfold = False
		if not tester.tests[id].fold:
			self.toggle_fold(id)
			unfold = True

		tester.tests[id].test_string = test

		if unfold:
			self.toggle_fold(id)

		self.memorize_tests()

	def get_next_title(self):
		v = self.view
		styles = get_test_styles(v) 
		content = open(root_dir + '/Highlight/test_next.html').read()

		content = '<style>' + styles + '</style>' + content

		def onclick(event, v=v):
			v.run_command('test_manager', {
				'action': 'new_test'
			})	

		phantom = Phantom(Region(self.view.size() - 1), content, sublime.LAYOUT_BLOCK, onclick)
		return phantom

	def update_configs(self, update_last=None):
		v = self.view
		tester = self.tester
		
		if v.settings().get('edit_mode'): return

		configs = []
		if not tester: return
		
		if tester.proc_run:
			k = tester.test_iter + 1
		else:
			k = tester.test_iter
		k = min(k, len(tester.tests))
		
		pt = 0
		_last_test_entry = -1
		for i in range(k):
			running = tester.proc_run and i == tester.running_test
			is_passed = tester.tests[i].is_correct_answer(tester.prog_out[i]) and str(tester.tests[i].rtcode) == '0'

			config = tester.tests[i].get_config(
				i, pt, self.on_test_action, tester.prog_out[i], self.view, running=running
			)
			_last_test_entry = len(configs)
			configs.append(config)
			
			if is_passed and tester.tests[i].shrunk:
				pt += 1
			else:
				if running:
					pt += len(tester.tests[i].test_string) + len(tester.prog_out[i]) + 2
				elif not tester.tests[i].fold:
					pt += len(tester.tests[i].test_string) + len(tester.prog_out[i]) + 1

				if not running and not tester.tests[i].fold and str(tester.tests[i].rtcode) == '0' and tester.prog_out[i]:
					if tester.tests[i].is_correct_answer(tester.prog_out[i]):
						type = 'decline'
					else:
						type = 'accept'
					accdec = tester.tests[i].get_accdec(
						i, pt, self.on_accdec_action, type, self.view
					)
					configs.append(accdec)

				if not tester.tests[i].fold:
					pt += 2

		if not tester.proc_run:
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

		self.input_start = v.size()
		self.delta_input = v.size()
		self.output_start = v.size() + 1
		self.out_region_set = False

		v.add_regions('type', \
			[Region(v.size(), v.size())], *self.REGION_BEGIN_PROP)

		v.sel().clear()
		v.sel().add(Region(v.size()))

		self.tester.next_test(v.size() - 1, lambda: self.update_configs(update_last=True))
	
	def memorize_tests(self):
		if not hasattr(self, 'dbg_file'): return
		with open(get_tests_file_path(self.dbg_file), 'w') as f:
			f.write(sublime.encode_value([x.memorize() for x in (self.tester.get_tests())], True))

	def on_insert(self, s):
		self.view.run_command('test_manager', {'action': 'insert_opd_input', 'text': s})

	def on_out(self, s):
		v = self.view
		self.view.run_command('test_manager', {'action': 'insert_opd_out', 'text': s})
		if not self.out_region_set:
			self.out_region_set = True

	def on_stop(self, rtcode, runtime, crash_line=None):
		v = self.view
		tester = self.tester

		test_id = self.tester.running_test
		_inp = self.tester.tests[test_id].test_string
		_outp = self.tester.prog_out[test_id]
		_outp = _outp.rstrip()

		if tester.running_new:
			_outp += '\n' + '\n'

		self.tester.tests[test_id].set_cur_runtime(runtime)
		self.tester.tests[test_id].set_cur_rtcode(rtcode)

		v.erase_regions('type')
		line = v.line(self.input_start)

		input_end = v.line(Region(self.delta_input)).end()

		is_passed_now = self.tester.tests[test_id].is_correct_answer(self.tester.prog_out[test_id]) and str(rtcode) == '0'

		if tester.running_new and is_passed_now:
			v.run_command('test_manager', {
				'action': 'replace',
				'region': (self.input_start, input_end),
				'text': ''
			})
			tester.tests[test_id].fold = True
			tester.tests[test_id].shrunk = True
		else:
			v.run_command('test_manager', {
				'action': 'replace',
				'region': (self.input_start, input_end),
				'text': _inp + '\n' + _outp
			})

			self.tester.tests[test_id].fold = False
			self.tester.tests[test_id].shrunk = False

			v.add_regions(self.REGION_BEGIN_KEY % test_id, \
				[Region(line.begin(), line.end())], *self.REGION_BEGIN_PROP)

		v.show(self.input_start + 20)
		rtcode = str(rtcode)

		v.add_regions('test_end_%d' % test_id, \
			[Region(self.input_start + len(_inp) + 1, self.input_start + len(_inp) + 1)], \
				*self.REGION_END_PROP)

		v.run_command('test_manager', {'action': 'set_cursor_to_end'})

		tester = self.tester
		self.memorize_tests()
		if str(rtcode) == '0':
			if tester.running_new and tester.have_pretests():
				self.update_configs(update_last=True)
				sublime.set_timeout(lambda: v.run_command('test_manager', {'action': 'new_test'}), 10)
			else:
				sublime.set_timeout(self.update_configs, 100)
		else:
			sublime.set_timeout(self.update_configs, 100)

		cur_test = tester.running_test
		check = self.tester.check_test(cur_test)

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
		if self.tester:
			v.erase_regions('type')
			for i in range(-1, self.tester.test_iter + 1):
				v.erase_regions(self.REGION_BEGIN_KEY % i)
				v.erase_regions(self.REGION_END_KEY % i)
				v.erase_regions('line_%d' % i)
				v.erase_regions('test_error_%d' % i)

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

	# --- NEWLY ADDED/RESTORED FUNCTIONS ---
	def sync_read_only(self):
		view = self.view
		tester = self.tester

		err = True
		if tester and tester.proc_run:
			err = False
			forb_before = self.delta_input
			forb_after = view.line(self.delta_input).b
			forbs = [Region(0, forb_before)]
			forbs.append(Region(forb_after, view.size() - 1))

			for forb in forbs:
				for sel in view.sel():
					if forb.intersects(sel):
						err = True

			delete_forb = False
			for sel in view.sel():
				if sel.a == self.delta_input or sel.begin() == 0:
					delete_forb = True
					break

			view.settings().set('delete_forb', delete_forb)

		view.set_read_only(err)

	def change_process_status(self, status):
		self.view.set_status('process_status', status)
	# --- END OF NEWLY ADDED/RESTORED FUNCTIONS ---

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

		if v.settings().get('edit_mode'): self.apply_edit_changes()

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
					tests = [self.Test(x) for x in sublime.decode_value(f.read()) if x['test'].strip()]
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

		def compile(self=self, v=v):
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
		sublime.set_timeout_async(compile, 10)

	def delete_test(self, edit, id):
		if id < len(self.tester.tests):
			del self.tester.tests[id]
			if id < len(self.tester.prog_out):
				del self.tester.prog_out[id]
			self.tester.test_iter -= 1
			self.update_configs()
			self.memorize_tests()

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
		elif action == 'set_test_input': self.set_test_input(id=kwargs['id'], test=kwargs['data'])
		elif action == 'delete_test': self.delete_test(edit, kwargs['id'])
		elif action == 'erase_all': v.replace(edit, Region(0, v.size()), '\n')
		elif action == 'set_cursor_to_end':
			v.sel().clear()
			v.sel().add(Region(v.size(), v.size()))
		elif action == 'insert_opd_input':
			v.insert(edit, self.delta_input, kwargs['text'])
			self.delta_input += len(kwargs['text'])
		
		# Most actions will call sync_read_only, so we put it at the end
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