# Using the scitq-manage utility

scitq-manage is meant as a command line solution to do all the actions that can be done using the GUI. 

## syntax

```bash
scitq-manage [<global options>] <object> <verb> [<verb options>]
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
 

scitq-manage has an extensive inline documentation, you can launch 

- `scitq-manage -h` to get a global help message
- `scitq-manage <object> -h` to get some help on the action you can perform on a certain type of object (for instance `scitq-manage worker -h`)
- `scitq-manage <object> <verb> -h` to get some help on the options for a certain action (for instance `scitq-manage worker list -h`)

So this documentation will not go in all the details that comes with the inline help and are more accurate. The idea is just to give some examples.

## global options

There are only two of them:
`-s`
: only usefull if you do not have SCITQ_SERVER environment variable set, or if you can reach several servers. This is the server IP address or FQDN (not the URL, do not say :5000, the 5000 port is known)

`-t`
: timeout. By default there is a 150s timeout to get the result to a certain query. This is almost ever much more than required. However for some very specific heavy task involving large data management, increasing the timeout is a good idea (see [troubleshooting](troubleshoot.md#big-outputs)).

## worker

### list 

This will list the different worker in the manner of the [worker screen](gui.md#worker-screen-httpui). The handy `-L` option will display all the attributes (prefetch, and the different counters for the task success or failures).

```bash
scitq-manage worker list   

  worker_id  name          status      concurrency  creation_date               last_contact_date           batch
          1  epeire.local  running               1  2022-11-16 08:25:25.747354  2022-11-16 08:28:14.738917  Default
```

```bash
scitq-manage worker list -L

  worker_id  name          status      concurrency  creation_date               last_contact_date           batch      prefetch  assigned    accepted    running    failed    succeeded
          1  epeire.local  running               1  2022-11-16 08:25:25.747354  2022-11-16 08:27:42.418281  Default           0
```

### deploy

This will recruit a new worker using Ansible (with the same options as in the GUI [worker recruit](gui.md#recruiting)).

For instance this will deploy the same simple worker as in the GUI document:
```bash

scitq-manage worker deploy -f s1-2 -r GRA11 -b mybatch
```

### delete

This is the same as clicking on the trash icon right of the worker, for instance this will delete the node1 worker:
```bash
scitq-manage worker delete -n node1
```

### udpdate

This will enable to change concurrency, batch, prefetch of a worker. For instance to change the batch as in the GUI:
```bash
scitq-manage worker update -b test -n node1
```

## task

!!! note
    To launch a task, use `scitq-launch`, cf [usage](usage.md#queuing-a-task). The reason is practical: scitq-manage use python package argparse which makes syntax and inline documentation clear and simple. 
### list

Same as with worker list, use -L option to see all the parameters of the task and the complete command (which will be truncated otherwise)
```bash
scitq-manage task list -L      

  task_id  name    status    command     creation_date               modification_date           batch    container    container_options    input    output    resource
        1          running   sleep 1000  2022-11-16 13:30:19.733077  2022-11-16 13:30:24.114657  test
```

### relaunch

Like [relaunching with the GUI](gui.md#task-screen-httpuitask):

```bash
scitq-manage task relaunch -i 1
```
NB here no choice, our task has no name so we cannot use the `-n` option, we must use the task id with `-i`. You must use one of them.


### output

See the output of a task (stderr and stdout by default, but you can specify `-o` to see only stdout or `-e` to see only stderr):

```bash
scitq-manage task output -i 1
```

### update

Change a property of the task, like the command (`-c`) or the docker image (`-d`):

```bash
scitq-manage task update -i 1 -d ubuntu:latest
```

Unlike the GUI and you can change any property of the task - including the status, thus you can also relaunch a task using:
```bash
scitq-manage task update -i 1 -S pending
```


### delete

Just delete the task:

```bash
scitq-manage task delete -i 1
```


## batch

This mimics the [batch screen](gui.md#batch-screen-httpuibatch) of the GUI.
### list

Contrarily to the other list no option for this one.

```bash
scitq-manage batch list

batch    pending    accepted    running    failed      succeeded  workers
test                                                           1  epeire.local
```

### stop/go

This will pause the batch (the simple pause only) and relaunch the batch.

```bash
scitq-manage batch stop -n test
```

### delete

This will just delete a batch (and all the corresponding tasks)

