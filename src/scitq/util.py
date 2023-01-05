import threading
import os
import boto3
from configparser import ConfigParser
import re

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


# this is an ugly hack to bypass the fact boto3 does not read all info
# in .aws/config, notably OVH specific options, endpoint_url

BOTO3_CONFIG_REGEXP = re.compile('(\S+) = (".*?"|\S+)')
BOTO3_ACCEPTED_OPTIONS = ['endpoint_url']

def boto3_resource(service_name, *, profile_name='default', **kwargs):
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
    profile_name = os.environ.get('AWS_PROFILE', profile_name)
    conf_filepath = os.environ.get('AWS_CONFIG_FILE', '~/.aws/config')
    aws_endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
    conf_filepath = os.path.expanduser(conf_filepath)
    
    service_cfg = {}
    
    if aws_endpoint_url:
        # Use environment variable if available
        service_cfg['endpoint_url']=aws_endpoint_url

    if os.path.exists(conf_filepath):
        parser = ConfigParser()
        with open(conf_filepath) as f:
            parser.read_file(f)
        cfg = dict(parser).get(f'profile {profile_name}', {})
        # Extract the service-specific config, if any                     
        service_raw_cfg = cfg.get(service_name, '')
        service_cfg = {k: v for k, v in BOTO3_CONFIG_REGEXP.findall(service_raw_cfg)
            if k in BOTO3_ACCEPTED_OPTIONS}
    
    # Load in the service config, on top of other defaults            
    # and let boto3 do the rest                                       
    return boto3.resource(service_name=service_name,
                              **service_cfg, **kwargs)
