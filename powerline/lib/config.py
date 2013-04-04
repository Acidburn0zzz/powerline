# vim:fileencoding=utf-8:noet

from powerline.lib.threaded import MultiRunnedThread
from powerline.lib.file_watcher import create_file_watcher

from threading import Event, Lock
from collections import defaultdict

import json


def open_file(path):
	return open(path, 'r')


def load_json_config(config_file_path, load=json.load, open_file=open_file):
	with open_file(config_file_path) as config_file_fp:
		return load(config_file_fp)


class ConfigLoader(MultiRunnedThread):
	def __init__(self, shutdown_event=None, watcher=None, load=load_json_config):
		super(ConfigLoader, self).__init__()
		self.shutdown_event = shutdown_event or Event()
		self.watcher = watcher or create_file_watcher()
		self._load = load

		self.pl = None
		self.interval = None

		self.lock = Lock()

		self.watched = defaultdict(set)
		self.missing = defaultdict(set)
		self.loaded = {}

	def set_pl(self, pl):
		self.pl = pl

	def set_interval(self, interval):
		self.interval = interval

	def register(self, function, path):
		'''Register function that will be run when file changes.

		:param function function:
			Function that will be called when file at the given path changes.
		:param str path:
			Path that will be watched for.
		'''
		with self.lock:
			self.watched[path].add(function)
			self.watcher.watch(path)

	def register_missing(self, condition_function, function, key):
		'''Register any function that will be called with given key each 
		interval seconds (interval is defined at __init__). Its result is then 
		passed to ``function``, but only if the result is true.
		
		:param function condition_function:
			Function which will be called each ``interval`` seconds. All 
			exceptions from it will be ignored.
		:param function function:
			Function which will be called if condition_function returns 
			something that is true. Accepts result of condition_function as an 
			argument.
		:param str key:
			Any value, it will be passed to condition_function on each call.

		Note: registered functions will be automatically removed if 
		condition_function results in something true.
		'''
		with self.lock:
			self.missing[key].add((condition_function, function))

	def unregister_functions(self, removed_functions):
		'''Unregister files handled by these functions.

		:param set removed_functions:
			Set of functions previously passed to ``.register()`` method.
		'''
		removes = []
		with self.lock:
			for path, functions in list(self.watched.items()):
				functions -= removed_functions
				if not functions:
					self.watched.pop(path)
					self.loaded.pop(path, None)

	def unregister_missing(self, removed_functions):
		'''Unregister files handled by these functions.

		:param set removed_functions:
			Set of pairs (2-tuples) representing ``(condition_function, 
			function)`` function pairs previously passed as an arguments to 
			``.register_missing()`` method.
		'''
		with self.lock:
			for key, functions in list(self.missing.items()):
				functions -= removed_functions
				if not functions:
					self.missing.pop(key)

	def load(self, path):
		try:
			# No locks: GIL does what we need
			return self.loaded[path]
		except KeyError:
			r = self._load(path)
			if self.interval is not None:
				self.loaded[path] = r
			return r

	def run(self):
		while self.interval is not None and not self.shutdown_event.is_set():
			toload = []
			with self.lock:
				for path, functions in self.watched.items():
					for function in functions:
						if self.watcher(path):
							function(path)
							toload.append(path)
			with self.lock:
				for key, functions in list(self.missing.items()):
					remove = False
					for condition_function, function in list(functions):
						try:
							path = condition_function(key)
						except Exception as e:
							self.exception('Error while running condition function for key {0}: {1}', key, str(e))
						else:
							if path:
								toload.append(path)
								function(path)
								functions.remove((condition_function, function))
					if not functions:
						self.missing.pop(key)
			for path in toload:
				try:
					self.loaded[path] = self._load(path)
				except Exception as e:
					self.exception('Error while loading {0}: {1}', path, str(e))
			self.shutdown_event.wait(self.interval)

	def exception(self, msg, *args, **kwargs):
		if self.pl:
			self.pl.exception(msg, prefix='config_loader', *args, **kwargs)
		else:
			raise
