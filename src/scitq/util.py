import threading
import os
import boto3
from configparser import ConfigParser
import re
import stat

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

def package_version():
    """Return scitq package version"""
    import pkg_resources
    return pkg_resources.get_distribution(__package__).version


class xboto3:
    # this is an ugly hack to bypass the fact boto3 does not read all info
    # in .aws/config, notably OVH specific options, endpoint_url
    """This class is a replacement of boto3 library. It should be used like this:
    instead of:
    
    boto3.resource('s3') -> xboto3().resource('s3')

    boto3.client('s3') -> xboto3().client('s3')

    The constructor (xboto3()) accept a profile_name argument.

    """

    BOTO3_CONFIG_REGEXP = re.compile('(\S+) = (".*?"|\S+)')
    BOTO3_ACCEPTED_OPTIONS = ['endpoint_url']
    
    def __init__(self, profile_name='default'):
        """Retrieves boto3.resource, and fills in any service-specific 
        (filtered by BOTO3_ACCEPTED_OPTIONS, as some options are not used)    
        parameters from your config, which can be specified either        
        in AWS_CONFIG_FILE or ~/.aws/config (default). Similarly,         
        profile_name is 'default' (default) unless AWS_PROFILE is set.    
                                                                        
        Assumes that additional service-specific config is specified as:  
                                                                        
        [profile_name]                                                    
        service-name =                                                    
            parameter-name = parameter-value                              
        another-service-name =                                            
            ... etc                                                       
        
        adapted from: https://github.com/aws/aws-cli/issues/1270
        thanks to https://github.com/jaklinger
        """
        # Get the AWS config file path                                    
        self.profile_name = os.environ.get('AWS_PROFILE', profile_name)
        self.conf_filepath = os.environ.get('AWS_CONFIG_FILE', '~/.aws/config')
        self.aws_endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
        self.conf_filepath = os.path.expanduser(self.conf_filepath)
        
        self.service_cfg = {}
        
        if self.aws_endpoint_url:
            # Use environment variable if available
            self.service_cfg['endpoint_url']=self.aws_endpoint_url

    def __get_config__(self, service_name):
        config = dict(self.service_cfg)
        if os.path.exists(self.conf_filepath):
            parser = ConfigParser()
            with open(self.conf_filepath) as f:
                parser.read_file(f)
            cfg = dict(parser).get(f'profile {self.profile_name}', {})
            # Extract the service-specific config, if any                     
            service_raw_cfg = cfg.get(service_name, '')
            config.update({k: v for k, v in self.BOTO3_CONFIG_REGEXP.findall(service_raw_cfg)
                if k in self.BOTO3_ACCEPTED_OPTIONS})
        return config
        
    def resource(self, service_name, **kwargs):
        # Load in the service config, on top of other defaults            
        # and let boto3 do the rest                                       
        return boto3.resource(service_name=service_name,
                                **self.__get_config__(service_name), **kwargs)
    

    def client(self, service_name, **kwargs):
        # Load in the service config, on top of other defaults            
        # and let boto3 do the rest                                       
        return boto3.Session().client(
            service_name=service_name, **self.__get_config__(service_name), **kwargs
        )
    

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