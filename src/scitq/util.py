import threading
import os

class PropagatingThread(threading.Thread):
    """Taken from https://stackoverflow.com/questions/2829329/catch-a-threads-exception-in-the-caller-thread
    the join here will fails if one of the thread fails.
    """
    def run(self):
        """This version of run capture the exception occuring in the thread"""
        self.exc = None
        try:
            self.ret = self._target(*self._args, **self._kwargs)
        except BaseException as e:
            self.exc = e

    def join(self, timeout=None):
        """This version of join throw an exception if the thread joined did
        throw an exception"""
        super(PropagatingThread, self).join(timeout)
        if self.exc:
            raise self.exc
        return self.ret

    def is_alive(self):
        """This version of is_alive throw an exception if the thread ended
        with an exception"""
        if self.exc:
            raise self.exc
        return super(PropagatingThread, self).is_alive()

def package_path(*subdirs):
    """A very stupid hack to point to actual package data"""
    return os.path.join(os.path.dirname(__file__), *subdirs)