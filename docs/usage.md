# Usage

## Task definition 
As said in introduction, PYTQ is about distributing tasks, but what a task is has not been clearly defined. In the [quick start](../#quick-start), the proposed task is `echo 'Hello world!'`, that is a simple command, with its parameter(s), which make it pretty much what you want, but with some restrictions that are not explicit in that definition. 

### self contained
First, the task should be self contained, it should rely on a limited input known before launch time, and depends on a reasonable amount of (read-only shared) resources. There are two specific mechanics to answer to both points in PYTQ (respectively [input](#input) and [resource](#resource)). Be aware that PYTQ is not suited to interdependant tasks: there is a third mechanism to take care of result collection ([output](#output)), but this is not accessible by the other tasks that were programmed before the producing task ended.

### atomic
Second, the task should be atomic, that is finish after a certain computation time on its own with a return code, expressed with the Unix paradigm, 0 if it is ok, some other number if it is not. 

It excludes unix services and other never ending tasks, or task whoes ending status is always 0 (usually poorly coded programs) or the other way around. In fact it is not strictly impossible to use such tasks but you will not be able to use the error treatment capability of PYTQ. It also exclude tasks with user interaction.


### predictible (in terms of requirements: cpu, mem, disk)
That's the last one but not the least. Some programs are extremely nice (like pigz), they let you choose how many thread you will use and consume a reasonable amount of memory, plus they are very constant in their needs (you do not have to monitor them for hours to guess how they will behave). Some programs are very bad in that regard, they tend to be very variable in their needs during their computation time and they offer little or no controle over it. They are not impossible to work with but will give you a hard time.

PYTQ will not help you to know what your needs are so the basic rule is to run one task completely either with a resource surveying program (like Zabbix, free and excellent), or simply using top and watching.




# input

# resource

# output