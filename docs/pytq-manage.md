# Using the pytq-manage utility

pytq-manage is meant as a command line solution to do all the actions that can be done using the GUI. 

## syntax

```bash
pytq-manage <object> <verb> <options>
```

The command takes two words, a first word that define the type of object you want to address, the second the action that must be performed. 

The different objects are:

- worker
- task
- batch

The actions are:

- list
- delete
- update (only worker, task)
- deploy (worker only)
- relauch (task only)
- output (task only)
- stop (batch only)
- go (batch only)
 

pytq-manage has an extensive inline documentation, you can launch 

- `pytq-manage -h` to get a global help message
- `pytq-manage <object> -h` to get some help on the action you can perform on a certain type of object (for instance `pytq-manage worker -h`)
- `pytq-manage <object> <verb> -h` to get some help on the options for a certain action (for instance `pytq-manage worker list -h`)

So this documentation will not go in all the details that comes with the inline help and are more accurate. The idea is just to give some examples.
## worker verbs

### list 

This will list the different worker in the manner of the [worker screen](gui.md#worker-screen-httpui). The handy `-L` option will display all the attributes (prefetch, and the different counters for the task success or failures).

```bash
% pytq-manage worker list   
  worker_id  name          status      concurrency  creation_date               last_contact_date           batch
          1  epeire.local  running               1  2022-11-16 08:25:25.747354  2022-11-16 08:28:14.738917  Default
% pytq-manage worker list -L
  worker_id  name          status      concurrency  creation_date               last_contact_date           batch      prefetch  assigned    accepted    running    failed    succeeded
          1  epeire.local  running               1  2022-11-16 08:25:25.747354  2022-11-16 08:27:42.418281  Default           0
```

### deploy

This will recruit a new worker using Ansible (with the same options as in the GUI [worker recruit](gui.md#recruiting)).

For instance this will deploy the same simple worker as in the GUI document:
```bash
pytq-manage worker deploy -f s1-2 -r GRA11 -b mybatch
```

### delete

This is the same as clicking on the trash icon right of the worker, for instance this will delete the node1 worker:
```bash
pytq-manage worker delete -n node1
```

### udpdate

This will enable to change concurrency, batch, prefetch of a worker. For instance to change the batch as in the GUI:
```bash
pytq-manage worker update -b test -n node1
```

## task

!!! note
    To launch a task, use `pytq-launch`, cf [usage](usage.md#queuing-a-task). The reason is practical: pytq-manage use python package argparse which makes syntax and inline documentation clear and simple. 
### list
