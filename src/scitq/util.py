import threading
import multiprocessing
import traceback
import os
from configparser import ConfigParser
import re
import stat
import shutil
from argparse import Namespace
from .constants import PROTOFILTER_SYNTAX, PROTOFILTER_SEPARATOR
from functools import reduce
import hashlib
import sys

MAX_MD5_BLOCK_SIZE=1024**2

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

class PropagatingProcess(multiprocessing.Process):
    """Same as above but for a process: this is a process that propagate exceptions.
    """
    def __init__(self, *args, **kwargs):
        super(PropagatingProcess, self).__init__(*args, **kwargs)
        self._pconn, self._cconn = multiprocessing.Pipe()
        self._exception = None

    def run(self):
        try:
            super(PropagatingProcess, self).run()
            self._cconn.send(None)
        except Exception as e:
            tb = traceback.format_exc()
            self._cconn.send((e, tb))

    @property
    def exception(self):
        if self._pconn.poll():
            self._exception = self._pconn.recv()
        return self._exception

    def join(self, timeout=None):
        """This version of join throw an exception if the process joined did
        throw an exception"""
        ret=super(PropagatingProcess, self).join(timeout)
        if self.exception:
            error, tb = self.exception
            print(tb)
            raise error
        return ret

    def is_alive(self):
        """This version of is_alive throw an exception if the process ended
        with an exception"""
        if self.exception:
            error, tb = self.exception
            print(tb)
            raise error
        return super(PropagatingProcess, self).is_alive()

def package_path(*subdirs):
    """A very stupid hack to point to actual package data"""
    return os.path.join(os.path.dirname(__file__), *subdirs)

def package_version():
    """Return scitq package version"""
    import pkg_resources
    return pkg_resources.get_distribution(__package__).version

def check_dir(path):
    """Try to create dir for this path if it does not exists"""
    path,_ = os.path.split(path)
    if not os.path.exists(path):
        os.makedirs(path)

def to_dict(obj):
    """Return a dict from an object filtering on "normal" attributes"""
    return {k:v if type(v) in [str,int,float] else '' if v is None else str(v) for k,v in obj.__dict__.items() if not k.startswith('_')}

def tryupdate(mydict, key, f, *args, alternative=None, **kwargs):
    """Try to compute a certain value with a certain function and update a dict with it"""
    try:
        value=f(*args, **kwargs)
        mydict[key]=value
    except:
        if alternative is not None:
            mydict[key]=alternative
    return mydict

def isfifo(filepath):
    """Return True if file is a fifo"""
    return stat.S_ISFIFO(os.stat(filepath).st_mode)

def if_is_not_None(x, default):
    """A small helper function that replace None with a default value"""
    return x if x is not None else default

class colors:
    '''Colors class:reset all colors with colors.reset; two
    sub classes fg for foreground
    and bg for background; use as colors.subclass.colorname.
    i.e. colors.fg.red or colors.bg.greenalso, the generic bold, disable,
    underline, reverse, strike through,
    and invisible work with the main class i.e. colors.bold'''
    reset = '\033[0m'
    bold = '\033[01m'
    disable = '\033[02m'
    underline = '\033[04m'
    reverse = '\033[07m'
    strikethrough = '\033[09m'
    invisible = '\033[08m'
    blinking = '\033[05m'
    
    class fg:
        black = '\033[30m'
        red = '\033[31m'
        green = '\033[32m'
        orange = '\033[33m'
        blue = '\033[34m'
        purple = '\033[35m'
        cyan = '\033[36m'
        lightgrey = '\033[37m'
        darkgrey = '\033[90m'
        lightred = '\033[91m'
        lightgreen = '\033[92m'
        yellow = '\033[93m'
        lightblue = '\033[94m'
        pink = '\033[95m'
        lightcyan = '\033[96m'
        white = '\033[97m'
 
    class bg:
        black = '\033[40m'
        red = '\033[41m'
        green = '\033[42m'
        orange = '\033[43m'
        blue = '\033[44m'
        purple = '\033[45m'
        cyan = '\033[46m'
        lightgrey = '\033[47m'

def flat_list(l):
    """Return a list of value from a list of one-uplet containing the value"""
    return list([item[0] for item in l])

def force_hard_link(src, dst):
    """A function that force hardlink creation, possibly overriding anything existing before"""
    if os.path.exists(dst):
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        else:
            os.remove(dst)
    os.link(src, dst)

def filter_none(d):
    """filter out null value from a dict as well as key in remove list (default
    to ['id'])"""
    return dict([(k,v) for k,v in d.items() if v is not None])

def to_obj(d):
    """Transform a dict into an obj"""
    return Namespace(**d)

protofilter_syntax=re.compile(PROTOFILTER_SYNTAX)

def validate_protofilter(worker_flavor):
    """A function that raise an Exception if worker_flavor does not match expected syntax"""
    if worker_flavor.startswith('auto'):
        if PROTOFILTER_SEPARATOR in worker_flavor:
            for filter in worker_flavor.split(PROTOFILTER_SEPARATOR)[1:]:
                match=protofilter_syntax.match(filter)
                if not match:
                    raise RuntimeError(f'Protofilter syntax error in {worker_flavor}: {filter} is not recognized as a proper filter')
        else:
            if worker_flavor!='auto':
                raise RuntimeError(f'Protofilter syntax error, worker_flavor should be auto or auto{PROTOFILTER_SEPARATOR}... not {worker_flavor}')

def is_like(a,b):
    """A small helper to simulate SQL like function that use % as a widechar"""
    return bool(re.match(b.replace('%','.*'),a))

def has_tag(a,b):
    """A small helper to simulate protofilter # sign, e.g. a#b == a contain tags b"""
    return reduce(lambda x,y: x and y, [c in a for c in b], True)

def bytes_to_hex(byte_array):
    """Convert a byte array to hex"""
    return None if byte_array is None else byte_array.hex()

def get_md5(path):
    """Return the md5 of a local file"""
    with open(path, "rb") as f:
        if sys.version_info>=(3,11):
            return hashlib.file_digest(f, "md5").hexdigest()
        else:
            md5=hashlib.md5()
            while True:
                chunk=f.read(MAX_MD5_BLOCK_SIZE)
                if not chunk:
                    break
                md5.update(chunk)
            return md5.hexdigest()


def split_list(l, n):
    """Split list l in n parts of approximately the same size"""
    # avoid creating empty sublist
    n = min(n, len(l))
    k, m = divmod(len(l), n)
    return (l[i*k+min(i, m):(i+1)*k+min(i+1, m)] for i in range(n))