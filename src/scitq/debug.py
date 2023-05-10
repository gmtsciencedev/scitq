from argparse import Namespace
import subprocess
import shlex
from .client import no_slash, docker_command
from .fetch import get
from multiprocessing import cpu_count
import os
import dotenv
import logging



class Debugger:
    """An object to debug a task"""

    def __init__(self,task,cpu=None,input_dir='input',output_dir='output',
                 resource_dir='resource', temp_dir='temp', 
                 get_resource=True, get_input=True, configuration=None,
                 extra_configuration=None):
        """Associate the task to debug with the debugger"""
        if type(task)==dict:
            self.task = Namespace(**task)
        else:
            self.task = task
        if cpu is None:
            self.cpu = cpu_count()
        else:
            self.cpu = cpu
        self.input_dir = os.path.abspath(no_slash(input_dir))
        self.output_dir = os.path.abspath(no_slash(output_dir))
        self.resource_dir = os.path.abspath(no_slash(resource_dir))
        self.temp_dir = os.path.abspath(no_slash(temp_dir))
        self.get_resource = get_resource
        self.get_input = get_input
        for configuration_item in [configuration, extra_configuration]:
            if configuration_item is not None and os.path.isfile(configuration_item):
                dotenv.load_dotenv(configuration_item)
        
            
        
        
    def prepare(self):
        "Do all the required actions before execution (preparing resources, inputs and other dirs)"
        for dir in [self.input_dir, self.output_dir, self.resource_dir, self.temp_dir]:
            if not os.path.exists(dir):
                os.mkdir(dir)
                os.chmod(dir, mode=0o777)
        if self.get_input and self.task.input:
            for data in self.task.input.split():
                get(data, self.input_dir+'/')
        if self.get_resource and self.task.resource:
            for data in self.task.resource.split():
                get(data, self.resource_dir+'/')

    def execute(self):
        "Do the execution of the task"
        logging.warning('Entering execution')
        self.process = None
        if not self.task.container:
            self.process = subprocess.run(
                    shlex.split(self.task.command),
                    env={
                        'CPU':str(self.cpu),
                        'INPUT': self.input_dir,
                        'OUTPUT': self.output_dir,
                        'TEMP': self.temp_dir,
                        'RESOURCE': self.resource_dir})
        else:
            self.process = subprocess.run(docker_command(command=self.task.command, 
                    container=self.task.container,
                    input_dir=self.input_dir,
                    output_dir=self.output_dir,
                    temp_dir=self.temp_dir,
                    resource_dir=self.resource_dir,
                    cpu=self.cpu,
                    extra_options=self.task.container_options,
                    mode='-it'),
                shell=False)

    def run(self):
        "Do the complete life cycle of the debug"
        logging.warning(f'Launching debugging for task {self.task.name or self.task.task_id} (id:{self.task.task_id})')
        self.prepare()
        self.execute()