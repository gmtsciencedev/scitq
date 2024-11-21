# troubleshooting

## debugging tasks

**New in v1.3** If you use Workflow, use `debug=True` in the Workflow and run it normally (`Workflow.run()` is mandatory in that case). This mode was meant to be intuitive and user friendly. You do not need more information than that to use it.

In more detail, it uses a text flow, and stop at each task, asking a question. Each answer is designated by a letter between brackets `[x]` with the first answer in capital, meaning it is the default answer. Just press the letter corresponding to the action you want (or nothing if the default choice is good for you) and press Enter.

Each task is done one at a time, displaying as much detail as possible on what is happening in scitq.

Each time a task is done, failed or succeeded, the question returns, what to do next? You can continue in debug mode as long as you wish, or you can quit, stoping all tasks, or you can exit to normal mode.

!!! note
    Contrarily to the old debug system below, tasks are executed normally, in a worker, they register in the database, so a task done in the new debug mode is not different from a task done in normal mode. For this reason, it is compatible with all other options, like automated worker recruitment or the `use_cache` option - this last option maybe particularly useful if the task to debug is somewhere in the middle of your workflow and you do not want to redo previous tasks each time you relaunch.

## troubleshooting a specific scitq task

Sometime a task might not behave in your docker like it should: switching from interactive to queued task is always a source of (joy and) surprises in any queuing system due to context issues (see [docker context](usage.md#docker--d) for instance). The execution can, however, be closely mimicked on any worker node using `scitq-manage debug run` command. It will run a command as closely as possible to scitq usual execution context, except it will be run locally and interactively (docker is run with `-d` flag in normal scitq execution, here it will be run with `-it`). For this to work, you need some queued task(s) in a batch. Having the batch in pause is advised (but not mandatory).

This will fetch randomly a task in the batch mybatch and launch it interactively:

```bash
scitq-manage debug run -b mybatch
```
More accurately, it fetch the resource, input, and docker and run it. If you want to change the command you may modify it, or change a shell script you would have in resource folder (to test) and you can retry. There are several useful flags to do add to the previous command:
- `-r`/'`--retry` won't redownload anything, (thus preserving any change you might have done in resource or input,
- `--no-resource` won't redownload resource, but will fetch randomly another task (with different inputs)),
- you might replace `-b mybatch` by `-i <taskid>` (the taskid should appear in the log) if commands differ from one input to another and you use `-r`.

Any error should appear more clearly in this context and if scitq classical debug output is not enough.

One important thing with `scitq-manage debug run` is that it never send the result to the database, so even if it succeed at some point, the task will not be considered succeeded, and output won't ever be uploaded (even if the task features an output instruction).

### minimal requirements for scitq-manage debug run to work

Obviously scitq should be installed. Then if your task use docker, docker should be installed. 

Some configuration may also be needed (it should not be needed on a normal worker when used as root as these are part of normal requirements of a worker).
Docker credentials should be set if you use a private registry (in `~/.docker/config.json`). Then if your task has some input from a cloud storage, you should install rclone (`apt install rclone`) and copy rclone configuration locally : `scitq-manage config rclone --install`.

To sum it up, the requirement are the same than for a normally deployed worker except scitq-worker service is not required to be installed and running.

## Ansible

### Specific Ansible errors
`error for nodeX: PLAY [Launch a compute instance] *********************************************** TASK [Gathering Facts] ********************************************************* ok: [localhost] TASK [Launch a VM] ************************************************************* fatal: [localhost]: FAILED! => {"changed": false, "extra_data": {"data": null, "details": "Invalid key_name provided.", "response": "{\"badRequest\": {\"code\": 400, \"message\": \"Invalid key_name provided.\"}}"}, "msg": "BadRequestException: 400: Client Error for url: https://compute.gra11.cloud.ovh.net/v2.1/XXXXXXXXXXXXXXXXXXXXXXX/servers, Invalid key_name provided."} PLAY RECAP ********************************************************************* localhost : ok=1 changed=0 unreachable=0 failed=1 skipped=0 rescued=0 ignored=0 `
:   The `keyname` parameter is wrong: either your forgot to change it in `/etc/ansible/inventory/common` or you forgot to deploy it on your provider console. Or maybe you deployed it but not on this region or not with this name.

`error for nodeX: PLAY [Launch a compute instance] *********************************************** TASK [Gathering Facts] ********************************************************* ok: [localhost] TASK [Launch a VM] ************************************************************* fatal: [localhost]: FAILED! => {"changed": false, "msg": "The instance is available but not Active state: ERROR"} PLAY RECAP ********************************************************************* localhost : ok=1 changed=0 unreachable=0 failed=1 skipped=0 rescued=0 ignored=0 `
:   An internal error of OpenStack, most likely an error of OVH when this reference is no more available in that region. OVH support confirms that you will not be charged for instances that are not available (stuck in ERROR or BUILD status). Simply delete the worker using the [GUI worker view](gui.md#worker-screen-httpui) delete icon and try another region. 

!!! note
    You might want to open OVH console as it will show the ERROR status of the instances quicker than waiting for scitq to display the error (that is because Ansible code is slow for this), but please do not use the OVH console to delete instances created with scitq: you can delete a server anytime with scitq, the code is very safe and will properly delete the objects and any modification Ansible has already done to your manager servers. When the line on the screen is gone, it means the Ansible delete worker procedure went fine and you can trust it was really deleted at provider level. However when you deal with a touchy reference (like the very good but rare i1-180), having the OVH console opened up to quickly know if you are in error or not is really nice. You can also call the support, they keep telling me I should call them to know how many instances of a certain type are available per region, but then I am terribly lazy...

`error for nodeX: PLAY [Launch a compute instance] *********************************************** TASK [Gathering Facts] ********************************************************* ok: [localhost] TASK [Add host and host related variables] ************************************* changed: [localhost] TASK [Launch a VM] ************************************************************* fatal: [localhost]: FAILED! => {"changed": false, "extra_data": {"data": null, "details": "None", "response": "None"}, "msg": "Timeout waiting for the server to come up."} PLAY RECAP ********************************************************************* localhost : ok=2 changed=1 unreachable=0 failed=1 skipped=0 rescued=0 ignored=0 `
:   This error occurs generally when you delete a worker before it had the chance to try three times to be deployed. You can ignore it safely if you deleted such a worker.

### Calling Ansible scripts manually

There are several things that can prove useful when using Ansible out of scitq automatic management:

#### Deploying a worker

A worker will automatically declare itself to the server when it is up, so recruiting manually a server out of scitq will work fine except when your tasks are done: such manually recruited workers will never be automatically deleted, you'll need to delete them manually.

If deploy fails (it will be tried 3 times in automatic mode) and you want to understand what is happening, this is also a good option.

```bash
source 7624350872955771-openrc.sh
cd $(scitq-manage ansible path)
ansible-playbook deploy_one_vm.yaml --extra-vars "nodename=node5 concurrency=1 status=running flavor=c2-180 region=GRA7 target=myscitq.server.dom"
```
The first line is loading OpenStack credentials (this file is provided by your cloud provider).
The second line put you in the standard place where Ansible playbooks should be when you have done the [install](install.md).
The third line is the deploying command, the same that scitq-server is using. The `target` variable is the FQDN of your scitq server. The other variables are usual variable for a worker.

NB calling manually ansible requires the presence of the worker object in database (this will be the case if the automatic ansible fails). If you need to do it manually also, connect to the database and create a worker like that:

```sql
INSERT INTO worker (name,hostname,flavor,provider,status,concurrency,prefetch,batch,region) VALUES ('node5','node5','c2-180','ovh','offline',1,0,'mybatch','GRA7');
```

#### Passing a specific command to a worker or a group of worker

Sometimes, it is very convenient to launch specific commands to some nodes:

```bash
ansible "node2 node6" -m shell -a "sudo docker ps"
```

#### Look at Ansible internal variables
Here for `node1` but it can be replaced with any host or group.
```
ansible node1 -m debug -a "var=hostvars[inventory_hostname]"
```

Notably this command will show you the scitq installed files version for ansible 
```bash
ansible bioit -m debug -a "var=version"
```
(if your version lags, redo the `scitq-manage ansible install`)


#### Connecting to a node

Of course as node are deployed with scitq server root SSH key, if you are already root on your scitq server, this is rather obvious. However there are two tricks that can make your life a lot easier there:

- First, the node are automatically inserted in (and removed from) `/etc/hosts`,
- Second, you should add this alias to your bash configuration: 
```bash
alias sssh="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
```

As we keep having nodes that are called the same (node1, node2, etc.) and that IP address and SSH identity is continually changing checking the host identity is very useless here and will requires a permanent and tedious management of `.ssh/known_hosts`. Now using `sssh` instead of `ssh` will enable you not to manage at all this file. So to go to node1, your command will just be:

```bash
sssh ubuntu@node6
```


#### Destroying a node manually with Ansible

Just in case, but you should not need that.

```bash
source 7624350872955771-openrc.sh
cd $(scitq-manage ansible path)
ansible-playbook destroy_vm.yaml --extra-vars "nodename=node5"
```


#### Playing with Ansible variables

Ansible see the file as a standalone python script in scitq extra inventory source (the one you added to your `inventory=...` ansible.cfg file). You can call the file directly like Ansible, but `scitq-manage` can be used to call it in a simpler way:

Just query the database with 
```bash
scitq-manage ansible inventory -h
```

```bash
usage: scitq-manage ansible inventory [-h] [--list] [--host HOST] [--add-host ADD_HOST] [--in-group IN_GROUP]
                                      [--for-host FOR_HOST] [--variable VARIABLE] [--value VALUE]
                                      [--del-host DEL_HOST]

(yaf) Ansible SQLite inventory script

optional arguments:
  -h, --help           show this help message and exit
  --list               List all hosts
  --host HOST          List one host in particular
  --add-host ADD_HOST  Add a host (in group Default unless --in-group is used)
  --in-group IN_GROUP  Specify in which group a host should be added
  --for-host FOR_HOST  Specify a host where to add variables
  --variable VARIABLE  Add a host variable (requires the host to be known, either with --add-host or with
                       --for-host, and requires a value set with --value), can be used several times
  --value VALUE        Add a host variable value (requires --variable, and thus the host to be known -
                       with --add-host or --for-host), can be used several times
  --del-host DEL_HOST  Delete a host
```

This is a very simple script but it can give you all the details you need on scitq Ansible managed workers. The very basic command is :
```bash
scitq-manage ansible inventory --list
```



## scitq task output

`You cannot attach to a stopped container, start it first`
:   This error occurs when a docker accept to start (the binary called was found and could be launched) but fails immediately after (a fraction second before python attach the docker process to a collecting thread). That is hopefully quite rare: look into the worker logs with `journalctl -u scitq-worker`, find the faulty docker launch, and launch it manually in the worker replacing -d option (detach) by -it (interactive), this will show the error.


## Specific cases

### Big outputs
Some programs (notably CAMISIM) are very verbose and generate huge output, so that maybe it is a good idea to redirect the output to a file and rely only on stderr to follow the tasks. If you really need to follow the output during execution, that is however not an option. There are two things you should take care of:

scitq will consume large amount of memory in the case, so be certain to have a significant amount of memory available. At least set up some swap, for instance like this:
```bash
fallocate -l 8G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
```

NB: You will have to add the following line in `/etc/fstab` to make it permanent (if required):
```fstab
/swapfile       none    swap    sw      0       0
```

Second, when querying the output of tasks, first forget the GUI, it won't be able to do it. Ideally, you have named your task and you know which one you're interested in, in which case go like this:
```bash
scitq-manage -t 600 task output -n mytaskname > mytaskname.output
```
Note the `-t 600` which tells the client library to be very patient (600s) before hitting timeout.

!!! note
    Be aware that REST is poorly adapted to large dataset and a modest 69Mb log (2 million lines, though) ended up as 19Gb REST message eating that amount of memory in scitq-server and at scitq-manage level upon reception. It did work, though, but I was looking at the server with top and added several swap files (as initially the server had only 8Gb memory...), which can be done live if you're in such a corner (the above procedure is extremely quick).

### Using variables and quote with scitq-launch

`scitq-launch` does the maximum to be userfriendly however it is used in a shell and there are certain limits.

When the launched command is not a shell, things are pretty simple, the only shell that can interpret the variable is the shell you are in when you run scitq-launch, and interpretation occurs only following the simple rules of shell interpretation:

- the variable is called directly like : `scitq-launch echo $VAR`,
- or the variable is used within a double quoted string : `scitq-launch echo "hello $VAR"`,
- in all other case (backslashing the $ sign or using single quoted string), `$VAR` will not be interpreted and will show as `$VAR` in the output, like for instance : `scitq-launch echo 'hello $VAR'`.

Note that `scitq-launch 'echo $VAR'` is improper and will throw an error `FileNotFoundError: [Errno 2] No such file or directory: 'echo $VAR'` in the error flow of the task.


Things get trickier when the command launched is a shell 

```bash
TEST=2
scitq-launch -n task1 sh -c "TEST=1; echo $TEST"
scitq-launch -n task2 sh -c 'TEST=1; echo $TEST'
```

The first case is similar to what happened in the `"hello $VAR"` exemple, `$TEST` is present in a double quoted string and is interpreted by the first shell, the one in which you run scitq-launch. In the second case, `$TEST` is protected by single quoted string ans is not interpreted, however as the task launched is a shell...

Well can you guess what will be the output of those two tasks?

- task1: 2
- task2: 1

Two more things on that topic:

First prefer **single quote** protection of the main string when using a shell command like this, it is more likely what you want:

```bash
scitq-launch -o s3://rnd/myresults/ sh -c 'echo "Hello world!" > $OUTPUT/result.txt'
```
You may remember that when tasks do not use a container, the special values `$OUTPUT`, `$INPUT`, `$TEMP`, `$RESOURCE` and `$CPU` (cf [No docker](usage.md#no-docker)) can be used to still use input, output and resource subsystems. 


Also be careful when trying to escape quotes. Say for instance you want to display `"l'avion"` (which means "the plane" in French). A rather nasty case because we have single and double quotes in that string, so the shell to do that is already a bit unfriendly:

```bash
echo "\"l'avion\""
```

With scitq, where you must protect from the initial shell and a python process, this becomes completely ugly:
```bash
scitq-launch echo "\"\\\"l'avion\\\"\""
```
# Upgrading servers and workers using Ansible

The server can be upgraded anytime. The workers will wait for it to come up again.

```bash
pip install --upgrade scitq
scitq-manage ansible install
systemctl restart scitq-queue scitq-main
```
NB : this does not use ansible, the command involving ansible is just in case the basic options of scitq ansible were changed.

In case you need to upgrade workers during a batch: (this command upgrade just the binaries on each worker, it does not restart anything)
```bash
cd $(scitq-manage ansible path)
ansible-playbook update_workers.yaml
```

To make the workers reload their binary, you can use the restart button on the page, or use a direct SQL command that will be seen below.
In either case: "reloading the binary" is really restarting scitq.client python code: it is not safe in the case of non-dockerized tasks. It is safe in principle in the case of dockerized tasks. It is really safe in the case of a restart with some task running and no task stoping at that moment. There is a mechanism to prevent restart during an upload. It is not 100% bullet proof yet. So the advice for now is to avoid live update if having to restart one or two tasks is not possible for you.

# Using SQL directly

## In case things turn bad
As a reminder, you must be very cautious when interacting directly with the database, at least during a work session. If something bad happens, the simplest thing to do is to stop the server (both services scitq-main and scitq-queue), drop the database and recreate it blank, it will be repopulated when the server starts (either service). All existing workers will redeclare themselves. All tasks will be lost, and also worker automated destruction will be brocken (you will have to delete them using the provider GUI in that case). You can also more specifically drop some tables, SQLalchemy will not modify existing tables but will recreate them if they are missing.

An easy protection to any error is to always protect modifications using transactions, which will give you the possibility to rollback and cancel a brocken change. Be aware that transactions will create locks so do not let them opened too long.

For what is next, SQL commands are reputed occuring in an SQL session which is opened with `sudo psql scitq` in standard setup with PostgreSQL (this only works locally on the SCITQ server unless you changed some parameters).

## Modifying commands
The first use case of direct interaction is to correct a list of command with a single instructions. While this could be done with clever use of `scitq-manage`, the efficiency is hugely improved in a direct SQL modification.

First have a look at your commands:
```sql
SELECT command FROM task WHERE batch='mybatch' LIMIT 10;
```

Then experience your change, let's say the current command is:
```bash
sh -c 'echo hello world!
```

Let's add the missing quote (as single quote are string boundaries in SQL, it must be doubled to appear in string) with a call to SQL REPLACE function:
```sql
SELECT REPLACE(command, 'world!', 'world!''') FROM task WHERE batch='mybatch' LIMIT 10;
```

It looks good? Ok, let's modify it:
```sql
BEGIN;
UPDATE task SET command=REPLACE(command, 'world!', 'world!''') WHERE batch='mybatch';
COMMIT;
```

You may also use the REGEXP_REPLACE SQL function, consider this real life example which will replace your command `<command>` by adding `sh -c '` before and closing the quote next, so that it become `sh -c '<commmand>'` (it will turn your command into a shell command):

```sql
BEGIN;
UPDATE task SET command=REGEXP_REPLACE(command,'(.*)','sh -c ''\1''') WHERE batch='mybatch';
COMMIT;
```

## Modifying the status of some failed tasks

This happen also sometime. Generally, you can restart tasks with the restart button in the GUI or using the API (with scitq.lib.Server.join call, and its retry argument), but if you have lots of them or if their status is 'succeeded' because the script or program in your command did not report correctly the error, then you may consider using the database directly - maybe in combination with a grouped command modification like the one above.

Let us say, you have a unique batch in the database, the batch is not yet finished but you have noticed that a subpart of the batch gives an apparent success that turns out to be a failure. A specific keyword can be seen in the error flow of those tasks, let us say the `error` keyword, that is not present is the real successes. 

So you can select the `task_id` of those tasks like that:
```sql
SELECT task_id FROM execution WHERE latest AND status='succeeded' AND error LIKE '%error%';
```
NB latest column is a boolean column which is true only if this is the latest execution.

Ok, so to relaunch those tasks, we have to set the execution as failed and set the failed tasks to pending - so that they are re-queued, and we must do the changes the other way around as we filter the execution by their `succeeded` status. :

```sql
BEGIN;
UPDATE task SET status='pending' WHERE task_id IN (SELECT task_id FROM execution WHERE latest AND status='succeeded' AND error LIKE '%error%');
UPDATE execution SET status='failed' WHERE latest AND status='succeeded' AND error LIKE '%error%';
COMMIT;
```

## Restarting all workers

This is the massive version of restart button in case of live update. Same caveat as previous: one or two tasks may be lost during the process, but it should be pretty safe in case of docker based tasks. Non dockerized tasks do not survive a restart.

```sql
BEGIN;
INSERT INTO signal (signal_id,worker_id,signal) SELECT worker_id,worker_id,-2 FROM worker;
COMMIT;
```

Naturally, you could add a WHERE clause just after the `FROM worker` to select workers (`WHERE name IN ('node1','node2',...)`).

Here is an extract of `scitq.constants`:

```python
SIGNAL_CLEAN=-1
SIGNAL_RESTART=-2
SIGNAL_RESET_RESOURCES=-3
```

So you can send this 3 different signals using a direct SQL command:

- The SIGNAL_CLEAN (-1) is the equivalent of clicking the clean button on the UI, it removes all unused folders in /scratch folder on workers,
- The SIGNAL_RESTART (-2) is to restart scitq.client on workers (for a live update),
- The SIGNAL_RESET_RESOURCES (-3) is used only when resources (in the meaning of `resource` option when launching a scitq task) unintentially overlapped and are corrupted: sending this signal will wipe all downloaded resources on worker and force them to redownload. This is rarely used and there is no button to do that, direct SQL is for now the only way to send the signal.

