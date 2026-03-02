import sublime, sublime_plugin
import os
from os import path

from .settings import root_dir, settings_file, default_settings_file, \
			get_settings, is_run_supported_ext


class OlympicFuncsCommand(sublime_plugin.TextCommand):
	def run(self, edit, action=None, **kwargs):
		v = self.view

		if action == 'open_settings':
			v.window().run_command('new_window')
			sublime.active_window().set_sidebar_visible(False)
			
			sublime.active_window().open_file(path.join(root_dir, default_settings_file))
			sublime.active_window().set_layout({
				'cols': [0, 0.5, 1],
				'rows': [0, 1],
				'cells': [[0, 0, 1, 1], [1, 0, 2, 1]]
			})
			_opt_path = path.join(sublime.packages_path(), 'User', 'FastOlympicCoding.sublime-settings')
			if not path.exists(_opt_path):
				_opt = open(_opt_path, 'w')
				_opt.write('{\n\t\n}')
				_opt.close()

			_opt_view = sublime.active_window().open_file(_opt_path)
			sublime.active_window().set_view_index(_opt_view, 1, 0)


class GenListener(sublime_plugin.EventListener):
	"""Prevents running on unsupported file types."""

	def on_text_command(self, view, command_name, args):
		if command_name == 'view_tester':
			if not view.file_name():
				return
			ext = path.splitext(view.file_name())[1][1:]
			if args['action'] == 'make_opd':
				if not is_run_supported_ext(ext):
					return ('olympic_funcs', { 'action': 'pass' })
