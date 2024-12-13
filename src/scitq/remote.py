import importlib.util
import sys
import os
import inspect

from .fetch import copy

__remote_functions__ = {}
__reverse__ = {}
__copied__ = False
__resource__ = None

def get_importing_file():
    # Get the current stack trace
    stack = inspect.stack()
    
    # Find the frame of the caller
    # Frame [1] is the importer, [0] is the current function
    importing_frame = stack[-1]
    
    # Get the filename of the importer
    importing_file_path = importing_frame.filename
    return importing_file_path

__script_path__,__script_name__ = os.path.split(get_importing_file())

class RemoteException(Exception):
    pass

def remote(f, remote_name=None):
    """Register function f as a remote function"""
    if remote_name is None:
        remote_name = f.__name__

    __remote_functions__[remote_name]=f
    __reverse__[f]=remote_name


    return f

def resource(server):
    """Provide the task resource for the function"""
    global __copied__ 
    global __resource__
    if not __copied__:
        remote_uri = server.config_remote()
        if not remote_uri:
            raise RemoteException('You must declare a REMOTE_URI in your /etc/scitq.conf for remotes to work.')
        copy(f"file://{__script_path__}/{__script_name__}",os.path.join(remote_uri,__script_name__))
        __resource__ = os.path.join(remote_uri,__script_name__)
        __copied__ = True
    return __resource__

def is_remote(f):
    """Answer True if f was decorated with @remote"""
    return f in __reverse__

def command(f, container=True, args={}):
    """Provide the command for the function with its args"""
    if f not in __reverse__:
        raise RemoteException(f'Cannot find function {f.__name__} in remotes, did you decorate it?')
    remote_name = __reverse__[f]
    command_args = ' '.join([f'--{arg.replace("_","-")} "{value}"' for arg,value in args.items()])
    if container:
        return f"scitq-remote /resource/{__script_name__} {remote_name} {command_args}"
    else:
        return f"scitq-remote $RESOURCE/{__script_name__} {remote_name} {command_args}"

def __import_by_path__(file_path):
    """Import the original script when run by scitq-remote"""
    spec = importlib.util.spec_from_file_location('this', file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['this'] = module
    spec.loader.exec_module(module)
    return module

def __add_global_variable__(name, value):
    """
    Adds a global variable to the code that calls this function.
    NB: does nothing if the stack is of length 1.
    
    Args:
        name (str): The name of the global variable to add.
        value (any): The value of the global variable.
    """
    # Get the caller's frame (the file that called this function)
    stack = inspect.stack()
    if len(stack)>1:
        caller_frame = stack[-1].frame
        
        # Inject the variable into the caller's global scope
        caller_globals = caller_frame.f_globals
        caller_globals[name] = value

__add_global_variable__('__remote_functions__',__remote_functions__)

def run():
    __import_by_path__(sys.argv[1])
    function_name = sys.argv[2] 
    items=sys.argv[3:]
    args = {}
    while items:
        key=items.pop(0)
        if not key.startswith('--'):
            raise RemoteException('Args should start with --')
        key=key[2:].replace('-','_')
        value=items.pop(0)
        try:
            value=int(value)
        except ValueError:
            try:
                value=float(value)
            except ValueError:
                pass
        args[key]=value

    value = __remote_functions__[function_name](**args)
    if value is not None:
        print(value) 
