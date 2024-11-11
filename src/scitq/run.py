from typing import List, Tuple, Union, Optional, Iterable
from .fetch import check_uri, info, list_content, FetchError, fnmatch
from .lib import Server
import os
import itertools

server = Server(style='object')

def merge(lists: Iterable[Iterable]) -> Iterable:
    """Flatten a list of list, e.g. merge all the lists into one big list"""
    current = []
    for l in lists:
        current.extend(l)
    return current

class DeclarativeError:
    pass

class Item:
    """An item that goes through the workflow"""
    def __init__(self, name: str, uris: Iterable[str]):
        if len(name)==0:
            raise DeclarativeError('An item name cannot be empty')
        if name[0] in map(str,range(10)):
            raise DeclarativeError(f'An item name cannot start with a figure : {name}')
        self.name = name
        self.uris = uris
        self.nice_name = name.replace(' ','_')
    
    @property
    def uri_string(self):
        return ' '.join(self.uris)
    
    @property
    def uri_comma(self):
        return ','.join(self.uris)
    

class TaskItem(Item):
    def __init__(self, name: str, uris: Iterable[str], task: object):
        super().__init__(name, uris)
        self.task = task

class Flow:
    """An Item factory class: a class representing an item flow that will go through the workflow
    The flow contain N iterable of Item or subflow"""
    def __init__(self, name: str, **items: Iterable[Item]):
        self.name = name
        self.items = items
    def gather(self) -> 'Flow':
        """Create a new Flow with a unique item consisting of all the items"""
        return Flow(name=f'all {self.name}', 
                    **{subflow: list(subflow_items) for subflow, subflow_items in self.items.items()})
    def __add__(self, other: 'Flow') -> 'Flow':
        """Create a new Flow by (parallel) merging current Flow with one or several other Flows"""
        new_subflows=dict(self.items)
        new_subflows.update(other.items)
        return Flow(name=f'group of {", ".join([self.name, other.name])}',
                    **new_subflows)
    
    def __iter__(self):
        subflows = []
        subflows_items = []
        for subflow, subflow_items in self.items.items():
            subflows.append(subflow)
            subflows_items.append(subflow_items)
        for subflows_item in zip(*subflows_items):
            yield dict(zip(subflows, subflows_item))

    def chain(self, other: 'Flow') -> 'Flow':
        """Merge two flows sequentially, only possible if they have the same subflows"""
        if self.items.keys()!=other.items.keys():
            raise DeclarativeError('Chaining flows is only possible when they have the same subflows')
        new_subflows={}
        for subflow_name in self.items.keys():
            new_subflows[subflow_name] = itertools.chain(self.items[subflow_name], other.items[subflow_name])

    def filter(self, *keys: str) -> 'Flow':
        """Create a new Flow keeping only certain subflows from the initial Flow"""
        real_keys=[key for key in keys if key in self.items.keys()]
        if not real_keys:
            raise DeclarativeError('Cannot filter all subflows of a Flow: at least one subflow should remain')
        return Flow(self.name, **{key: items for key,items in self.items if key in real_keys})

    
class URI_factory_like:
    """A super class for URI_factory and Filtered_URI_factory"""
    def generate(self, item: Item) -> str:
        raise DeclarativeError('URI_factory_like classes should override a generate method')
    def check(self):
        raise DeclarativeError('URI_factory_like classes should override a check method')

class URI_factory(URI_factory_like):
    """A class representing a path generator in the form of a URI pattern, which looks like an URI but may contain:
    - {item.name} that will be replaced by item.name
    By convention, the invariable part of the name (before any variable) is caused the base"""
    def __init__(self, uri_pattern: str):
        if ':' not in uri_pattern:
            uri_pattern = f'file://{uri_pattern}'
        self.uri_pattern = uri_pattern
    def __div__(self, other: str) -> 'URI_factory':
        if other.startswith('/'):
            other=other[1:]
        if self.check()=='run+fastq':
            raise DeclarativeError(f'Subfolders ({other}) of run+fastq URI ({self.uri_pattern}) make no sense')
        return URI_factory(os.path.join(self.uri_pattern, other))
    def check(self):
        """Check the syntax of current URI pattern"""
        return check_uri(self.uri)
    def generate(self, items: dict[Item]) -> str:
        """Generate the real URI"""
        return self.uri_pattern.format(**items)

class Null_URI_Factory(URI_factory_like):
    """An URI factory that generate None each time"""
    def check(self):
        return None
    def generate(self, items: dict[Item]):
        return None

class TaskFactoryIterator:
    def __init__(self, task_factory: 'TaskFactory'):
        self.task_factory = task_factory
        self.__depends_iterator__ = iter(task_factory.depends)
    
    def __next__(self):
        items = next(self.__depends_iterator__)
        depends = []
        for item in items:
            if isinstance(item, TaskItem):
                depends.append(TaskItem.task)

        return 

class TaskFactory:
    """A class representing a Task factory, Task are created by the low level lib.Server.task_create depending on a Flow
    this Flow is typically the input_flow or a TaskFactory.outflow or a combination of Flows"""
    def __init__(self, command: str, depends: Flow, name: str=None,
                 input: Union[List[URI_factory_like],URI_factory_like]=[], 
                 output: Optional[URI_factory_like]=None,
                 container: Optional[str]=None):
        if not command:
            raise DeclarativeError('A task factory cannot have an empty commmand')
        self.command = command
        self.depends = depends
        if name:
            self.name = name
        else:
            self.name = command.split()[0]
        self.input = input if type(input)==list else [input]
        self.output = output if output else Null_URI_Factory()
        self.container = container
        self.__memory__ = {}
        self.__counter__ = 0

    def __iter__(self):
        return TaskFactoryIterator(self)        

    def __get__(self, items):
        if items not in self.__memory__:
            pass

    def __generate__(self, items):
        self.__counter__+=1
        if len(items)!=len(self.input):
            raise DeclarativeError('')
        return server.task_create(command=self.command.format(**items),
                                  name=f'{self.name} {items[0].name if items else self.__counter__}',
                                  container=self.container,
                                  input = items,
                                  output = self.output.generate(items))


    def outflow(self) -> Flow:
        return Flow(name=self,
                    items=[TaskItem(name=f'{task.name} output',
                                    task=task,
                                    uris=task.output) 
                                    for task in self])


class Workflow:
    class Meta:
        auto_output=False
        storage = URI_factory('{item.name}')

    def make_meta(self):
        class new_meta(self.Meta, Workflow.Meta):
            pass
        self.Meta = new_meta

    def list_task(self):
        return [item for item in self.__dict__ if isinstance(item, TaskFactory)]

    def rename_tasks(self):
        task_names = []
        for task in self.list_task():
            if task.name in task_names:
                i=2
                while f'{task.name}{i}' in task_names:
                    i+=1
                task.name = f'{task.name}{i}'
            task_names.append(task.name)

    def complete(self, task_factory: TaskFactory):
        if task_factory.output is None and self.Meta.auto_output:
            task_factory.output = self.Meta.storage / task_factory.name

    def __init__(self):
        self.make_meta()
        self.rename_tasks()
        for task in self.list_task():
            self.complete(task)

