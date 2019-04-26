from __future__ import unicode_literals
import json
import os
import sys

this_dir = os.path.abspath(os.path.dirname(__file__))

from logcatcolor.main import LogcatColor

filter_results = os.path.join(this_dir, ".filter_results")
mock_adb = os.path.join(this_dir, "mock-adb")

class MockObject(object):
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

class MockAdbLogcatColor(LogcatColor):
    def __init__(self, log, results, args=None, max_wait_count=None):
        LogcatColor.__init__(self, args=args)
        self.log = log
        self.results = results
        self.wait_count = 0
        self.max_wait_count = max_wait_count

    def get_adb_args(self):
        adb_args = LogcatColor.get_adb_args(self)
        adb_args[0:1] = [mock_adb, "--log", self.log, "--results", self.results]
        adb_args = [sys.executable] + adb_args
        return adb_args

    def wait_for_device(self):
        LogcatColor.wait_for_device(self)
        if self.max_wait_count:
            self.wait_count += 1
            if self.wait_count == self.max_wait_count:
                raise KeyboardInterrupt()

def test_filter(fn):
    def wrapped(data):
        result = fn(data)
        save_filter_results(fn.__name__, data, result)
        return result
    return wrapped

def save_filter_results(name, data, result):
    results = read_filter_results()
    if name not in results:
        results[name] = []

    results[name].append({
        "data": data,
        "result": result
    })

    with open(filter_results, "w") as f:
        f.write(json.dumps(results))

def read_filter_results():
    results = {}
    if os.path.exists(filter_results):
        with open(filter_results, "rt") as f:
            results = json.loads(f.read())

    return results
